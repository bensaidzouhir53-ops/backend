import asyncio
import json
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, update
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.order import Order
from app.services.order_processing import should_process_order
from app.services.products import PRODUCT_CATALOG
from app.services.pricing import UPSELL_PRICE, calculate_item_price, get_fulfill_quantity

logger = logging.getLogger(__name__)
settings = get_settings()

_BASE_URL = "https://api.cod.network"
_TIMEOUT = 20.0
_SYNC_DELAY_SECONDS = 0.35


def _format_phone(phone_e164: str | None) -> str:
    if not phone_e164:
        return ""
    return phone_e164.strip().lstrip("+")


def _collect_line_items(order: Order, include_upsell: bool) -> list[dict]:
    lines: list[dict] = list(order.items or [])
    if include_upsell and order.upsell_item:
        lines.append(
            {
                "product_slug": order.upsell_item.get("product_slug", ""),
                "quantity": order.upsell_item.get("quantity", 1),
                "price": order.upsell_item.get("price"),
            }
        )
    return lines


def _line_price(item: dict) -> float:
    slug = str(item.get("product_slug", ""))
    qty = int(item.get("quantity", 1))
    if item.get("price") is not None:
        return float(item["price"])
    return calculate_item_price(slug, qty)


def _resolve_drop_product(slug: str) -> dict[str, str] | None:
    """Resolve COD Network SKU from Easypanel env (change anytime)."""
    store_meta = PRODUCT_CATALOG.get(slug, {})
    store_sku = store_meta.get("sku", slug)
    default_name = store_meta.get("name_ar", slug)

    product_map = settings.cod_network_product_map_parsed
    entry = product_map.get(slug)
    if isinstance(entry, dict) and entry.get("sku"):
        sku = settings.resolve_cod_network_sku(str(entry["sku"]).strip())
        return {
            "sku": sku,
            "name": str(entry.get("name") or default_name).strip(),
            "store_sku": store_sku,
        }
    if isinstance(entry, str) and entry.strip():
        return {
            "sku": settings.resolve_cod_network_sku(entry.strip()),
            "name": default_name,
            "store_sku": store_sku,
        }

    if store_sku:
        return {
            "sku": settings.resolve_cod_network_sku(store_sku),
            "name": default_name,
            "store_sku": store_sku,
        }

    default_sku = settings.cod_network_default_sku
    if default_sku:
        return {
            "sku": settings.resolve_cod_network_sku(default_sku),
            "name": settings.cod_network_default_name or default_name,
            "store_sku": store_sku,
        }
    return None


def _build_payload(order: Order, *, include_upsell: bool = False) -> dict | None:
    raw_lines = _collect_line_items(order, include_upsell)
    if not raw_lines:
        return None

    resolved_lines: list[dict] = []
    for item in raw_lines:
        slug = str(item.get("product_slug", ""))
        drop_product = _resolve_drop_product(slug)
        if not drop_product:
            logger.error(
                "COD Network: no SKU configured for slug %s (order %s). "
                "Set COD_NETWORK_PRODUCT_MAP or PRODUCT_CATALOG sku.",
                slug,
                order.order_number,
            )
            return None

        quantity = get_fulfill_quantity(slug, int(item.get("quantity", 1)))
        line_price = _line_price(item)
        resolved_lines.append(
            {
                "sku": drop_product["sku"],
                "product_name": drop_product["name"],
                "quantity": quantity,
                "price": line_price,
                "store_sku": drop_product.get("store_sku", slug),
            }
        )

    notes: list[str] = [
        f"order={order.order_number}",
        f"store={settings.FRONTEND_URL}",
        f"store_skus={','.join(line['store_sku'] for line in resolved_lines)}",
        f"cod_skus={','.join(line['sku'] for line in resolved_lines)}",
    ]
    if order.landing_page:
        notes.append(f"landing={order.landing_page}")
    if order.utm:
        utm_bits = [f"{k}={v}" for k, v in order.utm.items() if v]
        if utm_bits:
            notes.append("utm=" + ",".join(utm_bits))

    city = settings.COD_NETWORK_DEFAULT_CITY
    area = settings.COD_NETWORK_DEFAULT_AREA or city

    primary = resolved_lines[0]
    payload: dict = {
        "full_name": order.customer_name,
        "phone": _format_phone(order.phone_e164),
        "address": settings.COD_NETWORK_DEFAULT_ADDRESS,
        "city": city,
        "area": area,
        "country": settings.COD_NETWORK_COUNTRY,
        "currency": order.currency or "SAR",
        "sku_1": primary["sku"],
        "product_name_1": primary["product_name"],
        "quantity_1": primary["quantity"],
        "price_1": primary["price"],
        "notes": " | ".join(notes),
        "order-id": order.order_number,
        "items": [
            {
                "sku": line["sku"],
                "quantity": line["quantity"],
                "price": line["price"],
            }
            for line in resolved_lines
        ],
    }

    for index, line in enumerate(resolved_lines[1:], start=2):
        payload[f"sku_{index}"] = line["sku"]
        payload[f"product_name_{index}"] = line["product_name"]
        payload[f"quantity_{index}"] = line["quantity"]
        payload[f"price_{index}"] = line["price"]

    return payload


