"""ORM model for uploaded file assets."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FileAsset(Base):
    """A file uploaded by a user and stored in Supabase Storage.

    ``owner_id`` is the Supabase user id (JWT ``sub``). The actual bytes
    live in the ``presentation-assets`` storage bucket at ``storage_path``;
    this row only records metadata. As with presentations, ``owner_id`` is
    indexed but not a foreign key — identity lives in the auth provider.
    """

    __tablename__ = "file_assets"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(index=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(512), unique=True)
    content_type: Mapped[str | None] = mapped_column(String(128), default=None)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
