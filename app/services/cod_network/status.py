"""COD Network configuration helpers (no API token exposed)."""

from __future__ import annotations

import logging

import httpx

from app.config import Settings
from app.services.capi.status import is_real_secret

logger = logging.getLogger(__name__)

_COD_API_BASE = "https://api.cod.network"
_PROBE_TIMEOUT = 15.0


def _mask_token(token: str) -> str:
    if len(token) <= 12:
        return "…"
    return f"{token[:8]}…{token[-4:]}"


def cod_network_status(settings: Settings) -> dict:
    """Return COD Network readiness (for logs and /api/tracking/cod-network-status)."""
    token = (settings.COD_NETWORK_API_TOKEN or "").strip()
    token_ok = is_real_secret(token)
    default_sku = settings.cod_network_default_sku
    product_map = settings.cod_network_product_map_parsed
    aliases = settings.cod_network_sku_aliases_parsed

    resolved_default = None
    if default_sku:
        resolved_default = settings.resolve_cod_network_sku(default_sku)

    return {
        "enable_cod_network": settings.ENABLE_COD_NETWORK,
        "token_set": token_ok,
        "ready": settings.ENABLE_COD_NETWORK and token_ok and bool(default_sku or product_map),
        "mode": settings.COD_NETWORK_MODE,
        "api_version": settings.COD_NETWORK_API_VERSION,
        "default_sku": default_sku,
        "default_sku_resolved": resolved_default,
        "default_product_name": settings.cod_network_default_name,
        "product_map_slugs": list(product_map.keys()),
        "sku_aliases": aliases,
        "token_preview": _mask_token(token) if token_ok else None,
        "hint": (
            None
            if settings.ENABLE_COD_NETWORK and token_ok and (default_sku or product_map)
            else "Set ENABLE_COD_NETWORK=true, COD_NETWORK_API_TOKEN, and COD_NETWORK_SKU (or COD_NETWORK_PRODUCT_MAP) in Easypanel, then restart backend."
        ),
    }


async def probe_cod_network_token(settings: Settings) -> dict:
    """
    Live check against COD Network (GET /seller/products).
    Used at startup so a revoked/expired token shows clearly in logs.
    """
    if not settings.ENABLE_COD_NETWORK:
        return {"skipped": True, "reason": "disabled"}
    token = (settings.COD_NETWORK_API_TOKEN or "").strip()
    if not is_real_secret(token):
        return {"skipped": True, "reason": "token_not_set"}

    version = (settings.COD_NETWORK_API_VERSION or "v2").strip().strip("/")
    url = f"{_COD_API_BASE}/api/{version}/seller/products"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            response = await client.get(url, params={"per_page": 1, "page": 1})
    except httpx.HTTPError as exc:
        logger.error("COD Network token probe failed (network): %s", exc)
        return {"ok": False, "error": "network", "detail": str(exc)}

    if response.status_code == 401:
        logger.error(
            "COD Network API token is REJECTED (401 Unauthenticated). "
            "Paste a fresh token from COD Network → My Profile → API Developer "
            "into Easypanel COD_NETWORK_API_TOKEN and restart the backend."
        )
        return {"ok": False, "http_status": 401, "authenticated": False}

    if response.status_code >= 400:
        logger.warning(
            "COD Network token probe unexpected HTTP %s: %s",
            response.status_code,
            response.text[:300],
        )
        return {
            "ok": False,
            "http_status": response.status_code,
            "authenticated": None,
        }

    logger.info("COD Network API token verified (HTTP %s)", response.status_code)
    return {"ok": True, "http_status": response.status_code, "authenticated": True}
