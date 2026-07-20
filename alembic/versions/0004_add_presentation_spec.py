"""add presentations.spec column

Revision ID: 0004_add_presentation_spec
Revises: 0003_create_slides
Create Date: 2026-07-20
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_add_presentation_spec"
down_revision: str | None = "0003_create_slides"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLAlchemy's generic JSON maps to JSONB on Postgres and TEXT on SQLite,
    # matching the model definition so the same migration works everywhere.
    op.add_column(
        "presentations",
        sa.Column("spec", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("presentations", "spec")
