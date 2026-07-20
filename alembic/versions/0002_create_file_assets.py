"""create file_assets table

Revision ID: 0002_create_file_assets
Revises: 0001_create_presentations
Create Date: 2026-07-20
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_create_file_assets"
down_revision: str | None = "0001_create_presentations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "file_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=512), nullable=False, unique=True),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_file_assets_owner_id", "file_assets", ["owner_id"])

    # Row Level Security scoped to the owner.
    op.execute("ALTER TABLE file_assets ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS file_assets_owner_all ON file_assets")
    op.execute(
        "CREATE POLICY file_assets_owner_all ON file_assets "
        "FOR ALL USING (owner_id = auth.uid()) "
        "WITH CHECK (owner_id = auth.uid())"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS file_assets_owner_all ON file_assets")
    op.drop_index("ix_file_assets_owner_id", table_name="file_assets")
    op.drop_table("file_assets")
