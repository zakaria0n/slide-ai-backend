"""Integration tests for the generation endpoints (offline provider).

Verifies the full generate -> store -> slides flow and ownership scoping.
The offline stub provider is used because no real provider key is set, which
keeps the test hermetic and fast.
"""
from __future__ import annotations

import jwt
import pytest
from fastapi.testclient import TestClient

from app.main import create_app

SECRET = "test-secret-generate"


@pytest.fixture
def client(tmp_path) -> TestClient:
    db_file = tmp_path / "test_generation.db"
    from app.core.config import Settings

    settings = Settings(
        _env_file=None,
        app_env="test",
        cors_allowed_origins=["http://localhost:5173"],
        supabase_jwt_secret=SECRET,
        # No provider key -> offline stub provider.
        ai_provider_api_key="public",
        database_url=f"sqlite+aiosqlite:///{db_file}",
    )
    app = create_app(settings)

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


def _token(user_id: str) -> str:
    return jwt.encode({"sub": user_id, "email": "u@example.com"}, SECRET, algorithm="HS256")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_generate_creates_deck_and_slides(client: TestClient) -> None:
    uid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    headers = _auth(_token(uid))

    res = client.post(
        "/api/v1/presentations/generate",
        json={
            "prompt": "A go-to-market plan for a new AI product",
            "slide_count": 5,
            "tone": "Professional",
            "language": "English",
            "theme": "Ocean",
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    pid = body["id"]
    assert body["status"] == "ready"
    assert body["slide_count"] == 5
    assert body["theme"] == "Ocean"
    # Title is derived from the prompt.
    assert body["title"]

    slides = client.get(f"/api/v1/presentations/{pid}/slides", headers=headers)
    assert slides.status_code == 200
    data = slides.json()
    assert len(data) == 5
    assert data[0]["index"] == 0
    assert data[0]["title"]
    assert isinstance(data[0]["bullets"], list)


def test_generate_requires_auth(client: TestClient) -> None:
    res = client.post(
        "/api/v1/presentations/generate",
        json={"prompt": "x", "slide_count": 3},
    )
    assert res.status_code == 401


def test_slides_are_owner_scoped(client: TestClient) -> None:
    owner = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    intruder = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    owner_headers = _auth(_token(owner))

    pid = client.post(
        "/api/v1/presentations/generate",
        json={"prompt": "Roadmap", "slide_count": 3},
        headers=owner_headers,
    ).json()["id"]

    intruder_headers = _auth(_token(intruder))
    res = client.get(f"/api/v1/presentations/{pid}/slides", headers=intruder_headers)
    assert res.status_code == 404


def test_spec_endpoint_returns_structured_spec(client: TestClient) -> None:
    uid = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    headers = _auth(_token(uid))

    pid = client.post(
        "/api/v1/presentations/generate",
        json={"prompt": "Investor pitch for a fintech app", "slide_count": 5},
        headers=headers,
    ).json()["id"]

    res = client.get(f"/api/v1/presentations/{pid}/spec", headers=headers)
    assert res.status_code == 200, res.text
    spec = res.json()
    assert "meta" in spec
    assert "slides" in spec
    assert len(spec["slides"]) == 5
    # Each slide has a known layout and a non-empty element list.
    layouts = {s["layout"] for s in spec["slides"]}
    assert layouts
    for slide in spec["slides"]:
        assert isinstance(slide["elements"], list)
        assert slide["elements"]


def test_spec_is_owner_scoped(client: TestClient) -> None:
    owner = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    intruder = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    owner_headers = _auth(_token(owner))
    pid = client.post(
        "/api/v1/presentations/generate",
        json={"prompt": "Onboarding", "slide_count": 3},
        headers=owner_headers,
    ).json()["id"]
    intruder_headers = _auth(_token(intruder))
    res = client.get(f"/api/v1/presentations/{pid}/spec", headers=intruder_headers)
    assert res.status_code == 404
