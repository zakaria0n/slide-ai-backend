"""SQLAlchemy declarative base shared by all ORM models."""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all database models."""

    # Provides a stable, human-readable default repr for every model.
    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        cls = self.__class__.__name__
        pk = getattr(self, "id", None)
        return f"<{cls} id={pk!r}>"
