"""create presentations table

Revision ID: 0001_create_presentations
Revises:
Create Date: 2026-07-20
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_create_presentations"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "presentations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("slide_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("theme", sa.String(length=40), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_presentations_owner_id", "presentations", ["owner_id"])

    # Row Level Security: a user can only see/manage their own decks.
    op.execute("ALTER TABLE presentations ENABLE ROW LEVEL SECURITY")
    op.execute(
        "DROP POLICY IF EXISTS presentations_owner_all ON presentations"
    )
    op.execute(
        "CREATE POLICY presentations_owner_all ON presentations "
        "FOR ALL USING (owner_id = auth.uid()) "
        "WITH CHECK (owner_id = auth.uid())"
    )

    # Keep updated_at fresh on every update.
    op.execute(
        "CREATE OR REPLACE FUNCTION set_updated_at() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN NEW.updated_at = now(); RETURN NEW; END; $$"
    )
    op.execute("DROP TRIGGER IF EXISTS presentations_set_updated_at ON presentations")
    op.execute(
        "CREATE TRIGGER presentations_set_updated_at "
        "BEFORE UPDATE ON presentations "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS presentations_set_updated_at ON presentations")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
    op.execute("DROP POLICY IF EXISTS presentations_owner_all ON presentations")
    op.drop_index("ix_presentations_owner_id", table_name="presentations")
    op.drop_table("presentations")
