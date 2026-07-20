"""Generic repository pattern implementation.

Defines an abstract :class:`Repository` protocol and an async SQLAlchemy
implementation :class:`SqlAlchemyRepository`. Concrete repositories
(users, presentations, ...) subclass the implementation and only add
entity-specific queries. This keeps persistence logic out of services.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class Repository(ABC, Generic[ModelType]):
    """Abstract persistence contract for an entity."""

    @abstractmethod
    async def get(self, id: UUID) -> ModelType | None:
        ...

    @abstractmethod
    async def get_or_raise(self, id: UUID) -> ModelType:
        ...

    @abstractmethod
    async def list(
        self, *, limit: int = 50, offset: int = 0, **filters: Any
    ) -> Sequence[ModelType]:
        ...

    @abstractmethod
    async def count(self, **filters: Any) -> int:
        ...

    @abstractmethod
    async def add(self, entity: ModelType) -> ModelType:
        ...

    @abstractmethod
    async def update(self, entity: ModelType) -> ModelType:
        ...

    @abstractmethod
    async def delete(self, entity: ModelType) -> None:
        ...


class SqlAlchemyRepository(Repository[ModelType]):
    """Async SQLAlchemy implementation of :class:`Repository`."""

    model: type[ModelType]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, id: UUID) -> ModelType | None:
        return await self._session.get(self.model, id)

    async def get_or_raise(self, id: UUID) -> ModelType:
        from app.core.exceptions import NotFoundError

        entity = await self._session.get(self.model, id)
        if entity is None:
            raise NotFoundError(
                f"{self.model.__name__} not found",
                detail=str(id),
            )
        return entity

    async def list(
        self, *, limit: int = 50, offset: int = 0, **filters: Any
    ) -> Sequence[ModelType]:
        stmt = select(self.model)
        for key, value in filters.items():
            stmt = stmt.where(getattr(self.model, key) == value)
        stmt = stmt.limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def count(self, **filters: Any) -> int:
        stmt = select(func.count()).select_from(self.model)
        for key, value in filters.items():
            stmt = stmt.where(getattr(self.model, key) == value)
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def add(self, entity: ModelType) -> ModelType:
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def update(self, entity: ModelType) -> ModelType:
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def delete(self, entity: ModelType) -> None:
        await self._session.delete(entity)
        await self._session.flush()
