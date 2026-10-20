import hashlib
import logging
import re
import time
import uuid
from urllib.parse import parse_qs, urlparse

import httpx

from app.config import get_settings
from app.models.order import Order
from app.services.capi.status import is_real_secret

logger = logging.getLogger(__name__)

_SNAP_CAPI_URL = "https://tr.snapchat.com/v3/{pixel_id}/events"
_SNAP_VALIDATE_URL = "https://tr.snapchat.com/v3/{pixel_id}/events/validate"
_TIMEOUT = 10.0
_BROWSER_EVENT_MAP = {
    "AddToCart": "ADD_CART",
    "InitiateCheckout": "START_CHECKOUT",
    "ViewContent": "VIEW_CONTENT",
    "PageView": "PAGE_VIEW",
    "Purchase": "PURCHASE",
}


def _sha256(value: str) -> str:
    return hashlib.sha256(value.lower().encode()).hexdigest()


def _hash_phone_snap(phone_e164: str) -> str:
    """SHA-256 of digits-only E.164 (no +, spaces, or leading 00)."""
    digits = re.sub(r"\D", "", phone_e164 or "")
    if digits.startswith("00"):
        digits = digits[2:]
    return _sha256(digits)


def _hash_name(value: str | None) -> str | None:
    token = (value or "").strip().split()
    if not token:
        return None
    cleaned = re.sub(r"[^\w]", "", token[0], flags=re.UNICODE).lower()
    return _sha256(cleaned) if cleaned else None


def _sc_click_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        qs = parse_qs(urlparse(url).query)
    except Exception:
        return None
    for key in ("ScCid", "sccid", "sc_click_id"):
        values = qs.get(key)
        if values and values[0].strip():
            return values[0].strip()
    return None


def _click_id(order: Order | None = None, click_ids: dict | None = None, landing_page: str | None = None) -> str | None:
    ids = click_ids if click_ids is not None else (order.click_ids if order else None) or {}
    for key in ("sc_click_id", "ScCid", "sccid"):
        value = (ids.get(key) or "").strip()
        if value:
            return value
    return _sc_click_id_from_url(
        landing_page if landing_page is not None else (order.landing_page if order else None)
    )


def _cookie_scid(cookies: dict | None) -> str | None:
    cookies = cookies or {}
    for key in ("_scid", "scid", "sc_cookie1"):
        value = (cookies.get(key) or "").strip()
        if value:
            return value
    return None


def _order_contents(order: Order) -> tuple[list[dict], list[str]]:
    contents: list[dict] = []
    content_ids: list[str] = []
    for item in order.items or []:
        slug = str(item.get("product_slug") or item.get("slug") or "").strip()
        if not slug:
            continue
        qty = int(item.get("quantity") or 1)
        contents.append({"id": slug, "quantity": str(max(qty, 1))})
        content_ids.append(slug)
    if order.upsell_item:
        slug = str(order.upsell_item.get("product_slug") or "").strip()
        if slug and slug not in content_ids:
            qty = int(order.upsell_item.get("quantity") or 1)
            contents.append({"id": slug, "quantity": str(max(qty, 1))})
            content_ids.append(slug)
    return contents, content_ids


def _user_data(
    *,
    phone_e164: str | None = None,
    customer_name: str | None = None,
    client_ip: str | None = None,
    user_agent: str | None = None,
    sc_click_id: str | None = None,
    sc_cookie1: str | None = None,
) -> dict:
    user_data: dict = {}
    if phone_e164:
        user_data["ph"] = [_hash_phone_snap(phone_e164)]
    hashed_fn = _hash_name(customer_name)
    if hashed_fn:
        user_data["fn"] = [hashed_fn]
    user_data["country"] = [_sha256("sa")]
    if client_ip:
        user_data["client_ip_address"] = client_ip
    user_data["client_user_agent"] = (
        user_agent or "Mozilla/5.0 (compatible; NafaasSnapCAPI/1.0)"
    )
    if sc_click_id:
        user_data["sc_click_id"] = sc_click_id
    if sc_cookie1:
        user_data["sc_cookie1"] = sc_cookie1
    return user_data


