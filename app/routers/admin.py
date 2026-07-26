from __future__ import annotations

import csv
import io
import json
import secrets
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.order import Order
from app.models.tracking_event import TrackingEvent
from app.services import cod_network
from app.services.order_processing import should_process_order

router = APIRouter(prefix="/admin", tags=["admin"])
security = HTTPBasic()


def require_admin(credentials: HTTPBasicCredentials = Depends(security)) -> None:
    settings = get_settings()
    if not settings.ADMIN_USERNAME or not settings.ADMIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "Admin credentials are not configured"},
        )

    username_ok = secrets.compare_digest(
        credentials.username,
        settings.ADMIN_USERNAME,
    )
    password_ok = secrets.compare_digest(
        credentials.password,
        settings.ADMIN_PASSWORD,
    )
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid admin credentials"},
            headers={"WWW-Authenticate": "Basic"},
        )


def _as_float(value: Any) -> float:
    if isinstance(value, Decimal):
        return float(value)
    if value is None:
        return 0.0
    return float(value)


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _date_bounds(from_date: date | None, to_date: date | None) -> tuple[datetime, datetime]:
    today = datetime.now(tz=timezone.utc).date()
    start_date = from_date or (today - timedelta(days=29))
    end_date = to_date or today
    start = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return start, end


def _payload(event: TrackingEvent) -> dict[str, Any]:
    return event.payload or {}


def _has_click_id(event: TrackingEvent) -> bool:
    click_ids = (_payload(event).get("click_ids") or {})
    return any(str(value).strip() for value in click_ids.values())


def _order_to_summary(order: Order) -> dict[str, Any]:
    return {
        "id": str(order.id),
        "order_number": order.order_number,
        "customer_name": order.customer_name,
        "phone": order.phone_national,
        "phone_e164": order.phone_e164,
        "status": order.status,
        "subtotal": _as_float(order.subtotal),
        "upsell_total": _as_float(order.upsell_total),
        "total": _as_float(order.total),
        "currency": order.currency,
        "payment_method": order.payment_method,
        "items_count": sum(int(item.get("quantity") or 0) for item in (order.items or [])),
        "has_upsell": order.upsell_item is not None,
        "landing_page": order.landing_page,
        "utm": order.utm or {},
        "click_ids": order.click_ids or {},
        "created_at": _serialize_datetime(order.created_at),
        "has_notes": bool((order.admin_notes or "").strip()),
    }


def _order_to_detail(order: Order) -> dict[str, Any]:
    data = _order_to_summary(order)
    data.update(
        {
            "items": order.items or [],
            "upsell_item": order.upsell_item,
            "cookies": order.cookies or {},
            "event_id": order.event_id,
            "client_ip": order.client_ip,
            "user_agent": order.user_agent,
            "sheet_sent_at": _serialize_datetime(order.sheet_sent_at),
            "sheet_response": order.sheet_response,
            "cod_network_sent_at": _serialize_datetime(order.cod_network_sent_at),
            "cod_network_response": order.cod_network_response,
            "cod_network_reference_id": order.cod_network_reference_id,
            "admin_notes": order.admin_notes or "",
            "cancel_reason": order.cancel_reason or "",
            "confirmed_at": _serialize_datetime(order.confirmed_at),
            "shipped_at": _serialize_datetime(order.shipped_at),
            "delivered_at": _serialize_datetime(order.delivered_at),
            "updated_at": _serialize_datetime(order.updated_at),
        }
    )
    return data


ALLOWED_STATUSES = {
    "test",
    "pending",
    "confirmed",
    "shipped",
    "delivered",
    "cancelled",
    "returned",
}


