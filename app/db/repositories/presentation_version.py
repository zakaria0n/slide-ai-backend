"""Repository for :class:`PresentationVersion` entities."""
from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.base import SqlAlchemyRepository
from app.models.presentation_version import PresentationVersion


class PresentationVersionRepository(SqlAlchemyRepository[PresentationVersion]):
    model = PresentationVersion

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_for_presentation(
        self,
        presentation_id: UUID,
        *,
        limit: int = 50,
    ) -> Sequence[PresentationVersion]:
        stmt = (
            select(PresentationVersion)
            .where(PresentationVersion.presentation_id == presentation_id)
            .order_by(PresentationVersion.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_owned(
        self,
        version_id: UUID,
        owner_id: UUID,
    ) -> PresentationVersion | None:
        stmt = (
            select(PresentationVersion)
            .where(PresentationVersion.id == version_id)
            .where(PresentationVersion.owner_id == owner_id)
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def count_for_presentation(self, presentation_id: UUID) -> int:
        from sqlalchemy import func

        stmt = (
            select(func.count())
            .select_from(PresentationVersion)
            .where(PresentationVersion.presentation_id == presentation_id)
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def get_latest_spec_hash(self, presentation_id: UUID) -> str | None:
        """Return the latest version's spec as a string for comparison."""
        stmt = (
            select(PresentationVersion.spec)
            .where(PresentationVersion.presentation_id == presentation_id)
            .order_by(PresentationVersion.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        import json
        return json.dumps(row, sort_keys=True)
