"""Presentation domain entity.

A plain dataclass (no ORM coupling) describing the presentation concepts
the application cares about. The repository maps the ORM row to this
entity before it reaches the service/API layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class Presentation:
    """An owned presentation (metadata only at this stage)."""

    id: UUID
    owner_id: UUID
    title: str
    description: str | None
    slide_count: int
    status: str
    theme: str | None
    created_at: datetime
    updated_at: datetime
