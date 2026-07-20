"""Repository for :class:`PresentationShare` entities."""
from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.base import SqlAlchemyRepository
from app.models.presentation_share import PresentationShare


class PresentationShareRepository(SqlAlchemyRepository[PresentationShare]):
    model = PresentationShare

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_for_presentation(
        self,
        presentation_id: UUID,
        *,
        limit: int = 50,
    ) -> Sequence[PresentationShare]:
        stmt = (
            select(PresentationShare)
            .where(PresentationShare.presentation_id == presentation_id)
            .order_by(PresentationShare.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_by_token(self, token: str) -> PresentationShare | None:
        stmt = select(PresentationShare).where(PresentationShare.token == token)
        result = await self._session.execute(stmt)
        return result.scalars().first()
