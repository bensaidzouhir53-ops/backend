"""Normalize redirect target paths after domain migration

Revision ID: 005
Revises: 004
Create Date: 2026-06-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Convert stored absolute URLs (e.g. https://nasama.shop/products/...) to site paths.
    op.execute(
        """
        UPDATE redirect_links
        SET target_path = COALESCE(
            NULLIF(regexp_replace(target_path, '^https?://[^/]*', '', 'i'), ''),
            '/'
        )
        WHERE target_path ~* '^https?://'
        """
    )


def downgrade() -> None:
    pass
