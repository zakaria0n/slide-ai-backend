"""ORM model for presentation version snapshots."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PresentationVersion(Base):
    """A point-in-time snapshot of a presentation's spec."""

    __tablename__ = "presentation_versions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    presentation_id: Mapped[UUID] = mapped_column(ForeignKey("presentations.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[UUID] = mapped_column(index=True)
    spec: Mapped[dict] = mapped_column(JSON)
    version_note: Mapped[str | None] = mapped_column(String(200), default=None)
    slide_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
