"""Repository for :class:`FileAsset` entities (owner-scoped)."""
from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.base import SqlAlchemyRepository
from app.models.file_asset import FileAsset


class FileAssetRepository(SqlAlchemyRepository[FileAsset]):
    """Owner-scoped persistence for file assets."""

    model = FileAsset

    async def list_for_owner(
        self, owner_id: UUID, *, limit: int = 100, offset: int = 0
    ) -> Sequence[FileAsset]:
        stmt = (
            select(FileAsset)
            .where(FileAsset.owner_id == owner_id)
            .order_by(FileAsset.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()
