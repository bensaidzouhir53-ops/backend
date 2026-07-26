from datetime import datetime, timezone
from sqlalchemy import select, func, extract
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.order import Order


async def generate_order_number(db: AsyncSession) -> str:
    """Generate sequential order id: NA + YYYYMMDD + 4-digit sequence."""
    now = datetime.now(tz=timezone.utc)
    year = now.year
    month = now.month
    day = now.day
    date_prefix = f"{year}{month:02d}{day:02d}"

    result = await db.execute(
        select(func.count(Order.id)).where(
            extract("year", Order.created_at) == year,
            extract("month", Order.created_at) == month,
            extract("day", Order.created_at) == day,
        )
    )
    count: int = result.scalar_one()
    sequence = count + 1
    return f"NA{date_prefix}{sequence:04d}"
