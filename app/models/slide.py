"""ORM model for individual presentation slides."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Slide(Base):
    """A single slide belonging to a presentation.

    Slides are stored server-side so the viewer (F6) is deterministic and
    the deck survives reloads. ``owner_id`` is denormalized for RLS: it
    matches the parent presentation's owner and lets Supabase policies
    enforce row-level access without a join.

    ``slide_index`` orders slides within a deck (0-based). ``content`` holds
    the generated slide payload as JSON-encoded text (title, bullets, notes,
    layout). Keeping it as text avoids a second table join on every read.
    """

    __tablename__ = "slides"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    presentation_id: Mapped[UUID] = mapped_column(
        ForeignKey("presentations.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[UUID] = mapped_column(index=True)
    slide_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