async def _post_event(
    pixel_id: str,
    token: str,
    payload: dict,
    *,
    test_mode: bool,
    label: str,
) -> dict:
    url = (_SNAP_VALIDATE_URL if test_mode else _SNAP_CAPI_URL).format(pixel_id=pixel_id)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                url,
                params={"access_token": token},
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text[:500]}
            status = str(data.get("status") or "").upper() if isinstance(data, dict) else ""
            ok = resp.status_code < 400 and status in {"", "VALID", "SUCCESS"}
            if ok:
                logger.info(
                    "Snapchat CAPI OK for %s (status=%s test=%s): %s",
                    label,
                    resp.status_code,
                    test_mode,
                    data,
                )
            else:
                logger.error(
                    "Snapchat CAPI failed for %s (status=%s test=%s): %s",
                    label,
                    resp.status_code,
                    test_mode,
                    data,
                )
            return {
                "ok": ok,
                "status_code": resp.status_code,
                "test_mode": test_mode,
                "response": data,
            }
    except Exception as exc:
        logger.error("Snapchat CAPI error for %s: %s", label, exc)
        return {"ok": False, "error": str(exc), "test_mode": test_mode}


async def fire_purchase_event(order: Order, *, test_mode: bool = False) -> dict:
    """Send PURCHASE to Snapchat CAPI v3. Never raises."""
    settings = get_settings()
    pixel_id = (settings.SNAP_PIXEL_ID or "").strip()
    token = (settings.SNAP_ACCESS_TOKEN or "").strip()
    if not is_real_secret(pixel_id) or not is_real_secret(token):
        logger.warning(
            "Snapchat CAPI skipped: set SNAP_PIXEL_ID and SNAP_ACCESS_TOKEN "
            "(remove placeholder values like your_id)"
        )
        return {"skipped": "not configured"}

    logger.info(
        "Snapchat CAPI firing for order %s (pixel %s… test=%s)",
        order.order_number,
        pixel_id[:8],
        test_mode,
    )

    cookies = order.cookies or {}
    contents, content_ids = _order_contents(order)
    event_id = order.event_id or str(uuid.uuid4())
    custom_data: dict = {
        "value": float(order.total),
        "currency": (order.currency or "SAR").upper(),
        "order_id": str(order.id),
        "transaction_id": event_id,
        "content_ids": content_ids,
        "content_type": "product",
        "num_items": str(sum(int(c.get("quantity") or 1) for c in contents) or 1),
    }
    if contents:
        custom_data["contents"] = contents

    payload = {
        "data": [
            {
                "event_name": "PURCHASE",
                "event_time": int(time.time()),
                "event_id": event_id,
                "action_source": "WEB",
                "event_source_url": order.landing_page or settings.FRONTEND_URL,
                "user_data": _user_data(
                    phone_e164=order.phone_e164,
                    customer_name=order.customer_name,
                    client_ip=order.client_ip,
                    user_agent=order.user_agent,
                    sc_click_id=_click_id(order),
                    sc_cookie1=_cookie_scid(cookies),
                ),
                "custom_data": custom_data,
            }
        ]
    }

    return await _post_event(
        pixel_id,
        token,
        payload,
        test_mode=test_mode,
        label=f"order {order.order_number}",
    )


async def fire_browser_event(
    event_name: str,
    *,
    event_id: str | None,
    value: float | None,
    currency: str,
    content_ids: list[str],
    event_source_url: str | None,
    sc_click_id: str | None,
    scid: str | None,
    client_ip: str | None,
    user_agent: str | None,
    test_mode: bool = False,
) -> dict:
    """Forward a funnel event (ADD_CART / START_CHECKOUT) to Snap CAPI v3."""
    settings = get_settings()
    if not settings.ENABLE_CAPI:
        return {"skipped": "capi disabled"}

    pixel_id = (settings.SNAP_PIXEL_ID or "").strip()
    token = (settings.SNAP_ACCESS_TOKEN or "").strip()
    if not is_real_secret(pixel_id) or not is_real_secret(token):
        return {"skipped": "not configured"}

    snap_event = _BROWSER_EVENT_MAP.get(event_name, event_name.upper())
    ids = [cid for cid in (content_ids or []) if cid]
    custom_data: dict = {
        "currency": (currency or "SAR").upper(),
        "content_ids": ids,
        "content_type": "product",
    }
    if value is not None:
        custom_data["value"] = float(value)
    if ids:
        custom_data["contents"] = [{"id": cid, "quantity": "1"} for cid in ids]

    payload = {
        "data": [
            {
                "event_name": snap_event,
                "event_time": int(time.time()),
                "event_id": event_id or str(uuid.uuid4()),
                "action_source": "WEB",
                "event_source_url": event_source_url or settings.FRONTEND_URL,
                "user_data": _user_data(
                    client_ip=client_ip,
                    user_agent=user_agent,
                    sc_click_id=sc_click_id or _sc_click_id_from_url(event_source_url),
                    sc_cookie1=(scid or "").strip() or None,
                ),
                "custom_data": custom_data,
            }
        ]
    }

    return await _post_event(
        pixel_id,
        token,
        payload,
        test_mode=test_mode,
        label=f"{snap_event}:{event_id}",
    )
