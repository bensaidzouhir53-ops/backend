import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.order import Order
from app.models.tracking_event import TrackingEvent
from app.schemas.order import (
    AcceptUpsellRequest,
    AcceptUpsellResponse,
    CreateOrderRequest,
    CreateOrderResponse,
)
from app.services import (
    cod_network,
    order_number as order_number_svc,
    pricing,
    phone_validator,
    sheet_webhook,
)
from app.services.whatsapp_welcome import send_order_welcome
from app.services.order_processing import should_process_order
from app.services.phone_whitelist import is_whitelisted_phone
from app.services.phone_blacklist import is_blacklisted_phone
from app.services.capi import meta as meta_capi
from app.services.capi import tiktok as tiktok_capi
from app.services.capi import snapchat as snap_capi
from app.services.capi.status import provider_status

logger = logging.getLogger(__name__)
router = APIRouter(tags=["orders"])


def _get_client_ip(request: Request, override: str | None) -> str | None:
    if override:
        return override
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    if request.client:
        return request.client.host
    return None


async def _fire_capi_and_store(
    db: AsyncSession,
    order: Order,
    event_name: str = "Purchase",
    *,
    force: bool = False,
) -> None:
    """Fire all CAPI integrations concurrently; store a single TrackingEvent row."""
    settings = get_settings()

    if not force and not should_process_order(order):
        logger.info(
            "CAPI skipped for test order %s (PROCESS_TEST_ORDERS=false)",
            order.order_number,
        )
        return
    if not settings.ENABLE_CAPI:
        logger.info("CAPI disabled (ENABLE_CAPI=false) — skipping order %s", order.order_number)
        return

    existing = await db.execute(
        select(TrackingEvent).where(
            TrackingEvent.order_id == order.id,
            TrackingEvent.event_name == event_name,
            TrackingEvent.provider_results.isnot(None),
        )
    )
    if existing.scalar_one_or_none():
        logger.info(
            "CAPI %s already fired for order %s — skipping duplicate",
            event_name,
            order.order_number,
        )
        return

    status = provider_status(settings)
    logger.info(
        "CAPI dispatch for order %s — meta=%s tiktok=%s snap=%s force=%s",
        order.order_number,
        status["meta"]["ready"],
        status["tiktok"]["ready"],
        status["snapchat"]["ready"],
        force,
    )

    meta_result, tiktok_result, snap_result = await asyncio.gather(
        meta_capi.fire_purchase_event(order),
        tiktok_capi.fire_purchase_event(order),
        snap_capi.fire_purchase_event(order),
        return_exceptions=True,
    )

    def _safe(r):
        if isinstance(r, Exception):
            return {"error": str(r)}
        return r

    provider_results = {
        "meta": _safe(meta_result),
        "tiktok": _safe(tiktok_result),
        "snapchat": _safe(snap_result),
    }

    tracking_event = TrackingEvent(
        id=uuid.uuid4(),
        event_name=event_name,
        event_id=order.event_id,
        order_id=order.id,
        payload={
            "order_id": str(order.id),
            "order_number": order.order_number,
            "total": float(order.total),
            "currency": order.currency,
            "items": order.items,
            "test_order": force or order.status == "test",
        },
        provider_results=provider_results,
        created_at=datetime.now(tz=timezone.utc),
    )
    db.add(tracking_event)
    await db.commit()
    logger.info("CAPI finished for order %s — stored tracking_event", order.order_number)


async def _fire_capi_only(order_id: uuid.UUID) -> None:
    """Fire Meta/TikTok/Snap CAPI for test orders (no COD/sheet/WhatsApp). Never raises."""
    from app.database import AsyncSessionLocal

    logger.info("CAPI-only hook started for test order_id=%s", order_id)
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Order).where(Order.id == order_id))
            order = result.scalar_one_or_none()
            if not order:
                logger.error("CAPI-only hook: order %s not found", order_id)
                return
            await _fire_capi_and_store(db, order, "Purchase", force=True)
    except Exception as exc:
        logger.error("CAPI-only hook error for %s: %s", order_id, exc)