def _parse_response_body(body: str) -> dict | list | None:
    if not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def _extract_reference_id(parsed: dict | list | None) -> str | None:
    if not isinstance(parsed, dict):
        return None
    data = parsed.get("data")
    if isinstance(data, dict):
        for key in ("id", "lead_id", "order_id", "reference_id", "uuid"):
            value = data.get(key)
            if value is not None:
                return str(value)
    for key in ("id", "lead_id", "order_id", "reference_id", "uuid"):
        value = parsed.get(key)
        if value is not None:
            return str(value)
    return None


def _request_succeeded(result: dict) -> bool:
    if result.get("error"):
        return False
    status_code = result.get("status_code")
    if status_code not in (200, 201):
        return False
    parsed = result.get("body_parsed")
    if isinstance(parsed, dict):
        if parsed.get("status") == "error":
            return False
        if parsed.get("code") in (401, 403, 404, 422):
            return False
        if parsed.get("status") == "success":
            return True
    return True


def _is_items_not_found_error(parsed: dict | list | None) -> bool:
    if not isinstance(parsed, dict):
        return False
    code = parsed.get("code")
    message = str(parsed.get("message", "")).lower()
    return code == 41030 or "items object not found" in message


def _order_needs_cod_sync(order: Order) -> bool:
    if not should_process_order(order):
        return False
    if order.cod_network_sent_at is None:
        return True
    if not order.cod_network_response:
        return True
    return not _request_succeeded(order.cod_network_response)


def _endpoint_for_mode(mode: str) -> str:
    normalized = (mode or "lead").strip().lower()
    if normalized == "order":
        return f"/api/{settings.COD_NETWORK_API_VERSION}/seller/orders"
    return f"/api/{settings.COD_NETWORK_API_VERSION}/seller/leads"


