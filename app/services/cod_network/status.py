"""COD Network configuration helpers (no API token exposed)."""

from __future__ import annotations

from app.config import Settings
from app.services.capi.status import is_real_secret


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
