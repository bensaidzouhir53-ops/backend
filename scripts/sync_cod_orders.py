"""
Push orders from the database to COD Network.

Usage (from backend/):
  python scripts/sync_cod_orders.py
  python scripts/sync_cod_orders.py --all
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import AsyncSessionLocal
from app.services import cod_network

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main(include_all: bool) -> int:
    async with AsyncSessionLocal() as db:
        stats = await cod_network.sync_pending_orders_to_cod_network(
            db,
            include_all=include_all,
        )

    logger.info(
        "Done. attempted=%s succeeded=%s failed=%s skipped=%s",
        stats["attempted"],
        stats["succeeded"],
        stats["failed"],
        stats["skipped"],
    )
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync orders to COD Network")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Retry every order, not only failed/missing syncs",
    )
    raise SystemExit(asyncio.run(main(parser.parse_args().all)))
