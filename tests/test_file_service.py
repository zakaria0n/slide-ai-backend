"""Unit tests for FileService using FakeAsyncClient."""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.exceptions import NotFoundError, ValidationError
from app.files.service import FileService
from app.files.storage import InMemoryStorageGateway

from tests.conftest import FakeAsyncClient


@pytest.fixture
def owner_id() -> uuid4:
    return uuid4()  # type: ignore[return-value]


@pytest.fixture
def supabase() -> FakeAsyncClient:
    return FakeAsyncClient()


async def test_upload_stores_metadata_and_object(supabase, owner_id) -> None:
    storage = InMemoryStorageGateway()
    svc = FileService(supabase, storage)
    created = await svc.upload(
        owner_id, filename="deck.pdf", data=b"%PDF-1.4 content", content_type="application/pdf"
    )
    assert created["filename"] == "deck.pdf"
    assert created["size_bytes"] == len(b"%PDF-1.4 content")
    assert created["storage_path"].startswith(f"{owner_id}/")
    assert created["storage_path"] in storage._objects


async def test_upload_rejects_disallowed_type(supabase, owner_id) -> None:
    svc = FileService(supabase, InMemoryStorageGateway())
    with pytest.raises(ValidationError):
        await svc.upload(owner_id, filename="evil.exe", data=b"x", content_type="application/x-msdownload")


async def test_upload_rejects_empty(supabase, owner_id) -> None:
    svc = FileService(supabase, InMemoryStorageGateway())
    with pytest.raises(ValidationError):
        await svc.upload(owner_id, filename="empty.pdf", data=b"", content_type="application/pdf")


async def test_list_and_delete(supabase, owner_id) -> None:
    storage = InMemoryStorageGateway()
    svc = FileService(supabase, storage)
    f = await svc.upload(owner_id, filename="a.png", data=b"PNGDATA", content_type="image/png")
    items = await svc.list_for_owner(owner_id)
    assert len(items) == 1
    await svc.delete(f["id"], owner_id)
    assert await svc.list_for_owner(owner_id) == []
    assert f["storage_path"] not in storage._objects


async def test_delete_enforces_ownership(supabase, owner_id) -> None:
    other = uuid4()
    svc = FileService(supabase, InMemoryStorageGateway())
    f = await svc.upload(owner_id, filename="a.pdf", data=b"data", content_type="application/pdf")
    with pytest.raises(NotFoundError):
        await svc.delete(f["id"], other)