@router.get("/metrics", dependencies=[Depends(require_admin)])
async def get_metrics(
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    start, end = _date_bounds(from_date, to_date)

    order_rows = await db.execute(
        select(Order)
        .where(Order.created_at >= start, Order.created_at < end)
        .order_by(Order.created_at.asc())
    )
    orders = list(order_rows.scalars().all())

    event_rows = await db.execute(
        select(TrackingEvent)
        .where(TrackingEvent.created_at >= start, TrackingEvent.created_at < end)
        .order_by(TrackingEvent.created_at.asc())
    )
    events = list(event_rows.scalars().all())

    # First-party funnel events (PageView, AddToCart, InitiateCheckout, etc.)
    event_counts = Counter(event.event_name for event in events)
    page_views = event_counts.get("PageView", 0)
    ad_clicks = sum(
        1 for event in events if event.event_name == "PageView" and _has_click_id(event)
    )
    view_content = event_counts.get("ViewContent", 0)
    add_to_cart = event_counts.get("AddToCart", 0)
    checkout = event_counts.get("InitiateCheckout", 0)

    revenue = sum(_as_float(order.total) for order in orders)
    order_count = len(orders)
    delivered = sum(1 for order in orders if order.status == "delivered")
    cancelled = sum(1 for order in orders if order.status in ("cancelled", "returned"))
    confirmed = sum(
        1
        for order in orders
        if order.status in ("confirmed", "shipped", "delivered")
    )
    upsell_orders = sum(1 for order in orders if order.upsell_item is not None)
    realised_revenue = sum(
        _as_float(order.total) for order in orders if order.status == "delivered"
    )

    daily: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "date": "",
            "clicks": 0,
            "ad_clicks": 0,
            "view_content": 0,
            "add_to_cart": 0,
            "checkout": 0,
            "orders": 0,
            "revenue": 0.0,
        }
    )
    hourly: dict[int, dict[str, Any]] = {
        hour: {"hour": hour, "clicks": 0, "orders": 0, "revenue": 0.0}
        for hour in range(24)
    }
    for event in events:
        day = event.created_at.date().isoformat()
        daily[day]["date"] = day
        hour = event.created_at.hour
        if event.event_name == "PageView":
            daily[day]["clicks"] += 1
            hourly[hour]["clicks"] += 1
            if _has_click_id(event):
                daily[day]["ad_clicks"] += 1
        elif event.event_name == "ViewContent":
            daily[day]["view_content"] += 1
        elif event.event_name == "AddToCart":
            daily[day]["add_to_cart"] += 1
        elif event.event_name == "InitiateCheckout":
            daily[day]["checkout"] += 1

    for order in orders:
        day = order.created_at.date().isoformat()
        daily[day]["date"] = day
        daily[day]["orders"] += 1
        daily[day]["revenue"] += _as_float(order.total)
        hour = order.created_at.hour
        hourly[hour]["orders"] += 1
        hourly[hour]["revenue"] += _as_float(order.total)

    source_data: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"source": "", "orders": 0, "revenue": 0.0, "clicks": 0}
    )
    for event in events:
        if event.event_name != "PageView":
            continue
        utm = _payload(event).get("utm") or {}
        source = (utm.get("source") or "direct").strip() or "direct"
        source_data[source]["source"] = source
        source_data[source]["clicks"] += 1
    for order in orders:
        source = ((order.utm or {}).get("source") or "direct").strip() or "direct"
        source_data[source]["source"] = source
        source_data[source]["orders"] += 1
        source_data[source]["revenue"] += _as_float(order.total)

    campaign_data: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"campaign": "", "orders": 0, "revenue": 0.0, "clicks": 0}
    )
    for event in events:
        if event.event_name != "PageView":
            continue
        utm = _payload(event).get("utm") or {}
        campaign = (utm.get("campaign") or "").strip() or "(none)"
        campaign_data[campaign]["campaign"] = campaign
        campaign_data[campaign]["clicks"] += 1
    for order in orders:
        campaign = ((order.utm or {}).get("campaign") or "").strip() or "(none)"
        campaign_data[campaign]["campaign"] = campaign
        campaign_data[campaign]["orders"] += 1
        campaign_data[campaign]["revenue"] += _as_float(order.total)

    product_data: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"product_slug": "", "quantity": 0, "orders": 0, "revenue": 0.0}
    )
    for order in orders:
        seen_slugs: set[str] = set()
        for item in order.items or []:
            slug = str(item.get("product_slug") or "unknown")
            product_data[slug]["product_slug"] = slug
            product_data[slug]["quantity"] += int(item.get("quantity") or 0)
            seen_slugs.add(slug)
        if order.upsell_item:
            slug = str(order.upsell_item.get("product_slug") or "upsell")
            product_data[slug]["product_slug"] = slug
            product_data[slug]["quantity"] += int(order.upsell_item.get("quantity") or 1)
            seen_slugs.add(slug)
        order_share = _as_float(order.total) / max(len(seen_slugs), 1)
        for slug in seen_slugs:
            product_data[slug]["orders"] += 1
            product_data[slug]["revenue"] += order_share

    status_counts = Counter(order.status for order in orders)

    return {
        "range": {
            "from": start.date().isoformat(),
            "to": (end - timedelta(days=1)).date().isoformat(),
        },
        "summary": {
            "revenue": revenue,
            "realised_revenue": realised_revenue,
            "orders": order_count,
            "delivered": delivered,
            "confirmed": confirmed,
            "cancelled": cancelled,
            "clicks": page_views,
            "ad_clicks": ad_clicks,
            "view_content": view_content,
            "add_to_cart": add_to_cart,
            "checkout": checkout,
            "conversion_rate": (order_count / page_views * 100) if page_views else 0,
            "checkout_conversion_rate": (order_count / checkout * 100) if checkout else 0,
            "delivery_rate": (delivered / order_count * 100) if order_count else 0,
            "cancel_rate": (cancelled / order_count * 100) if order_count else 0,
            "average_order_value": (revenue / order_count) if order_count else 0,
            "upsell_rate": (upsell_orders / order_count * 100) if order_count else 0,
        },
        "funnel": [
            {"name": "Clicks", "value": page_views},
            {"name": "View content", "value": view_content},
            {"name": "Add to cart", "value": add_to_cart},
            {"name": "Checkout", "value": checkout},
            {"name": "Orders", "value": order_count},
            {"name": "Delivered", "value": delivered},
        ],
        "daily": sorted(daily.values(), key=lambda item: item["date"]),
        "hourly": list(hourly.values()),
        "sources": sorted(
            source_data.values(),
            key=lambda item: (item["revenue"], item["orders"], item["clicks"]),
            reverse=True,
        )[:10],
        "campaigns": sorted(
            campaign_data.values(),
            key=lambda item: (item["revenue"], item["orders"], item["clicks"]),
            reverse=True,
        )[:10],
        "top_products": sorted(
            product_data.values(),
            key=lambda item: (item["revenue"], item["quantity"]),
            reverse=True,
        )[:10],
        "status_counts": dict(status_counts),
        "recent_orders": [_order_to_summary(order) for order in reversed(orders[-8:])],
    }


