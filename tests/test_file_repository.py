"""Unit tests for the FileAssetRepository (in-memory SQLite)."""
from __future__ import annotations

import uuid

import pytest

from app.db.repositories.file_asset import FileAssetRepository
from app.models.file_asset import FileAsset


async def _make(session, owner_id, filename="doc.pdf", **kw) -> FileAsset:
    import uuid as _uuid

    path = kw.pop("storage_path", None) or f"{owner_id}/{_uuid.uuid4()}-x"
    repo = FileAssetRepository(session)
    return await repo.add(FileAsset(owner_id=owner_id, filename=filename, storage_path=path, **kw))


async def test_list_for_owner_scoped(sqlite_session) -> None:
    owner = uuid.uuid4()
    other = uuid.uuid4()
    await _make(sqlite_session, owner, "a.pdf")
    await _make(sqlite_session, owner, "b.png")
    await _make(sqlite_session, other, "c.pdf")
    await sqlite_session.commit()

    repo = FileAssetRepository(sqlite_session)
    mine = await repo.list_for_owner(owner)
    assert {f.filename for f in mine} == {"a.pdf", "b.png"}
    assert len(mine) == 2


async def test_get_and_delete(sqlite_session) -> None:
    owner = uuid.uuid4()
    f = await _make(sqlite_session, owner, "x.pdf")
    await sqlite_session.commit()

    repo = FileAssetRepository(sqlite_session)
    assert (await repo.get(f.id)) is not None
    await repo.delete(f)
    await sqlite_session.commit()
    assert await repo.get(f.id) is None
