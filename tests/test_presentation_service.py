"""Unit tests for the PresentationService (in-memory SQLite)."""
from __future__ import annotations

import uuid

import pytest

from app.core.exceptions import NotFoundError, ValidationError
from app.db.repositories.presentation import PresentationRepository
from app.models.presentation import Presentation
from app.presentations.service import PresentationService


@pytest.fixture
def owner_id() -> uuid.UUID:
    return uuid.uuid4()


async def test_create_and_list(sqlite_session, owner_id) -> None:
    svc = PresentationService(sqlite_session)
    created = await svc.create(owner_id, title="  My Deck  ", description="desc")
    await sqlite_session.commit()
    assert created.title == "My Deck"
    assert created.description == "desc"

    items = await svc.list_for_owner(owner_id)
    assert len(items) == 1
    assert items[0].id == created.id


async def test_create_empty_title_raises(sqlite_session, owner_id) -> None:
    svc = PresentationService(sqlite_session)
    with pytest.raises(ValidationError):
        await svc.create(owner_id, title="   ")


async def test_get_enforces_ownership(sqlite_session) -> None:
    other = uuid.uuid4()
    owner = uuid.uuid4()
    repo = PresentationRepository(sqlite_session)
    p = await repo.add(Presentation(owner_id=owner, title="x"))
    await sqlite_session.commit()

    svc = PresentationService(sqlite_session)
    with pytest.raises(NotFoundError):
        await svc.get(p.id, other)
    found = await svc.get(p.id, owner)
    assert found.title == "x"


async def test_rename(sqlite_session, owner_id) -> None:
    repo = PresentationRepository(sqlite_session)
    p = await repo.add(Presentation(owner_id=owner_id, title="orig"))
    await sqlite_session.commit()

    svc = PresentationService(sqlite_session)
    renamed = await svc.rename(p.id, owner_id, title="New Title")
    await sqlite_session.commit()
    assert renamed.title == "New Title"

    reloaded = await svc.get(p.id, owner_id)
    assert reloaded.title == "New Title"


async def test_duplicate(sqlite_session, owner_id) -> None:
    repo = PresentationRepository(sqlite_session)
    src = await repo.add(
        Presentation(owner_id=owner_id, title="Source", slide_count=10)
    )
    await sqlite_session.commit()

    svc = PresentationService(sqlite_session)
    copy = await svc.duplicate(src.id, owner_id)
    await sqlite_session.commit()
    assert copy.id != src.id
    assert copy.title == "Copy of Source"
    assert copy.slide_count == 10
    assert len(await svc.list_for_owner(owner_id)) == 2


async def test_delete(sqlite_session, owner_id) -> None:
    repo = PresentationRepository(sqlite_session)
    p = await repo.add(Presentation(owner_id=owner_id, title="temp"))
    await sqlite_session.commit()

    svc = PresentationService(sqlite_session)
    await svc.delete(p.id, owner_id)
    await sqlite_session.commit()
    with pytest.raises(NotFoundError):
        await svc.get(p.id, owner_id)
