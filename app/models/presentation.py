"""ORM model for user presentations."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Presentation(Base):
    """A presentation owned by a user.

    Presentation *content* (slides, layout, assets) is managed by later
    features; this table captures the owner-scoped metadata needed for
    listing, renaming, duplicating, and deleting decks.

    ``owner_id`` is the Supabase user id (JWT ``sub``). It is indexed but
    intentionally *not* a foreign key: identity lives in the external auth
    provider, not in this database.
    """

    __tablename__ = "presentations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, default=None)

    # Generation metadata (populated by later features).
    slide_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status: Mapped[str] = mapped_column(
        String(20), default="draft", server_default="draft"
    )
    theme: Mapped[str | None] = mapped_column(String(40), default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
    )