async def _post_payload(payload: dict, mode: str) -> httpx.Response:
    url = f"{_BASE_URL}{_endpoint_for_mode(mode)}"
    headers = {
        "Authorization": f"Bearer {settings.COD_NETWORK_API_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(url, json=payload, headers=headers)
        return response


async def _persist_cod_result(
    db: AsyncSession,
    order: Order,
    result: dict,
    *,
    succeeded: bool,
    now: datetime,
) -> None:
    values: dict = {"cod_network_response": result}
    if succeeded:
        values["cod_network_sent_at"] = now
        reference_id = _extract_reference_id(result.get("body_parsed"))
        if reference_id:
            values["cod_network_reference_id"] = reference_id

    try:
        await db.execute(update(Order).where(Order.id == order.id).values(**values))
        await db.commit()
    except ProgrammingError as exc:
        await db.rollback()
        logger.error(
            "COD Network: DB columns missing for order %s — run migration 004. Error: %s",
            order.order_number,
            exc,
        )


async def send_order_to_cod_network(
    db: AsyncSession,
    order: Order,
    *,
    include_upsell: bool = False,
) -> bool:
    if not should_process_order(order):
        logger.info(
            "COD Network skipped for test order %s (PROCESS_TEST_ORDERS=false)",
            order.order_number,
        )
        return False
    if not settings.ENABLE_COD_NETWORK:
        logger.info("COD Network disabled (ENABLE_COD_NETWORK=false)")
        return False
    if not settings.COD_NETWORK_API_TOKEN:
        logger.warning(
            "COD Network skipped for %s: COD_NETWORK_API_TOKEN is not set",
            order.order_number,
        )
        return False

    payload = _build_payload(order, include_upsell=include_upsell)
    if not payload:
        result = {
            "error": "missing_drop_product_sku",
            "hint": (
                "Set COD_NETWORK_SKU or COD_NETWORK_PRODUCT_MAP in Easypanel backend env"
            ),
        }
        await _persist_cod_result(
            db, order, result, succeeded=False, now=datetime.now(tz=timezone.utc)
        )
        return False

    now = datetime.now(tz=timezone.utc)
    try:
        resp = await _post_payload(payload, settings.COD_NETWORK_MODE)
        parsed = _parse_response_body(resp.text)

        # Some seller SKUs reject the items array — retry with sku_1 fields only.
        if resp.status_code >= 400 and _is_items_not_found_error(parsed):
            fallback_payload = {k: v for k, v in payload.items() if k != "items"}
            logger.warning(
                "COD Network items rejected for %s (sku=%s), retrying without items array",
                order.order_number,
                payload.get("sku_1"),
            )
            resp = await _post_payload(fallback_payload, settings.COD_NETWORK_MODE)
            parsed = _parse_response_body(resp.text)

        result = {
            "status_code": resp.status_code,
            "body": resp.text[:2000],
            "body_parsed": parsed,
            "endpoint": _endpoint_for_mode(settings.COD_NETWORK_MODE),
            "sku_sent": payload.get("sku_1"),
            "skus_sent": [item.get("sku") for item in payload.get("items", [])],
        }
        if resp.status_code >= 400:
            logger.error(
                "COD Network rejected order %s: HTTP %s — %s",
                order.order_number,
                resp.status_code,
                resp.text[:500],
            )
        else:
            logger.info(
                "COD Network %s for order %s: HTTP %s ref=%s sku=%s",
                settings.COD_NETWORK_MODE,
                order.order_number,
                resp.status_code,
                _extract_reference_id(parsed),
                payload.get("sku_1"),
            )
    except Exception as exc:
        result = {"error": str(exc)}
        logger.error(
            "COD Network failed for order %s: %s",
            order.order_number,
            exc,
        )

    succeeded = _request_succeeded(result)
    await _persist_cod_result(db, order, result, succeeded=succeeded, now=now)
    return succeeded


async def send_order_created(db: AsyncSession, order: Order) -> bool:
    return await send_order_to_cod_network(db, order, include_upsell=False)


async def send_upsell_accepted(db: AsyncSession, order: Order) -> bool:
    return await send_order_to_cod_network(db, order, include_upsell=True)


async def sync_order_to_cod_network(db: AsyncSession, order: Order) -> bool:
    include_upsell = order.upsell_item is not None
    return await send_order_to_cod_network(db, order, include_upsell=include_upsell)


async def sync_pending_orders_to_cod_network(
    db: AsyncSession,
    *,
    include_all: bool = False,
) -> dict[str, int]:
    if not settings.ENABLE_COD_NETWORK or not settings.COD_NETWORK_API_TOKEN:
        return {"attempted": 0, "succeeded": 0, "failed": 0, "skipped": 0}

    result = await db.execute(select(Order).order_by(Order.created_at.asc()))
    orders = list(result.scalars().all())

    stats = {"attempted": 0, "succeeded": 0, "failed": 0, "skipped": 0}
    for order in orders:
        if not include_all and not _order_needs_cod_sync(order):
            stats["skipped"] += 1
            continue

        stats["attempted"] += 1
        ok = await sync_order_to_cod_network(db, order)
        if ok:
            stats["succeeded"] += 1
        else:
            stats["failed"] += 1
        await asyncio.sleep(_SYNC_DELAY_SECONDS)

    logger.info("COD Network sync finished: %s", stats)
    return stats


async def sync_pending_orders_on_startup() -> None:
    if not settings.ENABLE_COD_NETWORK or not settings.COD_NETWORK_API_TOKEN:
        return

    from app.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            stats = await sync_pending_orders_to_cod_network(db, include_all=False)
            if stats["attempted"]:
                logger.info(
                    "Startup COD Network sync: attempted=%s succeeded=%s failed=%s",
                    stats["attempted"],
                    stats["succeeded"],
                    stats["failed"],
                )
    except Exception as exc:
        logger.error("Startup COD Network sync failed: %s", exc)