def _build_order_filters(
    from_date: date | None,
    to_date: date | None,
    status_filter: str | None,
    search: str | None,
) -> list[Any]:
    start, end = _date_bounds(from_date, to_date)
    filters: list[Any] = [Order.created_at >= start, Order.created_at < end]
    if status_filter:
        filters.append(Order.status == status_filter)
    if search:
        like = f"%{search.strip()}%"
        filters.append(
            or_(
                Order.order_number.ilike(like),
                Order.customer_name.ilike(like),
                Order.phone_national.ilike(like),
                Order.phone_e164.ilike(like),
            )
        )
    return filters


@router.get("/orders", dependencies=[Depends(require_admin)])
async def list_orders(
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    status_filter: str | None = Query(None, alias="status"),
    search: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    filters = _build_order_filters(from_date, to_date, status_filter, search)

    total = await db.scalar(select(func.count()).select_from(Order).where(*filters))
    rows = await db.execute(
        select(Order)
        .where(*filters)
        .order_by(Order.created_at.desc())
        .offset(offset)
        .limit(limit + 1)
    )
    orders = list(rows.scalars().all())
    has_more = len(orders) > limit
    orders = orders[:limit]

    return {
        "orders": [_order_to_summary(order) for order in orders],
        "has_more": has_more,
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
    }


@router.get("/orders.csv", dependencies=[Depends(require_admin)])
async def export_orders_csv(
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    status_filter: str | None = Query(None, alias="status"),
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> Response:
    filters = _build_order_filters(from_date, to_date, status_filter, search)
    rows = await db.execute(
        select(Order).where(*filters).order_by(Order.created_at.desc())
    )
    orders = list(rows.scalars().all())

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "order_number",
            "created_at",
            "status",
            "customer_name",
            "phone",
            "phone_e164",
            "items",
            "upsell",
            "subtotal",
            "upsell_total",
            "total",
            "currency",
            "payment_method",
            "utm_source",
            "utm_campaign",
            "landing_page",
            "client_ip",
            "admin_notes",
            "cancel_reason",
        ]
    )
    for order in orders:
        items_text = "; ".join(
            f"{item.get('product_slug')} x{item.get('quantity')}"
            for item in (order.items or [])
        )
        upsell = order.upsell_item or {}
        upsell_text = (
            f"{upsell.get('product_slug')} x{upsell.get('quantity')}"
            if upsell
            else ""
        )
        utm = order.utm or {}
        writer.writerow(
            [
                order.order_number,
                order.created_at.isoformat() if order.created_at else "",
                order.status,
                order.customer_name,
                order.phone_national,
                order.phone_e164,
                items_text,
                upsell_text,
                _as_float(order.subtotal),
                _as_float(order.upsell_total),
                _as_float(order.total),
                order.currency,
                order.payment_method,
                utm.get("source") or "",
                utm.get("campaign") or "",
                order.landing_page or "",
                order.client_ip or "",
                (order.admin_notes or "").replace("\n", " ").strip(),
                order.cancel_reason or "",
            ]
        )

    filename = f"nasama-orders-{datetime.now(tz=timezone.utc).date().isoformat()}.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/orders/{order_id}", dependencies=[Depends(require_admin)])
