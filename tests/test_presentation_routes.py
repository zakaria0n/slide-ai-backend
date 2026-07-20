"""Integration tests for the presentations API endpoints.

Uses an in-memory SQLite database (swapped into ``app.state.db``) and a
locally signed JWT so requests authenticate like a real Supabase token.
"""
from __future__ import annotations

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

SECRET = "test-secret"


@pytest.fixture
def client(tmp_path) -> TestClient:
    db_file = tmp_path / "test_presentations.db"
    settings = Settings(
        _env_file=None,
        app_env="test",
        cors_allowed_origins=["http://localhost:5173"],
        supabase_jwt_secret=SECRET,
        database_url=f"sqlite+aiosqlite:///{db_file}",
    )
    app = create_app(settings)

    # Create the schema in the file-backed SQLite database the lifespan
    # engine will use.
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_ensure_schema(engine))
    finally:
        loop.run_until_complete(engine.dispose())
        loop.close()

    with TestClient(app) as c:
        yield c


async def _ensure_schema(engine) -> None:
    from app.db.base import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _token(user_id: str, secret: str = SECRET) -> str:
    return jwt.encode({"sub": user_id, "email": "u@example.com"}, secret, algorithm="HS256")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_list_requires_auth(client: TestClient) -> None:
    res = client.get("/api/v1/presentations")
    assert res.status_code == 401


def test_full_crud_flow(client: TestClient) -> None:
    uid = "11111111-1111-1111-1111-111111111111"
    headers = _auth(_token(uid))

    # Create
    create = client.post(
        "/api/v1/presentations",
        json={"title": "Q3 Review", "description": "quarterly"},
        headers=headers,
    )
    assert create.status_code == 201
    created = create.json()
    pid = created["id"]
    assert created["title"] == "Q3 Review"
    assert created["owner_id"] == uid

    # List
    listing = client.get("/api/v1/presentations", headers=headers)
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == pid

    # Get
    got = client.get(f"/api/v1/presentations/{pid}", headers=headers)
    assert got.status_code == 200
    assert got.json()["title"] == "Q3 Review"

    # Rename
    renamed = client.patch(
        f"/api/v1/presentations/{pid}",
        json={"title": "Q3 Review v2"},
        headers=headers,
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Q3 Review v2"

    # Duplicate
    dup = client.post(
        f"/api/v1/presentations/{pid}/duplicate", headers=headers
    )
    assert dup.status_code == 200
    assert dup.json()["title"] == "Copy of Q3 Review v2"
    assert dup.json()["id"] != pid

    assert client.get("/api/v1/presentations", headers=headers).json()["total"] == 2

    # Delete
    deleted = client.delete(f"/api/v1/presentations/{pid}", headers=headers)
    assert deleted.status_code == 204
    after = client.get("/api/v1/presentations", headers=headers).json()
    assert after["total"] == 1


def test_get_missing_returns_404(client: TestClient) -> None:
    uid = "22222222-2222-2222-2222-222222222222"
    headers = _auth(_token(uid))
    missing = "00000000-0000-0000-0000-000000000000"
    res = client.get(f"/api/v1/presentations/{missing}", headers=headers)
    assert res.status_code == 404


def test_owner_cannot_access_others_presentation(client: TestClient) -> None:
    owner = "33333333-3333-3333-3333-333333333333"
    intruder = "44444444-4444-4444-4444-444444444444"
    owner_headers = _auth(_token(owner))

    created = client.post(
        "/api/v1/presentations",
        json={"title": "Private"},
        headers=owner_headers,
    ).json()
    pid = created["id"]

    intruder_headers = _auth(_token(intruder))
    res = client.get(f"/api/v1/presentations/{pid}", headers=intruder_headers)
    assert res.status_code == 404


def test_update_spec_persists(client: TestClient) -> None:
    import asyncio
    from app.generation.spec import PresentationSpec
    from app.generation.spec_provider import OfflineSpecProvider

    uid = "55555555-5555-5555-5555-555555555555"
    headers = _auth(_token(uid))

    # Create a presentation with a spec via the generate endpoint.
    gen = client.post(
        "/api/v1/presentations/generate",
        json={"prompt": "test deck", "slide_count": 3},
        headers=headers,
    )
    assert gen.status_code == 201
    pid = gen.json()["id"]

    # Verify spec exists.
    spec_res = client.get(f"/api/v1/presentations/{pid}/spec", headers=headers)
    assert spec_res.status_code == 200
    original = spec_res.json()
    assert len(original["slides"]) == 3

    # Update: change the title of the first slide.
    original["slides"][0]["elements"][0]["text"] = "Updated Title"
    update = client.put(
        f"/api/v1/presentations/{pid}/spec",
        json=original,
        headers=headers,
    )
    assert update.status_code == 200
    updated = update.json()
    assert updated["slides"][0]["elements"][0]["text"] == "Updated Title"

    # Re-fetch to confirm persistence.
    re_fetched = client.get(f"/api/v1/presentations/{pid}/spec", headers=headers)
    assert re_fetched.json()["slides"][0]["elements"][0]["text"] == "Updated Title"


def test_update_spec_owner_scoped(client: TestClient) -> None:
    owner = "66666666-6666-6666-6666-666666666666"
    intruder = "77777777-7777-7777-7777-777777777777"
    headers = _auth(_token(owner))

    gen = client.post(
        "/api/v1/presentations/generate",
        json={"prompt": "my deck", "slide_count": 2},
        headers=headers,
    ).json()
    pid = gen["id"]

    spec = client.get(f"/api/v1/presentations/{pid}/spec", headers=headers).json()
    spec["meta"]["title"] = "Hacked"
    res = client.put(
        f"/api/v1/presentations/{pid}/spec",
        json=spec,
        headers=_auth(_token(intruder)),
    )
    assert res.status_code == 404


def test_update_spec_validates(client: TestClient) -> None:
    uid = "88888888-8888-8888-8888-888888888888"
    headers = _auth(_token(uid))

    gen = client.post(
        "/api/v1/presentations/generate",
        json={"prompt": "x", "slide_count": 2},
        headers=headers,
    ).json()
    pid = gen["id"]

    bad = {"slides": []}  # empty slides
    res = client.put(f"/api/v1/presentations/{pid}/spec", json=bad, headers=headers)
    assert res.status_code == 422
