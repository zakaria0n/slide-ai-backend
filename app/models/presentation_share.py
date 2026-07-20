"""ORM model for presentation shares."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PresentationShare(Base):
    """A share link for a presentation (public, private, or password-protected)."""

    __tablename__ = "presentation_shares"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    presentation_id: Mapped[UUID] = mapped_column(ForeignKey("presentations.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[UUID] = mapped_column(index=True)
    token: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    visibility: Mapped[str] = mapped_column(String(20), default="public")  # public, private, password
    password_hash: Mapped[str | None] = mapped_column(String(128), default=None)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    permission: Mapped[str] = mapped_column(String(20), default="view")  # view, present
    embed_allowed: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