@router.post("/orders", response_model=CreateOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    body: CreateOrderRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> CreateOrderResponse:
    # Idempotency: if same event_id already exists, return existing order
    if body.event_id:
        existing = await db.execute(
            select(Order).where(Order.event_id == body.event_id)
        )
        existing_order = existing.scalar_one_or_none()
        if existing_order:
            logger.info(
                "Duplicate event_id %s — returning existing order %s (CAPI not re-fired)",
                body.event_id,
                existing_order.order_number,
            )
            upsell_offer = pricing.get_upsell_offer(body.items)
            return CreateOrderResponse(
                order_id=existing_order.id,
                order_number=existing_order.order_number,
                subtotal=float(existing_order.subtotal),
                total=float(existing_order.total),
                currency=existing_order.currency,
                upsell=upsell_offer,
            )

    # Server-side phone validation & normalisation
    phone_e164, phone_national = phone_validator.validate_saudi_phone(body.phone)

    if is_blacklisted_phone(body.phone) or is_blacklisted_phone(phone_e164):
        logger.warning(
            "Blocked order attempt from blacklisted phone (national=%s)",
            phone_national,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "تعذر إتمام الطلب من هذا الرقم. يرجى التواصل مع خدمة العملاء.",
            },
        )

    client_ip = _get_client_ip(request, body.client_ip)

    # Server-side price calculation
    subtotal = pricing.calculate_subtotal(body.items)
    total = subtotal

    # Generate order number
    order_number = await order_number_svc.generate_order_number(db)

    user_agent = body.user_agent or request.headers.get("User-Agent")

    items_json = [item.model_dump() for item in body.items]

    is_test = is_whitelisted_phone(body.phone) and not get_settings().PROCESS_TEST_ORDERS

    order = Order(
        id=uuid.uuid4(),
        order_number=order_number,
        customer_name=body.customer_name.strip(),
        phone_e164=phone_e164,
        phone_national=phone_national,
        status="test" if is_test else "pending",
        subtotal=subtotal,
        upsell_total=0,
        total=total,
        currency="SAR",
        payment_method="COD",
        items=items_json,
        upsell_item=None,
        landing_page=body.landing_page,
        utm=body.utm.model_dump() if body.utm else None,
        click_ids=body.click_ids.model_dump() if body.click_ids else None,
        cookies=body.cookies.model_dump(by_alias=False) if body.cookies else None,
        event_id=body.event_id,
        client_ip=client_ip,
        user_agent=user_agent,
        created_at=datetime.now(tz=timezone.utc),
        updated_at=datetime.now(tz=timezone.utc),
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)

    logger.info("Order created: %s (total: %.2f SAR)", order.order_number, order.total)

    if is_test:
        logger.info(
            "Test order %s — fulfillment skipped; Meta CAPI still fires for pixel testing",
            order.order_number,
        )
        # Whitelist/test phones skip COD/sheet/WhatsApp, but must still hit Meta CAPI
        # so Events Manager / Test Events can verify the pixel + token.
        background_tasks.add_task(_fire_capi_only, order.id)
    else:
        background_tasks.add_task(_fire_post_order_hooks, order.id)

    upsell_offer = pricing.get_upsell_offer(body.items)

    return CreateOrderResponse(
        order_id=order.id,
        order_number=order.order_number,
        subtotal=float(order.subtotal),
        total=float(order.total),
        currency=order.currency,
        upsell=upsell_offer,
    )


async def _fire_post_order_hooks(order_id: uuid.UUID) -> None:
    """Run sheet webhook + CAPI after order is committed. Never raises."""
    from app.database import AsyncSessionLocal

    logger.info("Post-order hooks started for order_id=%s", order_id)
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Order).where(Order.id == order_id))
            order = result.scalar_one_or_none()
            if not order:
                logger.error("Post-order hook: order %s not found", order_id)
                return

            if not should_process_order(order):
                logger.info(
                    "Post-order hooks skipped for test order %s",
                    order.order_number,
                )
                return

            hook_tasks = [
                sheet_webhook.send_order_created(db, order),
                cod_network.send_order_created(db, order),
                send_order_welcome(order),
                _fire_capi_and_store(db, order, "Purchase"),
            ]

            results = await asyncio.gather(
                *hook_tasks,
                return_exceptions=True,
            )
            hook_labels = ("sheet_webhook", "cod_network", "whatsapp_welcome", "capi")
            for label, result in zip(hook_labels, results, strict=True):
                if isinstance(result, Exception):
                    logger.error(
                        "Post-order hook %s failed for %s: %s",
                        label,
                        order_id,
                        result,
                    )
    except Exception as exc:
        logger.error("Post-order hook error for %s: %s", order_id, exc)


