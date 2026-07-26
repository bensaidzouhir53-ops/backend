"""Normalize PostgreSQL URLs for SQLAlchemy asyncpg (Railway, Docker, etc.)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


def normalize_database_url(raw: str) -> tuple[str, bool]:
    """
    Convert postgres:// / postgresql:// to postgresql+asyncpg://.
    Returns (sqlalchemy_url, ssl_disabled).
    """
    url = raw.strip()
    if not url:
        raise ValueError("DATABASE_URL is empty")

    ssl_disabled = False
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    sslmode = (query.get("sslmode") or query.get("ssl") or [""])[0].lower()
    if sslmode in {"disable", "false", "off", "0"}:
        ssl_disabled = True

    scheme = parsed.scheme
    if scheme in {"postgres", "postgresql"}:
        scheme = "postgresql+asyncpg"
    elif scheme == "postgresql+asyncpg":
        pass
    else:
        raise ValueError(f"Unsupported DATABASE_URL scheme: {parsed.scheme}")

    clean_query = {
        k: v
        for k, v in query.items()
        if k.lower() not in {"sslmode", "ssl"}
    }
    new_query = urlencode(clean_query, doseq=True)
    cleaned = urlunparse(
        (scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment)
    )
    return cleaned, ssl_disabled
