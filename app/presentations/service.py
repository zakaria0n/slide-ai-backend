"""Presentation business logic.

Access-scoped CRUD: a caller can operate on a presentation when they own
it or belong to a workspace that contains it. Read access is granted to
any member (including ``viewer``); write operations (rename) require an
``owner``/``admin``/``editor`` role. Duplication creates a new owned copy
with a fresh id and a derived title.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from supabase import AsyncClient

import app.db as db
from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.presentations.entities import Presentation

_TITLE_MAX = 200
_TITLE_MIN = 1
_DEFAULT_DUPLICATE_PREFIX = "Copy of "


def _to_entity(row: dict) -> Presentation:
    return Presentation(
        id=UUID(row["id"]),
        owner_id=UUID(row["owner_id"]),
        title=row["title"],
        description=row.get("description"),
        slide_count=row.get("slide_count", 0),
        status=row.get("status", "draft"),
        theme=row.get("theme"),
        created_at=_parse_dt(row["created_at"]),
        updated_at=_parse_dt(row["updated_at"]),
    )


def _parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _validate_title(title: str) -> str:
    stripped = title.strip()
    if len(stripped) < _TITLE_MIN:
        raise ValidationError("Title must not be empty")
    if len(stripped) > _TITLE_MAX:
        raise ValidationError(f"Title must be at most {_TITLE_MAX} characters")
    return stripped


class PresentationService:
    """Access-scoped presentation operations."""

    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def list_for_owner(
        self, owner_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> Sequence[Presentation]:
        rows = await db.list_presentations(
            self._client, owner_id, limit=max(1, min(limit, 200)), offset=max(0, offset)
        )
        return [_to_entity(r) for r in rows]

    async def get(self, presentation_id: UUID, user_id: UUID) -> Presentation:
        return await self._require_access(presentation_id, user_id)

    async def create(
        self,
        owner_id: UUID,
        *,
        title: str,
        description: str | None = None,
        theme: str | None = None,
    ) -> Presentation:
        clean_title = _validate_title(title)
        row = await db.create_presentation(
            self._client,
            owner_id=str(owner_id),
            title=clean_title,
            description=description.strip() if description else None,
            theme=theme,
            status="draft",
            slide_count=0,
        )
        return _to_entity(row)

    async def rename(
        self, presentation_id: UUID, user_id: UUID, *, title: str
    ) -> Presentation:
        await self._require_access(presentation_id, user_id, write=True)
        row = await db.update_presentation(self._client, presentation_id, title=_validate_title(title))
        if row is None:
            raise NotFoundError("Presentation not found")
        return _to_entity(row)

    async def delete(self, presentation_id: UUID, user_id: UUID) -> None:
        await self._require_access(presentation_id, user_id, write=True)
        await db.delete_presentation(self._client, presentation_id)

    async def duplicate(
        self, presentation_id: UUID, user_id: UUID
    ) -> Presentation:
        source = await self._require_access(presentation_id, user_id)
        # Carry the full spec so the duplicate is a real copy.
        source_row = await db.get_presentation(self._client, presentation_id)
        spec = source_row.get("spec") if source_row else None

        row = await db.create_presentation(
            self._client,
            owner_id=str(user_id),
            title=f"{_DEFAULT_DUPLICATE_PREFIX}{source.title}",
            description=source.description,
            theme=source.theme,
            status=source.status,
            slide_count=source.slide_count,
            spec=spec,
        )

        return _to_entity(row)

    async def _require_access(
        self, presentation_id: UUID, user_id: UUID, *, write: bool = False
    ) -> Presentation:
        row = await db.get_presentation(self._client, presentation_id)
        if row is None:
            raise NotFoundError("Presentation not found")
        role = await db.get_presentation_access_role(
            self._client, presentation_id, user_id
        )
        if role is None:
            raise NotFoundError("Presentation not found")
        if write and role not in ("owner", "admin", "editor"):
            raise ForbiddenError("You have read-only access to this presentation")
        return _to_entity(row)