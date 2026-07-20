"""Tests for the sharing feature."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

SECRET = "test-secret"


@pytest.fixture
def client(tmp_path) -> TestClient:
    db_file = tmp_path / "test_sharing.db"
    settings = Settings(
        _env_file=None,
        app_env="test",
        cors_allowed_origins=["http://localhost:5173"],
        supabase_jwt_secret=SECRET,
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
    import app.models.presentation  # noqa: F401
    import app.models.slide  # noqa: F401
    import app.models.file_asset  # noqa: F401
    import app.models.presentation_version  # noqa: F401
    import app.models.presentation_share  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _token(user_id: str, secret: str = SECRET) -> str:
    import jwt
    return jwt.encode({"sub": user_id, "email": "u@example.com"}, secret, algorithm="HS256")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_presentation(client: TestClient, uid: str) -> str:
    """Generate a presentation and return its id."""
    gen = client.post(
        "/api/v1/presentations/generate",
        json={"prompt": "share test", "slide_count": 2},
        headers=_auth(_token(uid)),
    ).json()
    return gen["id"]


def test_create_and_list_shares(client: TestClient) -> None:
    uid = "11111111-1111-1111-1111-111111111111"
    pid = _create_presentation(client, uid)

    res = client.post(
        f"/api/v1/presentations/{pid}/shares",
        json={"visibility": "public", "permission": "view"},
        headers=_auth(_token(uid)),
    )
    assert res.status_code == 201
    share = res.json()
    assert share["token"]
    assert share["visibility"] == "public"

    # List.
    listing = client.get(
        f"/api/v1/presentations/{pid}/shares",
        headers=_auth(_token(uid)),
    )
    assert listing.status_code == 200
    assert len(listing.json()["shares"]) == 1


def test_public_share_access(client: TestClient) -> None:
    uid = "22222222-2222-2222-2222-222222222222"
    pid = _create_presentation(client, uid)

    create = client.post(
        f"/api/v1/presentations/{pid}/shares",
        json={"visibility": "public"},
        headers=_auth(_token(uid)),
    ).json()
    token = create["token"]

    # Public access without auth.
    shared = client.get(f"/api/v1/shared/{token}")
    assert shared.status_code == 200
    assert "spec" in shared.json()
    assert shared.json()["title"].lower() == "share test"


def test_private_share_denied(client: TestClient) -> None:
    uid = "33333333-3333-3333-3333-333333333333"
    pid = _create_presentation(client, uid)

    create = client.post(
        f"/api/v1/presentations/{pid}/shares",
        json={"visibility": "private"},
        headers=_auth(_token(uid)),
    ).json()
    token = create["token"]

    # Private share returns 404 for anyone.
    shared = client.get(f"/api/v1/shared/{token}")
    assert shared.status_code == 404


def test_password_share(client: TestClient) -> None:
    uid = "44444444-4444-4444-4444-444444444444"
    pid = _create_presentation(client, uid)

    create = client.post(
        f"/api/v1/presentations/{pid}/shares",
        json={"visibility": "password", "password": "secret123"},
        headers=_auth(_token(uid)),
    ).json()
    token = create["token"]

    # No password → 403.
    res = client.get(f"/api/v1/shared/{token}")
    assert res.status_code == 403

    # Wrong password → 403.
    res = client.get(f"/api/v1/shared/{token}?password=wrong")
    assert res.status_code == 403

    # Correct password → 200.
    res = client.get(f"/api/v1/shared/{token}?password=secret123")
    assert res.status_code == 200


def test_revoke_share(client: TestClient) -> None:
    uid = "55555555-5555-5555-5555-555555555555"
    pid = _create_presentation(client, uid)

    create = client.post(
        f"/api/v1/presentations/{pid}/shares",
        json={"visibility": "public"},
        headers=_auth(_token(uid)),
    ).json()
    token = create["token"]

    # Revoke.
    res = client.delete(
        f"/api/v1/shares/{token}",
        headers=_auth(_token(uid)),
    )
    assert res.status_code == 204

    # Token no longer works.
    shared = client.get(f"/api/v1/shared/{token}")
    assert shared.status_code == 404
