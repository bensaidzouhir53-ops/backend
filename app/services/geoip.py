"""MaxMind GeoIP2 — KSA-only orders (country check only, no VPN/proxy blocking)."""

from __future__ import annotations

import base64
import ipaddress
import logging
from typing import Any

import httpx
from fastapi import HTTPException, status

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

MSG_NOT_KSA = (
    "عذراً، الطلبات متاحة داخل المملكة العربية السعودية فقط."
)
MSG_IP_UNKNOWN = (
    "تعذر التحقق من موقع الاتصال. يرجى المحاولة مرة أخرى."
)


def _is_private_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip.strip())
        return (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
        )
    except ValueError:
        return True


def _credentials_configured() -> bool:
    return bool(settings.MAXMIND_ACCOUNT_ID and settings.MAXMIND_LICENSE_KEY)


def _auth_header() -> str:
    raw = f"{settings.MAXMIND_ACCOUNT_ID}:{settings.MAXMIND_LICENSE_KEY}".encode()
    return f"Basic {base64.b64encode(raw).decode('ascii')}"


def _insights_url(ip: str) -> str:
    host = settings.MAXMIND_API_HOST.strip().rstrip("/")
    return f"https://{host}/geoip/v2.1/insights/{ip}"


async def lookup_ip(ip: str) -> dict[str, Any]:
    """Call MaxMind GeoIP2 Insights for an IP address."""
    if not _credentials_configured():
        raise RuntimeError("MaxMind credentials are not configured")

    url = _insights_url(ip)
    headers = {
        "Authorization": _auth_header(),
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(timeout=8.0) as client:
        response = await client.get(url, headers=headers)

    if response.status_code == 404:
        logger.warning("MaxMind has no record for IP %s — allowing order (soft-fail)", ip)
        return {"country": {"iso_code": settings.GEOIP_ALLOWED_COUNTRY or "SA"}}

    if response.status_code in (401, 403):
        logger.error("MaxMind authentication failed (%s)", response.status_code)
        raise RuntimeError("MaxMind authentication failed")

    if response.status_code >= 400:
        logger.error(
            "MaxMind API error %s for IP %s: %s",
            response.status_code,
            ip,
            response.text[:200],
        )
        raise RuntimeError(f"MaxMind API error {response.status_code}")

    return response.json()


def evaluate_geoip(data: dict[str, Any]) -> None:
    """Raise HTTPException only when the IP country is outside KSA."""
    country_code = (data.get("country") or {}).get("iso_code") or ""
    allowed = (settings.GEOIP_ALLOWED_COUNTRY or "SA").upper()

    if not country_code:
        logger.warning("GeoIP country unknown — allowing order (soft-fail)")
        return

    if country_code != allowed:
        logger.info(
            "GeoIP blocked: country=%s (allowed=%s)",
            country_code,
            allowed,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"field": "geoip", "message": MSG_NOT_KSA},
        )


async def enforce_order_geoip(client_ip: str | None) -> None:
    """
    Enforce KSA-only orders using MaxMind country lookup.
    VPN/proxy/datacenter IPs are allowed if the country is SA.
    Skipped when ENABLE_GEOIP_CHECK=false.
    """
    if not settings.ENABLE_GEOIP_CHECK:
        return

    if not client_ip or not client_ip.strip():
        if settings.APP_ENV == "production":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"field": "geoip", "message": MSG_IP_UNKNOWN},
            )
        logger.warning("GeoIP skipped: no client IP in non-production")
        return

    ip = client_ip.strip()

    if _is_private_ip(ip):
        if settings.APP_ENV == "production":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"field": "geoip", "message": MSG_IP_UNKNOWN},
            )
        logger.info("GeoIP skipped for private/local IP %s (non-production)", ip)
        return

    if not _credentials_configured():
        logger.warning(
            "GeoIP check enabled but MaxMind credentials missing — skipping verification"
        )
        return

    try:
        data = await lookup_ip(ip)
    except httpx.TimeoutException:
        logger.error(
            "MaxMind API timeout for IP %s — allowing order (GeoIP soft-fail)",
            ip,
        )
        return
    except RuntimeError as exc:
        logger.error(
            "MaxMind lookup failed: %s — allowing order (GeoIP soft-fail)",
            exc,
        )
        return

    evaluate_geoip(data)
