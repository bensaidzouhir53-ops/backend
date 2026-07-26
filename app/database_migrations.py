"""Idempotent schema fixes applied at startup (safe if Alembic already ran)."""

from __future__ import annotations

import logging

from sqlalchemy import text

from app.database import engine

logger = logging.getLogger(__name__)

_STARTUP_SQL = """
ALTER TABLE orders ADD COLUMN IF NOT EXISTS cod_network_sent_at TIMESTAMPTZ;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS cod_network_response JSONB;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS cod_network_reference_id VARCHAR(255);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS sheet_sent_at TIMESTAMPTZ;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS sheet_response JSONB;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS admin_notes VARCHAR(2000);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS cancel_reason VARCHAR(500);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipped_at TIMESTAMPTZ;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ;
"""


async def ensure_order_schema() -> None:
    try:
        async with engine.begin() as conn:
            for statement in _STARTUP_SQL.strip().split(";"):
                sql = statement.strip()
                if sql:
                    await conn.execute(text(sql))
        logger.info("Order schema verified (startup migration check)")
    except Exception as exc:
        logger.error("Startup schema check failed (orders may fail): %s", exc)
