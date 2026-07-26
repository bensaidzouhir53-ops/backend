import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Numeric, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_e164: Mapped[str] = mapped_column(String(20), nullable=False)
    phone_national: Mapped[str] = mapped_column(String(15), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    subtotal: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    upsell_total: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    total: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="SAR")
    payment_method: Mapped[str] = mapped_column(String(50), nullable=False, default="COD")
    items: Mapped[dict] = mapped_column(JSONB, nullable=False)
    upsell_item: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    landing_page: Mapped[str | None] = mapped_column(String(500), nullable=True)
    utm: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    click_ids: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    cookies: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    event_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    client_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    sheet_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sheet_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    cod_network_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cod_network_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    cod_network_reference_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    admin_notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    shipped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
