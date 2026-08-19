import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.tracking_event import TrackingEvent
from app.schemas.tracking import (
    PublicTrackingConfigResponse,
    TrackingEventRequest,
    TrackingEventResponse,
)
from app.services.capi.status import is_real_secret, provider_status
from app.services.cod_network.status import cod_network_status

logger = logging.getLogger(__name__)
router = APIRouter(tags=["tracking"])


def _get_client_ip(request: Request, override: str | None) -> str | None:
    if override:
        return override
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()
    if request.client:
        return request.client.host
    return None


@router.get("/tracking/config", response_model=PublicTrackingConfigResponse)
async def get_tracking_config() -> PublicTrackingConfigResponse:
    """
    Public pixel IDs for the storefront. Configure once in backend env (Easypanel);
    the Next.js app fetches this at runtime so NEXT_PUBLIC_* rebuilds are not required.
    """
    settings = get_settings()
    meta_ids = settings.meta_pixel_ids
    has_any_pixel = bool(
        meta_ids
        or settings.TIKTOK_PIXEL_CODE
        or settings.SNAP_PIXEL_ID
    )
    enabled = settings.ENABLE_WEB_PIXELS and has_any_pixel
    return PublicTrackingConfigResponse(
        enabled=enabled,
        meta_pixel_id=meta_ids[0] if meta_ids else None,
        meta_pixel_ids=meta_ids,
        tiktok_pixel_id=settings.TIKTOK_PIXEL_CODE or None,
        snap_pixel_id=(
            settings.SNAP_PIXEL_ID
            if is_real_secret(settings.SNAP_PIXEL_ID)
            else None
        ),
        capi_enabled=settings.ENABLE_CAPI and len(settings.meta_pixel_token_pairs) > 0,
    )


@router.get("/tracking/capi-status")
async def get_capi_status() -> dict:
    """Debug endpoint: verify Easypanel env vars are loaded (no tokens returned)."""
    settings = get_settings()
    return provider_status(settings)


@router.post("/tracking/meta-test")
async def fire_meta_test_event(request: Request) -> dict:
    """
    Fire one test Purchase to Meta CAPI using env pixel + token.
    Optional JSON body: {"test_event_code": "TEST12345"} — or set META_TEST_EVENT_CODE.
    Use this to verify the token shows in Events Manager → Test events.
    """
    import time
    import hashlib

    import httpx

    settings = get_settings()
    pairs = settings.meta_pixel_token_pairs
    if not pairs:
        return {
            "ok": False,
            "error": "META_PIXEL_ID or META_ACCESS_TOKEN missing/invalid in backend env",
            "status": provider_status(settings),
        }

    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        body = {}

    test_code = (
        (body.get("test_event_code") if isinstance(body, dict) else None)
        or settings.META_TEST_EVENT_CODE
    )
    if isinstance(test_code, str):
        test_code = test_code.strip() or None

    if settings.APP_ENV == "production" and not test_code:
        return {
            "ok": False,
            "error": "Blocked in production — set META_TEST_EVENT_CODE or pass test_event_code",
            "status": provider_status(settings),
        }

    pixel_id, token = pairs[0]
    phone_hash = hashlib.sha256(b"966500000000").hexdigest()
    event = {
        "event_name": "Purchase",
        "event_time": int(time.time()),
        "event_id": str(uuid.uuid4()),
        "action_source": "website",
        "event_source_url": settings.FRONTEND_URL or "https://nafaas.shop/",
        "user_data": {
            "ph": [phone_hash],
            "client_ip_address": _get_client_ip(request, None) or "8.8.8.8",
            "client_user_agent": request.headers.get("User-Agent")
            or "Mozilla/5.0 (compatible; NafaasMetaTest/1.0)",
        },
        "custom_data": {
            "value": 1.0,
            "currency": "SAR",
            "content_ids": ["meta-test"],
            "content_type": "product",
            "order_id": f"meta-test-{int(time.time())}",
        },
    }
    payload: dict = {"data": [event], "access_token": token}
    if test_code and is_real_secret(test_code):
        payload["test_event_code"] = test_code

    url = f"https://graph.facebook.com/v22.0/{pixel_id}/events"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
            data = resp.json()
    except Exception as exc:
        logger.error("Meta test event failed: %s", exc)
        return {"ok": False, "error": str(exc), "pixel_preview": pixel_id[:6] + "…"}

    ok = resp.status_code < 400 and not (isinstance(data, dict) and data.get("error"))
    logger.info(
        "Meta test event pixel=%s status=%s test_code=%s response=%s",
        pixel_id[:6],
        resp.status_code,
        bool(test_code),
        data,
    )
    return {
        "ok": ok,
        "status_code": resp.status_code,
        "pixel_preview": pixel_id[:6] + "…",
        "test_event_code_used": bool(test_code and is_real_secret(test_code)),
        "hint": (
            None
            if test_code
            else "Pass test_event_code or set META_TEST_EVENT_CODE to see this in Test Events tab"
        ),
        "response": data,
    }


@router.get("/tracking/cod-network-status")
async def get_cod_network_status() -> dict:
    """Debug endpoint: verify COD Network env is loaded (no API token returned)."""
    settings = get_settings()
    return cod_network_status(settings)


@router.post(
    "/tracking/events",
    response_model=TrackingEventResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def capture_tracking_event(
    body: TrackingEventRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TrackingEventResponse:
    """
    Store first-party storefront analytics for the admin dashboard.

    GeoIP is not enforced here so funnel metrics (clicks, add-to-cart, checkout)
    reflect real visitor activity. KSA enforcement remains on POST /api/orders only.
    """
    client_ip = _get_client_ip(request, body.client_ip)

    event = TrackingEvent(
        id=uuid.uuid4(),
        event_name=body.event_name.strip(),
        event_id=body.event_id,
        payload={
            "visitor_id": body.visitor_id,
            "session_id": body.session_id,
            "page_url": body.page_url,
            "referrer": body.referrer,
            "user_agent": body.user_agent or request.headers.get("User-Agent"),
            "value": body.value,
            "currency": body.currency,
            "content_ids": body.content_ids,
            "metadata": body.metadata,
            "utm": body.utm,
            "click_ids": body.click_ids,
            "cookies": body.cookies,
            "client_ip": client_ip,
        },
        created_at=datetime.now(tz=timezone.utc),
    )
    db.add(event)
    await db.commit()

    return TrackingEventResponse(stored=True)
