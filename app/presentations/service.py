"""Presentation business logic.

Owner-scoped CRUD: every operation requires the caller's user id
(JWT ``sub``) and is restricted to that owner. Duplication creates a new
owned copy with a fresh id and a derived title.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.repositories.presentation import PresentationRepository
from app.models.presentation import Presentation as PresentationModel
from app.presentations.entities import Presentation

_TITLE_MAX = 200
_TITLE_MIN = 1
_DEFAULT_DUPLICATE_PREFIX = "Copy of "


def _to_entity(model: PresentationModel) -> Presentation:
    return Presentation(
        id=model.id,
        owner_id=model.owner_id,
        title=model.title,
        description=model.description,
        slide_count=model.slide_count,
        status=model.status,
        theme=model.theme,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _validate_title(title: str) -> str:
    stripped = title.strip()
    if len(stripped) < _TITLE_MIN:
        raise ValidationError("Title must not be empty")
    if len(stripped) > _TITLE_MAX:
        raise ValidationError(f"Title must be at most {_TITLE_MAX} characters")
    return stripped


class PresentationService:
    """Owner-scoped presentation operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._repo = PresentationRepository(session)

    async def list_for_owner(
        self, owner_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> Sequence[Presentation]:
        models = await self._repo.list_for_owner(
            owner_id, limit=max(1, min(limit, 200)), offset=max(0, offset)
        )
        return [_to_entity(m) for m in models]

    async def get(self, presentation_id: UUID, owner_id: UUID) -> Presentation:
        model = await self._repo.get(presentation_id)
        if model is None or model.owner_id != owner_id:
            raise NotFoundError("Presentation not found")
        return _to_entity(model)

    async def create(
        self,
        owner_id: UUID,
        *,
        title: str,
        description: str | None = None,
        theme: str | None = None,
    ) -> Presentation:
        clean_title = _validate_title(title)
        model = PresentationModel(
            owner_id=owner_id,
            title=clean_title,
            description=(description.strip() if description else None),
            theme=theme,
            status="draft",
            slide_count=0,
        )
        saved = await self._repo.add(model)
        return _to_entity(saved)

    async def rename(
        self, presentation_id: UUID, owner_id: UUID, *, title: str
    ) -> Presentation:
        model = await self._require_owned(presentation_id, owner_id)
        model.title = _validate_title(title)
        saved = await self._repo.update(model)
        return _to_entity(saved)

    async def delete(self, presentation_id: UUID, owner_id: UUID) -> None:
        model = await self._require_owned(presentation_id, owner_id)
        await self._repo.delete(model)

    async def duplicate(
        self, presentation_id: UUID, owner_id: UUID
    ) -> Presentation:
        source = await self._require_owned(presentation_id, owner_id)
        copy = PresentationModel(
            owner_id=owner_id,
            title=f"{_DEFAULT_DUPLICATE_PREFIX}{source.title}",
            description=source.description,
            theme=source.theme,
            status=source.status,
            slide_count=source.slide_count,
        )
        saved = await self._repo.add(copy)
        return _to_entity(saved)

    async def _require_owned(
        self, presentation_id: UUID, owner_id: UUID
    ) -> PresentationModel:
        model = await self._repo.get(presentation_id)
        if model is None or model.owner_id != owner_id:
            raise NotFoundError("Presentation not found")
        return model
