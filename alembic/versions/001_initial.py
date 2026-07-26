"""Initial schema: orders and tracking_events

Revision ID: 001
Revises:
Create Date: 2026-05-25 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_number", sa.String(32), nullable=False),
        sa.Column("customer_name", sa.String(255), nullable=False),
        sa.Column("phone_e164", sa.String(20), nullable=False),
        sa.Column("phone_national", sa.String(15), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("subtotal", sa.Numeric(10, 2), nullable=False),
        sa.Column("upsell_total", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("total", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="SAR"),
        sa.Column("payment_method", sa.String(50), nullable=False, server_default="COD"),
        sa.Column("items", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("upsell_item", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("landing_page", sa.String(500), nullable=True),
        sa.Column("utm", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("click_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("cookies", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("event_id", sa.String(255), nullable=True),
        sa.Column("client_ip", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(1000), nullable=True),
        sa.Column("sheet_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sheet_response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_unique_constraint("uq_orders_order_number", "orders", ["order_number"])
    op.create_index("ix_orders_order_number", "orders", ["order_number"])
    op.create_index("ix_orders_event_id", "orders", ["event_id"])

    op.create_table(
        "tracking_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_name", sa.String(100), nullable=False),
        sa.Column("event_id", sa.String(255), nullable=True),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "provider_results",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_tracking_events_event_id", "tracking_events", ["event_id"])
    op.create_index("ix_tracking_events_order_id", "tracking_events", ["order_id"])


def downgrade() -> None:
    op.drop_table("tracking_events")
    op.drop_index("ix_orders_event_id", table_name="orders")
    op.drop_index("ix_orders_order_number", table_name="orders")
    op.drop_table("orders")
