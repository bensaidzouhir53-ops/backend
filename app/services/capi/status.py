"""CAPI configuration helpers (no secrets exposed)."""

from __future__ import annotations

from app.config import Settings

_PLACEHOLDER_VALUES = frozenset(
    {
        "",
        "your_id",
        "your_token",
        "your_pixel_id",
        "changeme",
        "change-me",
        "xxx",
        "placeholder",
        "none",
        "null",
    }
)


def _clean(value: str | None) -> str:
    if not value:
        return ""
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ('"', "'"):
        cleaned = cleaned[1:-1].strip()
    return cleaned


def is_real_secret(value: str | None) -> bool:
    cleaned = _clean(value).lower()
    if not cleaned:
        return False
    if cleaned in _PLACEHOLDER_VALUES:
        return False
    if cleaned.startswith("your_"):
        return False
    return True


def provider_status(settings: Settings) -> dict:
    """Return which CAPI providers are ready (for logs and /api/tracking/capi-status)."""
    tiktok_code = _clean(settings.TIKTOK_PIXEL_CODE)
    tiktok_token = _clean(settings.TIKTOK_ACCESS_TOKEN)
    snap_id = _clean(settings.SNAP_PIXEL_ID)
    snap_token = _clean(settings.SNAP_ACCESS_TOKEN)

    def _entry(pixel: str, token: str) -> dict:
        pixel_ok = is_real_secret(pixel)
        token_ok = is_real_secret(token)
        return {
            "pixel_set": pixel_ok,
            "token_set": token_ok,
            "ready": pixel_ok and token_ok,
            "pixel_preview": pixel[:6] + "…" if len(pixel) > 6 else pixel or None,
        }

    pixel_token_pairs = settings.meta_pixel_token_pairs
    pid_clean = _clean(settings.META_PIXEL_ID)
    token_clean = _clean(settings.META_ACCESS_TOKEN)
    meta_info = {
        "pixel_preview": pid_clean[:6] + "…" if len(pid_clean) > 6 else pid_clean or None,
        "pixel_set": is_real_secret(pid_clean),
        "token_set": is_real_secret(token_clean),
        "ready": len(pixel_token_pairs) > 0,
    }

    return {
        "enable_capi": settings.ENABLE_CAPI,
        "meta": {
            "pixels_configured": len(pixel_token_pairs),
            "ready": len(pixel_token_pairs) > 0,
            "test_event_code_set": is_real_secret(settings.META_TEST_EVENT_CODE),
            "test_event_hint": (
                None
                if is_real_secret(settings.META_TEST_EVENT_CODE)
                else "Set META_TEST_EVENT_CODE from Events Manager → Test events to see CAPI in Test Events"
            ),
            "pixel": meta_info,
        },
        "tiktok": _entry(tiktok_code, tiktok_token),
        "snapchat": _entry(snap_id, snap_token),
    }
