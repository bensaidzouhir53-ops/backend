"""Add redirect_links table for ad slug redirects

Revision ID: 003
Revises: 002
Create Date: 2026-05-29 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "redirect_links",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("target_path", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_redirect_links_slug", "redirect_links", ["slug"])


def downgrade() -> None:
    op.drop_index("ix_redirect_links_slug", table_name="redirect_links")
    op.drop_table("redirect_links")
