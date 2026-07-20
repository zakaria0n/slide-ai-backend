"""create slides table

Revision ID: 0003_create_slides
Revises: 0002_create_file_assets
Create Date: 2026-07-20
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_create_slides"
down_revision: str | None = "0002_create_file_assets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "slides",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "presentation_id",
            sa.Uuid(),
            sa.ForeignKey("presentations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("slide_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content", sa.Text(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_slides_presentation_id", "slides", ["presentation_id"])
    op.create_index("ix_slides_owner_id", "slides", ["owner_id"])

    # Row Level Security scoped to the owner (denormalized owner_id).
    op.execute("ALTER TABLE slides ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS slides_owner_all ON slides")
    op.execute(
        "CREATE POLICY slides_owner_all ON slides "
        "FOR ALL USING (owner_id = auth.uid()) "
        "WITH CHECK (owner_id = auth.uid())"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS slides_owner_all ON slides")
    op.drop_index("ix_slides_owner_id", table_name="slides")
    op.drop_index("ix_slides_presentation_id", table_name="slides")
    op.drop_table("slides")
