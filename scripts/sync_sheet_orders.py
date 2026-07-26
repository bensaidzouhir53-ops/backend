"""
Push orders from the database to the Google Sheet (nasama-ksa tab).

Usage (from backend/):
  python scripts/sync_sheet_orders.py
  python scripts/sync_sheet_orders.py --all
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
from app.services import sheet_webhook

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main(include_all: bool) -> int:
    async with AsyncSessionLocal() as db:
        stats = await sheet_webhook.sync_pending_orders_to_sheet(
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
    parser = argparse.ArgumentParser(description="Sync DB orders to Google Sheet")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Send every order (Apps Script skips duplicates by order id)",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(include_all=args.all)))
