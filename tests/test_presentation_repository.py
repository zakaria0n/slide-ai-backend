"""Unit tests for the PresentationRepository (in-memory SQLite)."""
from __future__ import annotations

import uuid

import pytest

from app.db.repositories.presentation import PresentationRepository
from app.models.presentation import Presentation


async def _make(session, owner_id, title="Deck", **kw) -> Presentation:
    repo = PresentationRepository(session)
    return await repo.add(
        Presentation(owner_id=owner_id, title=title, **kw)
    )


async def test_add_and_list_for_owner(sqlite_session) -> None:
    owner = uuid.uuid4()
    other = uuid.uuid4()
    await _make(sqlite_session, owner, "A")
    await _make(sqlite_session, owner, "B")
    await _make(sqlite_session, other, "C")
    await sqlite_session.commit()

    repo = PresentationRepository(sqlite_session)
    mine = await repo.list_for_owner(owner)
    assert {p.title for p in mine} == {"A", "B"}
    assert await repo.count_for_owner(owner) == 2
    assert await repo.count_for_owner(other) == 1


async def test_list_for_owner_newest_first(sqlite_session) -> None:
    owner = uuid.uuid4()
    first = await _make(sqlite_session, owner, "old")
    second = await _make(sqlite_session, owner, "new")
    await sqlite_session.commit()

    # Touch updated_at to control ordering deterministically.
    first.title = "old-updated"
    await sqlite_session.flush()

    repo = PresentationRepository(sqlite_session)
    items = await repo.list_for_owner(owner)
    assert items[0].title == "old-updated"


async def test_get_and_update(sqlite_session) -> None:
    owner = uuid.uuid4()
    p = await _make(sqlite_session, owner, "title")
    await sqlite_session.commit()

    repo = PresentationRepository(sqlite_session)
    fetched = await repo.get(p.id)
    assert fetched is not None and fetched.title == "title"

    fetched.title = "renamed"
    await repo.update(fetched)
    await sqlite_session.commit()

    reloaded = await repo.get(p.id)
    assert reloaded.title == "renamed"


async def test_delete(sqlite_session) -> None:
    owner = uuid.uuid4()
    p = await _make(sqlite_session, owner, "gone")
    await sqlite_session.commit()

    repo = PresentationRepository(sqlite_session)
    await repo.delete(p)
    await sqlite_session.commit()
    assert await repo.get(p.id) is None
