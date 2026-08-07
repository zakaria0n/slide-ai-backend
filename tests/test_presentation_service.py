"""Unit tests for PresentationService using FakeAsyncClient."""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.exceptions import NotFoundError, ValidationError
from app.presentations.service import PresentationService

from tests.conftest import FakeAsyncClient


@pytest.fixture
def owner_id() -> uuid4:
    return uuid4()  # type: ignore[return-value]


@pytest.fixture
def supabase() -> FakeAsyncClient:
    return FakeAsyncClient()


async def test_create_and_list(supabase, owner_id) -> None:
    svc = PresentationService(supabase)
    created = await svc.create(owner_id, title="  My Deck  ", description="desc")
    assert created.title == "My Deck"
    assert created.description == "desc"

    items = await svc.list_for_owner(owner_id)
    assert len(items) == 1
    assert items[0].id == created.id


async def test_create_empty_title_raises(supabase, owner_id) -> None:
    svc = PresentationService(supabase)
    with pytest.raises(ValidationError):
        await svc.create(owner_id, title="   ")


async def test_get_enforces_ownership(supabase) -> None:
    other = uuid4()
    owner = uuid4()
    svc = PresentationService(supabase)
    p = await svc.create(owner, title="x")
    with pytest.raises(NotFoundError):
        await svc.get(p.id, other)
    found = await svc.get(p.id, owner)
    assert found.title == "x"


async def test_rename(supabase, owner_id) -> None:
    svc = PresentationService(supabase)
    p = await svc.create(owner_id, title="orig")
    renamed = await svc.rename(p.id, owner_id, title="New Title")
    assert renamed.title == "New Title"
    reloaded = await svc.get(p.id, owner_id)
    assert reloaded.title == "New Title"


async def test_duplicate(supabase, owner_id) -> None:
    svc = PresentationService(supabase)
    src = await svc.create(owner_id, title="Source")
    # Manually set slide_count in the store for this test.
    rows = supabase.table("presentations")._rows()
    for r in rows:
        if r["id"] == str(src.id):
            r["slide_count"] = 10
    copy = await svc.duplicate(src.id, owner_id)
    assert copy.id != src.id
    assert copy.title == "Copy of Source"
    assert copy.slide_count == 10
    assert len(await svc.list_for_owner(owner_id)) == 2


async def test_delete(supabase, owner_id) -> None:
    svc = PresentationService(supabase)
    p = await svc.create(owner_id, title="temp")
    await svc.delete(p.id, owner_id)
    with pytest.raises(NotFoundError):
        await svc.get(p.id, owner_id)