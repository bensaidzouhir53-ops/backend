import hashlib
import logging
import time
import uuid

import httpx

from app.config import get_settings
from app.models.order import Order

from app.services.capi.status import is_real_secret

logger = logging.getLogger(__name__)

_SNAP_CAPI_URL = "https://tr.snapchat.com/v2/conversion"
_TIMEOUT = 10.0


def _sha256(value: str) -> str:
    return hashlib.sha256(value.lower().encode()).hexdigest()


def _hash_phone_snap(phone_e164: str) -> str:
    """Hash without leading +, e.g. 9665XXXXXXXX."""
    return _sha256(phone_e164.lstrip("+"))


async def fire_purchase_event(order: Order) -> dict:
    """Send PURCHASE event to Snapchat CAPI. Returns result dict (never raises)."""
    settings = get_settings()
    if not is_real_secret(settings.SNAP_PIXEL_ID) or not is_real_secret(
        settings.SNAP_ACCESS_TOKEN
    ):
        logger.warning(
            "Snapchat CAPI skipped: set SNAP_PIXEL_ID and SNAP_ACCESS_TOKEN "
            "(remove placeholder values like your_id)"
        )
        return {"skipped": "not configured"}

    logger.info(
        "Snapchat CAPI firing for order %s (pixel %s…)",
        order.order_number,
        settings.SNAP_PIXEL_ID[:6],
    )

    cookies = order.cookies or {}
    click_ids = order.click_ids or {}

    user_data: dict = {
        "ph": _hash_phone_snap(order.phone_e164),
        "client_ip_address": order.client_ip,
        "client_user_agent": order.user_agent,
    }
    sc_click_id = click_ids.get("sc_click_id")
    scid = cookies.get("scid") or cookies.get("_scid")
    if sc_click_id:
        user_data["sc_click_id"] = sc_click_id
    if scid:
        user_data["scid"] = scid

    payload = {
        "pixel_id": settings.SNAP_PIXEL_ID,
        "event_type": "PURCHASE",
        "event_conversion_type": "WEB",
        "event_tag": "Purchase",
        "timestamp": int(time.time() * 1000),
        "event_id": order.event_id or str(uuid.uuid4()),
        "user_data": user_data,
        "custom_data": {
            "price": float(order.total),
            "currency": "SAR",
            "order_id": str(order.id),
        },
    }

    headers = {
        "Authorization": f"Bearer {settings.SNAP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(_SNAP_CAPI_URL, json=payload, headers=headers)
            data = resp.json()
            logger.info(
                "Snapchat CAPI response for order %s: %s", order.order_number, data
            )
            return {"status_code": resp.status_code, "response": data}
    except Exception as exc:
        logger.error("Snapchat CAPI error for order %s: %s", order.order_number, exc)
        return {"error": str(exc)}