async def get_order(order_id: UUID, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Order not found"},
        )
    return _order_to_detail(order)


async def _read_json_object_body(request: Request) -> dict[str, Any]:
    """Parse JSON object from request body (works without Content-Type header)."""
    raw_bytes = await request.body()
    if not raw_bytes:
        return {}

    try:
        parsed = json.loads(raw_bytes.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Invalid JSON body"},
        ) from exc

    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "JSON body must be an object"},
        )

    return parsed


@router.patch("/orders/{order_id}", dependencies=[Depends(require_admin)])
async def update_order(
    order_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    body = await _read_json_object_body(request)
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Order not found"},
        )

    now = datetime.now(tz=timezone.utc)
    changed = False

    if "status" in body and body["status"] is not None:
        new_status = str(body["status"]).strip()
        if new_status not in ALLOWED_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"message": "Invalid order status"},
            )
        if order.status != new_status:
            order.status = new_status
            if new_status == "confirmed" and not order.confirmed_at:
                order.confirmed_at = now
            elif new_status == "shipped" and not order.shipped_at:
                order.shipped_at = now
            elif new_status == "delivered" and not order.delivered_at:
                order.delivered_at = now
            changed = True

    if "admin_notes" in body:
        order.admin_notes = (str(body.get("admin_notes") or "")).strip() or None
        changed = True

    if "cancel_reason" in body:
        order.cancel_reason = (str(body.get("cancel_reason") or "")).strip() or None
        changed = True

    if changed:
        order.updated_at = now
        await db.commit()
        await db.refresh(order)

    return _order_to_detail(order)


@router.post(
    "/orders/{order_id}/sync-cod-network",
    dependencies=[Depends(require_admin)],
)
async def sync_order_cod_network(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Manually push or retry one order to COD Network."""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Order not found"},
        )

    if not should_process_order(order):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Test orders are not processed until PROCESS_TEST_ORDERS=true",
            },
        )

    ok = await cod_network.sync_order_to_cod_network(db, order)
    await db.refresh(order)
    return {
        "ok": ok,
        "order_id": str(order.id),
        "order_number": order.order_number,
        "cod_network_sent_at": _serialize_datetime(order.cod_network_sent_at),
        "cod_network_reference_id": order.cod_network_reference_id,
        "cod_network_response": order.cod_network_response,
    }
