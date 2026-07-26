"""Add COD Network sync fields to orders

Revision ID: 004
Revises: 003
Create Date: 2026-05-29 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("cod_network_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column(
            "cod_network_response",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "orders",
        sa.Column("cod_network_reference_id", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orders", "cod_network_reference_id")
    op.drop_column("orders", "cod_network_response")
    op.drop_column("orders", "cod_network_sent_at")
