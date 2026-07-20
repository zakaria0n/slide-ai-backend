"""Pydantic request/response schemas for the presentations API."""
from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.presentations.entities import Presentation


class CreatePresentationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    theme: str | None = Field(default=None, max_length=40)


class RenamePresentationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class PresentationResponse(BaseModel):
    id: UUID
    owner_id: UUID
    title: str
    description: str | None
    slide_count: int
    status: str
    theme: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, p: Presentation) -> "PresentationResponse":
        return cls(
            id=p.id,
            owner_id=p.owner_id,
            title=p.title,
            description=p.description,
            slide_count=p.slide_count,
            status=p.status,
            theme=p.theme,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )


class PresentationListResponse(BaseModel):
    items: list[PresentationResponse]
    total: int


class SlideResponse(BaseModel):
    """A stored slide returned in a presentation detail view."""

    index: int
    title: str
    bullets: list[str]
    notes: str | None
    layout: str

    @classmethod
    def from_content(cls, index: int, content: str) -> "SlideResponse":
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            data = {}
        return cls(
            index=index,
            title=str(data.get("title", "")),
            bullets=[str(b) for b in data.get("bullets", [])],
            notes=(data.get("notes") if isinstance(data.get("notes"), str) else None),
            layout=str(data.get("layout", "title-bullets")),
        )


__all__ = [
    "CreatePresentationRequest",
    "RenamePresentationRequest",
    "PresentationResponse",
    "PresentationListResponse",
    "SlideResponse",
]
