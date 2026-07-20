"""Tests for workspaces."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

SECRET = "test-secret"


@pytest.fixture
def client(tmp_path) -> TestClient:
    db_file = tmp_path / "test_workspaces.db"
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
    import app.models.workspace  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _token(user_id: str, secret: str = SECRET) -> str:
    import jwt
    return jwt.encode({"sub": user_id, "email": "u@example.com"}, secret, algorithm="HS256")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_create_and_list_workspace(client: TestClient) -> None:
    uid = "11111111-1111-1111-1111-111111111111"
    headers = _auth(_token(uid))

    res = client.post("/api/v1/workspaces", json={"name": "My Team"}, headers=headers)
    assert res.status_code == 201
    ws = res.json()
    assert ws["name"] == "My Team"

    listing = client.get("/api/v1/workspaces", headers=headers)
    assert listing.status_code == 200
    assert len(listing.json()["workspaces"]) == 1


def test_add_member(client: TestClient) -> None:
    owner = "22222222-2222-2222-2222-222222222222"
    member_uid = "33333333-3333-3333-3333-333333333333"
    headers = _auth(_token(owner))

    ws = client.post("/api/v1/workspaces", json={"name": "WS"}, headers=headers).json()
    wid = ws["id"]

    res = client.post(
        f"/api/v1/workspaces/{wid}/members",
        json={"user_id": member_uid, "role": "editor"},
        headers=headers,
    )
    assert res.status_code == 201
    assert res.json()["role"] == "editor"

    members = client.get(f"/api/v1/workspaces/{wid}/members", headers=headers)
    assert len(members.json()["members"]) == 2  # owner + editor


def test_change_role(client: TestClient) -> None:
    owner = "44444444-4444-4444-4444-444444444444"
    member_uid = "55555555-5555-5555-5555-555555555555"
    headers = _auth(_token(owner))

    ws = client.post("/api/v1/workspaces", json={"name": "WS"}, headers=headers).json()
    wid = ws["id"]
    client.post(f"/api/v1/workspaces/{wid}/members", json={"user_id": member_uid, "role": "viewer"}, headers=headers)

    res = client.patch(
        f"/api/v1/workspaces/{wid}/members/{member_uid}",
        json={"role": "admin"},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["role"] == "admin"


def test_remove_member(client: TestClient) -> None:
    owner = "66666666-6666-6666-6666-666666666666"
    member_uid = "77777777-7777-7777-7777-777777777777"
    headers = _auth(_token(owner))

    ws = client.post("/api/v1/workspaces", json={"name": "WS"}, headers=headers).json()
    wid = ws["id"]
    client.post(f"/api/v1/workspaces/{wid}/members", json={"user_id": member_uid, "role": "viewer"}, headers=headers)

    res = client.delete(f"/api/v1/workspaces/{wid}/members/{member_uid}", headers=headers)
    assert res.status_code == 204

    members = client.get(f"/api/v1/workspaces/{wid}/members", headers=headers)
    assert len(members.json()["members"]) == 1  # only owner


def test_audit_log(client: TestClient) -> None:
    owner = "88888888-8888-8888-8888-888888888888"
    member_uid = "99999999-9999-9999-9999-999999999999"
    headers = _auth(_token(owner))

    ws = client.post("/api/v1/workspaces", json={"name": "WS"}, headers=headers).json()
    wid = ws["id"]
    client.post(f"/api/v1/workspaces/{wid}/members", json={"user_id": member_uid, "role": "editor"}, headers=headers)

    audit = client.get(f"/api/v1/workspaces/{wid}/audit", headers=headers)
    assert audit.status_code == 200
    entries = audit.json()["entries"]
    assert len(entries) >= 1
    assert entries[0]["action"] == "add_member"
