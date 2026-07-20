"""Integration tests for the files API endpoints.

Uses an in-memory SQLite database (swapped into ``app.state.db``) and the
in-memory storage gateway the app falls back to when Supabase is not
configured. Auth uses a locally signed JWT.
"""
from __future__ import annotations

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.base import Base
from app.db.dependencies import Database
from app.main import create_app

SECRET = "test-secret"


@pytest.fixture
def client(tmp_path) -> TestClient:
    db_file = tmp_path / "test_files.db"
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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _token(user_id: str, secret: str = SECRET) -> str:
    return jwt.encode({"sub": user_id, "email": "u@example.com"}, secret, algorithm="HS256")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_upload_requires_auth(client: TestClient) -> None:
    res = client.post("/api/v1/files", files={"file": ("a.pdf", b"data", "application/pdf")})
    assert res.status_code == 401


def test_upload_list_and_delete_flow(client: TestClient) -> None:
    uid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    headers = _auth(_token(uid))

    # Upload
    up = client.post(
        "/api/v1/files",
        files={"file": ("deck.pdf", b"%PDF-1.4 test", "application/pdf")},
        headers=headers,
    )
    assert up.status_code == 201
    body = up.json()
    assert body["filename"] == "deck.pdf"
    assert body["owner_id"] == uid
    fid = body["id"]

    # List
    listing = client.get("/api/v1/files", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    # Delete
    deleted = client.delete(f"/api/v1/files/{fid}", headers=headers)
    assert deleted.status_code == 204
    assert client.get("/api/v1/files", headers=headers).json()["total"] == 0


def test_upload_rejects_bad_type(client: TestClient) -> None:
    uid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    headers = _auth(_token(uid))
    res = client.post(
        "/api/v1/files",
        files={"file": ("malware.exe", b"x", "application/x-msdownload")},
        headers=headers,
    )
    assert res.status_code == 422


def test_delete_other_owner_404(client: TestClient) -> None:
    owner = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    intruder = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    owner_headers = _auth(_token(owner))

    fid = client.post(
        "/api/v1/files",
        files={"file": ("a.png", b"PNG", "image/png")},
        headers=owner_headers,
    ).json()["id"]

    intruder_headers = _auth(_token(intruder))
    res = client.delete(f"/api/v1/files/{fid}", headers=intruder_headers)
    assert res.status_code == 404
