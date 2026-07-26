import asyncio
import json
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.order import Order
from app.services.order_processing import should_process_order
from app.services.products import PRODUCT_CATALOG
from app.services.pricing import get_fulfill_quantity, order_has_pending_upsell

logger = logging.getLogger(__name__)
settings = get_settings()

_TIMEOUT = 15.0
_RIYADH = ZoneInfo("Asia/Riyadh")
_SYNC_DELAY_SECONDS = 0.35


def _format_sheet_date(dt: datetime | None) -> str:
    if dt is None:
        dt = datetime.now(tz=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(_RIYADH)
    return local.strftime("%d/%m/%Y")


def _format_sheet_phone(phone_e164: str | None) -> str:
    if not phone_e164:
        return ""
    return phone_e164.strip().lstrip("+")


def _collect_line_items(order: Order, include_upsell: bool) -> list[dict]:
    lines: list[dict] = list(order.items or [])
    if include_upsell and order.upsell_item:
        upsell = order.upsell_item
        lines.append(
            {
                "product_slug": upsell.get("product_slug", ""),
                "quantity": upsell.get("quantity", 1),
            }
        )
    return lines


def _webhook_succeeded(result: dict) -> bool:
    if result.get("error"):
        return False
    status_code = result.get("status_code")
    if status_code is not None and status_code >= 400:
        return False
    body = result.get("body", "")
    if not body:
        return status_code == 200 if status_code is not None else False
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return status_code == 200 if status_code is not None else False
    return parsed.get("ok") is True


def _order_needs_sheet_sync(order: Order) -> bool:
    if not should_process_order(order):
        return False
    if order.sheet_sent_at is None:
        return True
    if not order.sheet_response:
        return True
    return not _webhook_succeeded(order.sheet_response)


def _build_payload(order: Order) -> tuple[str, dict]:
    include_upsell = order.upsell_item is not None
    event = "upsell_accepted" if include_upsell else "order_created"
    payload = {
        "event": event,
        **build_sheet_payload(order, include_upsell=include_upsell),
    }
    return event, payload


def build_sheet_payload(order: Order, *, include_upsell: bool = False) -> dict:
    """Build a flat payload matching the Google Sheet column layout."""
    products: list[str] = []
    skus: list[str] = []
    quantities: list[str] = []

    for item in _collect_line_items(order, include_upsell):
        slug = item.get("product_slug", "")
        meta = PRODUCT_CATALOG.get(slug, {})
        products.append(meta.get("name_ar", slug))
        skus.append(meta.get("sku", slug))
        quantities.append(
            str(
                get_fulfill_quantity(
                    slug,
                    int(item.get("quantity", 1)),
                )
            )
        )

    return {
        "date": _format_sheet_date(order.created_at),
        "order_id": order.order_number,
        "country": "KSA",
        "name": order.customer_name,
        "phone": _format_sheet_phone(order.phone_e164),
        "product": "/".join(products),
        "sku": "/".join(skus),
        "quantity": "/".join(quantities),
        "total_price": float(order.total),
        "currency": "SAR",
        "status": "",
        "url": order.landing_page or "",
    }


async def _post_to_google_apps_script(url: str, payload: dict) -> httpx.Response:
    """
    POST to a Google Apps Script web app URL.

    GAS runs doPost on the /exec URL, then returns 302 to a googleusercontent
    echo URL that only accepts GET (POST there returns 405).
    """
    headers = {"Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(
            url.strip(),
            json=payload,
            headers=headers,
            follow_redirects=False,
        )

        if response.status_code in (301, 302, 303, 307, 308):
            redirect_url = response.headers.get("location")
            if not redirect_url:
                response.raise_for_status()
                return response
            logger.info("Sheet webhook redirect -> %s", redirect_url[:120])
            response = await client.get(redirect_url, follow_redirects=True)

        response.raise_for_status()
        return response


def _sheet_send_cod_flag() -> bool:
    """Backend owns COD when configured; Apps Script should only mirror the sheet."""
    return not (
        settings.ENABLE_COD_NETWORK and bool(settings.COD_NETWORK_API_TOKEN)
    )


async def send_order_created(db: AsyncSession, order: Order) -> bool:
    """Send new order row to Google Sheets."""
    if not should_process_order(order):
        logger.info(
            "Sheet webhook skipped for test order %s (PROCESS_TEST_ORDERS=false)",
            order.order_number,
        )
        return False
    if not settings.ENABLE_SHEET_WEBHOOK:
        logger.info("Sheet webhook disabled (ENABLE_SHEET_WEBHOOK=false)")
        return False
    if not settings.GOOGLE_SHEET_WEBHOOK_URL:
        logger.warning(
            "Sheet webhook skipped for %s: GOOGLE_SHEET_WEBHOOK_URL is not set",
            order.order_number,
        )
        return False

    payload = {
        "event": "order_created",
        "send_cod": _sheet_send_cod_flag()
        and not order_has_pending_upsell(
            list(order.items or []),
            order.upsell_item,
        ),
        **build_sheet_payload(order, include_upsell=False),
    }
    return await _post_webhook(db, order, payload)


async def send_upsell_accepted(db: AsyncSession, order: Order) -> bool:
    """Update existing sheet row after upsell is accepted."""
    if not should_process_order(order):
        logger.info(
            "Sheet upsell webhook skipped for test order %s (PROCESS_TEST_ORDERS=false)",
            order.order_number,
        )
        return False
    if not settings.ENABLE_SHEET_WEBHOOK:
        return False
    if not settings.GOOGLE_SHEET_WEBHOOK_URL:
        logger.warning(
            "Sheet webhook skipped for upsell on %s: GOOGLE_SHEET_WEBHOOK_URL is not set",
            order.order_number,
        )
        return False

    payload = {
        "event": "upsell_accepted",
        "send_cod": _sheet_send_cod_flag(),
        **build_sheet_payload(order, include_upsell=True),
    }
    return await _post_webhook(db, order, payload)


async def sync_order_to_sheet(db: AsyncSession, order: Order) -> bool:
    """Send or update one order on the sheet (used for backfill/retry)."""
    if not settings.ENABLE_SHEET_WEBHOOK:
        return False
    if not settings.GOOGLE_SHEET_WEBHOOK_URL:
        logger.warning(
            "Sheet sync skipped for %s: GOOGLE_SHEET_WEBHOOK_URL is not set",
            order.order_number,
        )
        return False

    _, payload = _build_payload(order)
    return await _post_webhook(db, order, payload)


async def _post_webhook(db: AsyncSession, order: Order, payload: dict) -> bool:
    now = datetime.now(tz=timezone.utc)
    try:
        resp = await _post_to_google_apps_script(
            settings.GOOGLE_SHEET_WEBHOOK_URL or "",
            payload,
        )
        result = {"status_code": resp.status_code, "body": resp.text[:500]}
        logger.info("Sheet webhook sent for order %s: %s", order.order_number, result)
    except Exception as exc:
        result = {"error": str(exc)}
        logger.error(
            "Sheet webhook failed for order %s: %s", order.order_number, exc
        )

    succeeded = _webhook_succeeded(result)
    values: dict = {"sheet_response": result}
    if succeeded:
        values["sheet_sent_at"] = now

    await db.execute(
        update(Order)
        .where(Order.id == order.id)
        .values(**values)
    )
    await db.commit()
    return succeeded


async def sync_pending_orders_to_sheet(
    db: AsyncSession,
    *,
    include_all: bool = False,
) -> dict[str, int]:
    """
    Push database orders to Google Sheets.

    By default only orders never synced or previously failed are sent.
    Set include_all=True to attempt every order (duplicates are skipped by Apps Script).
    """
    if not settings.ENABLE_SHEET_WEBHOOK or not settings.GOOGLE_SHEET_WEBHOOK_URL:
        logger.warning("Sheet sync skipped: webhook disabled or URL not configured")
        return {"attempted": 0, "succeeded": 0, "failed": 0, "skipped": 0}

    result = await db.execute(select(Order).order_by(Order.created_at.asc()))
    orders = list(result.scalars().all())

    stats = {"attempted": 0, "succeeded": 0, "failed": 0, "skipped": 0}

    for order in orders:
        if not include_all and not _order_needs_sheet_sync(order):
            stats["skipped"] += 1
            continue

        stats["attempted"] += 1
        ok = await sync_order_to_sheet(db, order)
        if ok:
            stats["succeeded"] += 1
        else:
            stats["failed"] += 1

        await asyncio.sleep(_SYNC_DELAY_SECONDS)

    logger.info("Sheet sync finished: %s", stats)
    return stats


async def sync_pending_orders_on_startup() -> None:
    """Background job: sync any orders missing from the sheet after deploy/restart."""
    if not settings.ENABLE_SHEET_WEBHOOK or not settings.GOOGLE_SHEET_WEBHOOK_URL:
        return

    from app.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            stats = await sync_pending_orders_to_sheet(db, include_all=False)
            if stats["attempted"]:
                logger.info(
                    "Startup sheet sync: attempted=%s succeeded=%s failed=%s",
                    stats["attempted"],
                    stats["succeeded"],
                    stats["failed"],
                )
    except Exception as exc:
        logger.error("Startup sheet sync failed: %s", exc)


async def send_order_created_by_id(db: AsyncSession, order_id) -> None:
    """Load order from DB then send to sheet (safe for background tasks)."""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        logger.error("Sheet webhook: order %s not found", order_id)
        return
    await send_order_created(db, order)


async def send_upsell_accepted_by_id(db: AsyncSession, order_id) -> None:
    """Load order from DB then update sheet row (safe for background tasks)."""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        logger.error("Sheet webhook upsell: order %s not found", order_id)
        return
    await send_upsell_accepted(db, order)
