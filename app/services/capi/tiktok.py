import hashlib
import logging
import uuid
from datetime import datetime, timezone

import httpx

from app.config import get_settings
from app.models.order import Order

from app.services.capi.status import is_real_secret

logger = logging.getLogger(__name__)

_TIKTOK_EVENTS_URL = "https://business-api.tiktok.com/open_api/v1.3/event/track/"
_TIMEOUT = 10.0


def _sha256(value: str) -> str:
    return hashlib.sha256(value.lower().encode()).hexdigest()


def _hash_phone_tiktok(phone_e164: str) -> str:
    """Hash with leading +, e.g. +9665XXXXXXXX."""
    return _sha256(phone_e164)


def _build_event_data(order: Order, settings) -> dict:
    """Build one Events 2.0 event object for /open_api/v1.3/event/track/."""
    cookies = order.cookies or {}
    click_ids = order.click_ids or {}

    contents = [
        {"content_id": item["product_slug"], "quantity": item.get("quantity", 1)}
        for item in (order.items or [])
    ]

    user: dict = {
        "phone": _hash_phone_tiktok(order.phone_e164),
    }
    if order.client_ip:
        user["ip"] = order.client_ip
    if order.user_agent:
        user["user_agent"] = order.user_agent

    ttp = cookies.get("ttp") or cookies.get("_ttp")
    ttclid = click_ids.get("ttclid")
    if ttp:
        user["ttp"] = ttp
    if ttclid:
        user["ttclid"] = ttclid

    return {
        # One server-side purchase per order — browser pixel does not fire this event.
        "event": "PlaceAnOrder",
        "event_time": int(datetime.now(tz=timezone.utc).timestamp()),
        "event_id": order.event_id or str(uuid.uuid4()),
        "user": user,
        "page": {"url": order.landing_page or settings.FRONTEND_URL},
        "properties": {
            "value": float(order.total),
            "currency": "SAR",
            "content_type": "product",
            "contents": contents,
        },
    }


async def fire_purchase_event(order: Order) -> dict:
    """Send Purchase event to TikTok Events API. Returns result dict (never raises)."""
    settings = get_settings()
    if not is_real_secret(settings.TIKTOK_PIXEL_CODE) or not is_real_secret(
        settings.TIKTOK_ACCESS_TOKEN
    ):
        logger.warning(
            "TikTok CAPI skipped: set TIKTOK_PIXEL_CODE (or TIKTOK_PIXEL_ID) "
            "and TIKTOK_ACCESS_TOKEN in backend env"
        )
        return {"skipped": "not configured"}

    logger.info(
        "TikTok CAPI firing for order %s (pixel %s…)",
        order.order_number,
        settings.TIKTOK_PIXEL_CODE[:6],
    )

    payload = {
        "event_source": "web",
        "event_source_id": settings.TIKTOK_PIXEL_CODE,
        "data": [_build_event_data(order, settings)],
    }

    headers = {
        "Access-Token": settings.TIKTOK_ACCESS_TOKEN,
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(_TIKTOK_EVENTS_URL, json=payload, headers=headers)
            data = resp.json()
            logger.info("TikTok CAPI response for order %s: %s", order.order_number, data)
            return {"status_code": resp.status_code, "response": data}
    except Exception as exc:
        logger.error("TikTok CAPI error for order %s: %s", order.order_number, exc)
        return {"error": str(exc)}