@router.post(
    "/orders/{order_id}/upsell",
    response_model=AcceptUpsellResponse,
    status_code=status.HTTP_200_OK,
)
async def accept_upsell(
    order_id: uuid.UUID,
    body: AcceptUpsellRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> AcceptUpsellResponse:
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Order not found"},
        )

    if order.upsell_item is not None:
        # Already upsold — idempotent response
        return AcceptUpsellResponse(
            order_id=order.id,
            order_number=order.order_number,
            upsell_total=float(order.upsell_total),
            total=float(order.total),
            currency=order.currency,
        )

    upsell_price = pricing.UPSELL_PRICE
    new_upsell_total = upsell_price
    new_total = float(order.subtotal) + new_upsell_total

    order.upsell_item = {
        "product_slug": body.product_slug,
        "quantity": body.quantity,
        "price": upsell_price,
    }
    order.upsell_total = new_upsell_total
    order.total = new_total
    order.updated_at = datetime.now(tz=timezone.utc)

    # Preserve original event_id unless upsell provides its own
    if body.event_id and not order.event_id:
        order.event_id = body.event_id

    await db.commit()
    await db.refresh(order)

    logger.info(
        "Upsell accepted for order %s: %s (new total: %.2f SAR)",
        order.order_number,
        body.product_slug,
        order.total,
    )

    background_tasks.add_task(_fire_post_upsell_hooks, order.id)

    return AcceptUpsellResponse(
        order_id=order.id,
        order_number=order.order_number,
        upsell_total=float(order.upsell_total),
        total=float(order.total),
        currency=order.currency,
    )


async def _fire_post_upsell_hooks(order_id: uuid.UUID) -> None:
    """Run sheet webhook after upsell is committed. Never raises."""
    from app.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Order).where(Order.id == order_id))
            order = result.scalar_one_or_none()
            if not order:
                logger.error("Post-upsell hook: order %s not found", order_id)
                return

            if not should_process_order(order):
                logger.info(
                    "Post-upsell hooks skipped for test order %s",
                    order.order_number,
                )
                return

            results = await asyncio.gather(
                sheet_webhook.send_upsell_accepted(db, order),
                cod_network.send_upsell_accepted(db, order),
                _fire_capi_and_store(db, order, "Purchase"),
                return_exceptions=True,
            )
            for label, result in zip(
                ("sheet_webhook", "cod_network", "capi"),
                results,
                strict=True,
            ):
                if isinstance(result, Exception):
                    logger.error(
                        "Post-upsell hook %s failed for %s: %s",
                        label,
                        order_id,
                        result,
                    )
    except Exception as exc:
        logger.error("Post-upsell hook error for %s: %s", order_id, exc)


@router.post(
    "/orders/{order_id}/upsell/decline",
    status_code=status.HTTP_200_OK,
)
async def decline_upsell(
    order_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Order not found"},
        )

    if order.upsell_item is not None:
        return {
            "order_id": str(order.id),
            "order_number": order.order_number,
            "total": float(order.total),
            "currency": order.currency,
            "cod_sent": order.cod_network_sent_at is not None,
        }

    background_tasks.add_task(_fire_post_upsell_decline_hooks, order.id)

    return {
        "order_id": str(order.id),
        "order_number": order.order_number,
        "total": float(order.total),
        "currency": order.currency,
        "cod_pending": True,
    }


async def _fire_post_upsell_decline_hooks(order_id: uuid.UUID) -> None:
    """Send base-order COD lead + CAPI after customer declines upsell."""
    from app.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Order).where(Order.id == order_id))
            order = result.scalar_one_or_none()
            if not order:
                logger.error("Post-upsell decline hook: order %s not found", order_id)
                return

            if not should_process_order(order):
                logger.info(
                    "Post-upsell decline hooks skipped for test order %s",
                    order.order_number,
                )
                return

            if order.upsell_item is not None:
                logger.info(
                    "Post-upsell decline skipped for %s — upsell already accepted",
                    order.order_number,
                )
                return

            ok = await cod_network.send_order_created(db, order)
            if not ok:
                logger.error(
                    "COD Network decline sync failed for order %s",
                    order.order_number,
                )
    except Exception as exc:
        logger.error("Post-upsell decline hook error for %s: %s", order_id, exc)
