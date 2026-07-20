"""Repository for :class:`Presentation` entities.

Persistence logic lives here; business rules (ownership, duplication)
live in the service layer. The repository only knows how to read and
write ``Presentation`` rows scoped by ``owner_id``.
"""
from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.base import SqlAlchemyRepository
from app.models.presentation import Presentation


class PresentationRepository(SqlAlchemyRepository[Presentation]):
    """Owner-scoped persistence for presentations."""

    model = Presentation

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_for_owner(
        self,
        owner_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Presentation]:
        """Return the owner's presentations, newest first."""
        stmt = (
            select(Presentation)
            .where(Presentation.owner_id == owner_id)
            .order_by(Presentation.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def count_for_owner(self, owner_id: UUID) -> int:
        from sqlalchemy import func

        stmt = (
            select(func.count())
            .select_from(Presentation)
            .where(Presentation.owner_id == owner_id)
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())
