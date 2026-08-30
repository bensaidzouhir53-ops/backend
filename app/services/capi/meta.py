import hashlib
import logging
import time
import uuid

import httpx

from app.config import get_settings
from app.models.order import Order

from app.services.capi.status import is_real_secret

logger = logging.getLogger(__name__)

_META_CAPI_URL = "https://graph.facebook.com/v22.0/{pixel_id}/events"
_TIMEOUT = 10.0


def _sha256(value: str) -> str:
    return hashlib.sha256(value.lower().encode()).hexdigest()


def _hash_phone_meta(phone_e164: str) -> str:
    """Hash phone without leading +, e.g. 9665XXXXXXXX."""
    return _sha256(phone_e164.lstrip("+"))


def _format_fbc(cookie_fbc: str | None, fbclid: str | None) -> str | None:
    """Meta requires fbc as fb.1.{ms}.{fbclid}, not a raw fbclid query param."""
    for raw in (cookie_fbc, fbclid):
        if not raw:
            continue
        value = raw.strip()
        if not value:
            continue
        if value.startswith("fb."):
            return value
        return f"fb.1.{int(time.time() * 1000)}.{value}"
    return None


async def _fire_to_pixel(
    label: str,
    pixel_id: str,
    access_token: str,
    event: dict,
    test_event_code: str | None,
) -> dict:
    """Fire a single event to one Meta pixel. Returns result dict (never raises)."""
    payload: dict = {
        "data": [event],
        "access_token": access_token,
    }
    if test_event_code:
        payload["test_event_code"] = test_event_code

    url = _META_CAPI_URL.format(pixel_id=pixel_id)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            data = resp.json()
            if resp.status_code >= 400 or data.get("error"):
                error = data.get("error") or {}
                if error.get("code") == 190:
                    logger.error(
                        "Meta CAPI invalid access token for pixel %s — regenerate in "
                        "Events Manager → Settings → Generate access token (token usually starts with EAA)",
                        pixel_id[:6],
                    )
                logger.error(
                    "Meta CAPI failed for %s pixel %s (status=%s): %s",
                    label,
                    pixel_id[:6],
                    resp.status_code,
                    data,
                )
            else:
                logger.info(
                    "Meta CAPI OK for %s pixel %s: %s",
                    label,
                    pixel_id[:6],
                    data,
                )
            return {"pixel_id": pixel_id, "status_code": resp.status_code, "response": data}
    except Exception as exc:
        logger.error(
            "Meta CAPI error for %s pixel %s: %s",
            label,
            pixel_id[:6],
            exc,
        )
        return {"pixel_id": pixel_id, "error": str(exc)}


async def fire_purchase_event(order: Order) -> dict:
    """Send Purchase event to all configured Meta pixels. Returns result dict (never raises)."""
    settings = get_settings()
    pixel_token_pairs = settings.meta_pixel_token_pairs

    if not pixel_token_pairs:
        logger.warning(
            "Meta CAPI skipped: set META_PIXEL_ID + META_ACCESS_TOKEN (or _2/_3 pairs) in backend env"
        )
        return {"skipped": "not configured"}

    logger.info(
        "Meta CAPI firing for order %s to %d pixel(s): %s",
        order.order_number,
        len(pixel_token_pairs),
        [p[:6] + "…" for p, _ in pixel_token_pairs],
    )

    cookies = order.cookies or {}
    click_ids = order.click_ids or {}

    user_data: dict = {
        "ph": [_hash_phone_meta(order.phone_e164)],
        # Meta rejects events with insufficient customer info (error 2804050)
        "client_user_agent": order.user_agent
        or "Mozilla/5.0 (compatible; NafaasCAPI/1.0)",
    }
    if order.client_ip:
        user_data["client_ip_address"] = order.client_ip
    fbp = cookies.get("fbp") or cookies.get("_fbp") or click_ids.get("fbp")
    fbc = _format_fbc(
        cookies.get("fbc") or cookies.get("_fbc"),
        click_ids.get("fbclid"),
    )
    if fbp:
        user_data["fbp"] = fbp
    if fbc:
        user_data["fbc"] = fbc

    content_ids = [item["product_slug"] for item in (order.items or [])]
    if order.upsell_item and order.upsell_item.get("product_slug"):
        upsell_slug = order.upsell_item["product_slug"]
        if upsell_slug not in content_ids:
            content_ids.append(upsell_slug)

    event: dict = {
        "event_name": "Purchase",
        "event_id": order.event_id or str(uuid.uuid4()),
        "event_time": int(time.time()),
        "action_source": "website",
        "event_source_url": order.landing_page or settings.FRONTEND_URL,
        "user_data": user_data,
        "custom_data": {
            "value": float(order.total),
            "currency": "SAR",
            "order_id": str(order.id),
            "content_ids": content_ids,
            "content_type": "product",
        },
    }

    import asyncio

    results = await asyncio.gather(
        *[
            _fire_to_pixel(
                f"order {order.order_number}",
                pixel_id,
                token,
                event,
                settings.META_TEST_EVENT_CODE,
            )
            for pixel_id, token in pixel_token_pairs
        ]
    )

    return {"pixels_fired": len(results), "results": results}


async def fire_browser_event(
    event_name: str,
    *,
    event_id: str | None,
    value: float | None,
    currency: str,
    content_ids: list[str],
    event_source_url: str | None,
    fbp: str | None,
    fbc: str | None,
    fbclid: str | None = None,
    client_ip: str | None,
    user_agent: str | None,
) -> dict:
    """
    Send a top-of-funnel event (AddToCart, InitiateCheckout, ...) to Meta CAPI.

    No PII is available yet at this stage, so identity relies on fbp/fbc (Meta's own
    click/browser cookies) plus client IP + user agent — the same signal Meta's browser
    pixel already relies on. Share the same event_id used by the browser fbq call so
    Meta dedupes the two into a single event in Ads Manager.
    """
    settings = get_settings()
    if not settings.ENABLE_CAPI:
        return {"skipped": "capi disabled"}

    pixel_token_pairs = settings.meta_pixel_token_pairs
    if not pixel_token_pairs:
        return {"skipped": "not configured"}

    fbc_formatted = _format_fbc(fbc, fbclid)
    if not client_ip and not fbp and not fbc_formatted:
        # Still attempt CAPI — Meta may match via IP + UA alone for funnel events.
        logger.warning(
            "Meta CAPI %s: no fbp/fbc/client_ip — firing anyway with UA only",
            event_name,
        )

    user_data: dict = {
        "client_user_agent": user_agent or "Mozilla/5.0 (compatible; NafaasCAPI/1.0)",
    }
    if client_ip:
        user_data["client_ip_address"] = client_ip
    if fbp:
        user_data["fbp"] = fbp
    if fbc_formatted:
        user_data["fbc"] = fbc_formatted

    event: dict = {
        "event_name": event_name,
        "event_id": event_id or str(uuid.uuid4()),
        "event_time": int(time.time()),
        "action_source": "website",
        "event_source_url": event_source_url or settings.FRONTEND_URL,
        "user_data": user_data,
        "custom_data": {
            "value": value,
            "currency": currency or "SAR",
            "content_ids": content_ids or [],
            "content_type": "product",
        },
    }

    import asyncio

    results = await asyncio.gather(
        *[
            _fire_to_pixel(
                f"{event_name}:{event_id}",
                pixel_id,
                token,
                event,
                settings.META_TEST_EVENT_CODE,
            )
            for pixel_id, token in pixel_token_pairs
        ]
    )

    return {"pixels_fired": len(results), "results": results}
