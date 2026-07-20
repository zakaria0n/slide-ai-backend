"""Unit tests for the SQLAlchemy repository implementation.

Uses an in-memory SQLite database (see conftest) and a small concrete
model + repository defined inline so the generic layer is exercised in
isolation from domain entities.
"""
from __future__ import annotations

import uuid

import pytest

from sqlalchemy import String, select
from sqlalchemy.orm import Mapped, mapped_column

from app.core.exceptions import NotFoundError
from app.db.base import Base
from app.db.repositories.base import SqlAlchemyRepository


class _Sample(Base):
    __tablename__ = "sample"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(50))
    tenant: Mapped[str] = mapped_column(String(50))


class SampleRepo(SqlAlchemyRepository[_Sample]):
    model = _Sample


async def test_add_and_get(sqlite_session) -> None:
    repo = SampleRepo(sqlite_session)
    entity = _Sample(name="alpha", tenant="t1")
    saved = await repo.add(entity)
    assert saved.id is not None

    fetched = await repo.get(saved.id)
    assert fetched is not None
    assert fetched.name == "alpha"


async def test_get_or_raise_raises_not_found(sqlite_session) -> None:
    repo = SampleRepo(sqlite_session)
    with pytest.raises(NotFoundError):
        await repo.get_or_raise(uuid.uuid4())


async def test_list_with_filters_and_count(sqlite_session) -> None:
    repo = SampleRepo(sqlite_session)
    await repo.add(_Sample(name="a", tenant="t1"))
    await repo.add(_Sample(name="b", tenant="t1"))
    await repo.add(_Sample(name="c", tenant="t2"))

    t1 = await repo.list(tenant="t1")
    assert len(t1) == 2
    assert await repo.count(tenant="t1") == 2
    assert await repo.count() == 3


async def test_update_persists_changes(sqlite_session) -> None:
    repo = SampleRepo(sqlite_session)
    entity = await repo.add(_Sample(name="old", tenant="t1"))
    entity.name = "new"
    await repo.update(entity)
    await sqlite_session.commit()

    reloaded = await repo.get(entity.id)
    assert reloaded.name == "new"


async def test_delete(sqlite_session) -> None:
    repo = SampleRepo(sqlite_session)
    entity = await repo.add(_Sample(name="x", tenant="t1"))
    await repo.delete(entity)
    await sqlite_session.commit()
    assert await repo.get(entity.id) is None

