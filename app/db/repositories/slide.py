"""Repository for :class:`Slide` entities.

Slides are owned transitively through their presentation, but the
``owner_id`` column is denormalized for RLS and owner-scoped queries.
"""
from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.base import SqlAlchemyRepository
from app.models.slide import Slide


class SlideRepository(SqlAlchemyRepository[Slide]):
    """Persistence for presentation slides."""

    model = Slide

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_for_presentation(
        self, presentation_id: UUID, *, owner_id: UUID
    ) -> Sequence[Slide]:
        stmt = (
            select(Slide)
            .where(Slide.presentation_id == presentation_id)
            .where(Slide.owner_id == owner_id)
            .order_by(Slide.slide_index.asc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def delete_for_presentation(
        self, presentation_id: UUID, *, owner_id: UUID
    ) -> None:
        rows = await self.list_for_presentation(presentation_id, owner_id=owner_id)
        for row in rows:
            await self._session.delete(row)
