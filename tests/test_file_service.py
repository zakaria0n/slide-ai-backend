"""Unit tests for the FileService (in-memory SQLite + fake storage)."""
from __future__ import annotations

import uuid

import pytest

from app.core.exceptions import NotFoundError, ValidationError
from app.db.repositories.file_asset import FileAssetRepository
from app.files.service import FileService
from app.files.storage import InMemoryStorageGateway
from app.models.file_asset import FileAsset


@pytest.fixture
def owner_id() -> uuid.UUID:
    return uuid.uuid4()


async def test_upload_stores_metadata_and_object(sqlite_session, owner_id) -> None:
    storage = InMemoryStorageGateway()
    svc = FileService(sqlite_session, storage)
    created = await svc.upload(
        owner_id, filename="deck.pdf", data=b"%PDF-1.4 content", content_type="application/pdf"
    )
    await sqlite_session.commit()

    assert created.filename == "deck.pdf"
    assert created.size_bytes == len(b"%PDF-1.4 content")
    assert created.storage_path.startswith(f"{owner_id}/")
    assert created.storage_path in storage._objects


async def test_upload_rejects_disallowed_type(sqlite_session, owner_id) -> None:
    svc = FileService(sqlite_session, InMemoryStorageGateway())
    with pytest.raises(ValidationError):
        await svc.upload(owner_id, filename="evil.exe", data=b"x", content_type="application/x-msdownload")


async def test_upload_rejects_empty(sqlite_session, owner_id) -> None:
    svc = FileService(sqlite_session, InMemoryStorageGateway())
    with pytest.raises(ValidationError):
        await svc.upload(owner_id, filename="empty.pdf", data=b"", content_type="application/pdf")


async def test_list_and_delete(sqlite_session, owner_id) -> None:
    storage = InMemoryStorageGateway()
    svc = FileService(sqlite_session, storage)
    f = await svc.upload(owner_id, filename="a.png", data=b"PNGDATA", content_type="image/png")
    await sqlite_session.commit()

    items = await svc.list_for_owner(owner_id)
    assert len(items) == 1

    await svc.delete(f.id, owner_id)
    await sqlite_session.commit()
    assert await svc.list_for_owner(owner_id) == []
    assert f.storage_path not in storage._objects


async def test_delete_enforces_ownership(sqlite_session, owner_id) -> None:
    other = uuid.uuid4()
    repo = FileAssetRepository(sqlite_session)
    f = await repo.add(FileAsset(owner_id=owner_id, filename="a.pdf", storage_path=f"{owner_id}/a"))
    await sqlite_session.commit()

    svc = FileService(sqlite_session, InMemoryStorageGateway())
    with pytest.raises(NotFoundError):
        await svc.delete(f.id, other)
