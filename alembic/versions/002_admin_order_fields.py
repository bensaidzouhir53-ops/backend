"""Admin: add notes, cancel_reason, status timestamps to orders

Revision ID: 002
Revises: 001
Create Date: 2026-05-27 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("admin_notes", sa.String(2000), nullable=True))
    op.add_column("orders", sa.Column("cancel_reason", sa.String(500), nullable=True))
    op.add_column(
        "orders",
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_orders_created_at", "orders", ["created_at"])
    op.create_index(
        "ix_tracking_events_event_name", "tracking_events", ["event_name"]
    )
    op.create_index(
        "ix_tracking_events_created_at", "tracking_events", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_tracking_events_created_at", table_name="tracking_events")
    op.drop_index("ix_tracking_events_event_name", table_name="tracking_events")
    op.drop_index("ix_orders_created_at", table_name="orders")
    op.drop_index("ix_orders_status", table_name="orders")
    op.drop_column("orders", "delivered_at")
    op.drop_column("orders", "shipped_at")
    op.drop_column("orders", "confirmed_at")
    op.drop_column("orders", "cancel_reason")
    op.drop_column("orders", "admin_notes")
