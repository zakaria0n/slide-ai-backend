"""Integration tests for the authentication API endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    settings = Settings(
        _env_file=None,
        app_env="test",
        cors_allowed_origins=["http://localhost:5173"],
        supabase_jwt_secret="test-secret",
        database_url="postgresql+asyncpg://u:p@127.0.0.1:1/none",
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def test_signup_returns_201_and_tokens(client: TestClient) -> None:
    res = client.post(
        "/api/v1/auth/signup",
        json={"email": "new@example.com", "password": "password123", "full_name": "Neo"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["user"]["email"] == "new@example.com"
    assert body["user"]["display_name"] == "Neo"
    assert body["tokens"]["access_token"]
    assert body["tokens"]["token_type"] == "bearer"


def test_signup_duplicate_returns_409(client: TestClient) -> None:
    payload = {"email": "dup@example.com", "password": "password123"}
    first = client.post("/api/v1/auth/signup", json=payload)
    assert first.status_code == 201
    second = client.post("/api/v1/auth/signup", json=payload)
    assert second.status_code == 409
    assert second.json()["error"] == "conflict"


def test_signin_success_and_me(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/signup",
        json={"email": "me@example.com", "password": "password123", "full_name": "Me"},
    )
    res = client.post(
        "/api/v1/auth/signin",
        json={"email": "me@example.com", "password": "password123"},
    )
    assert res.status_code == 200
    token = res.json()["tokens"]["access_token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "me@example.com"


def test_signin_wrong_password_401(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/signup",
        json={"email": "x@example.com", "password": "password123"},
    )
    res = client.post(
        "/api/v1/auth/signin",
        json={"email": "x@example.com", "password": "nope"},
    )
    assert res.status_code == 401
    assert res.json()["error"] == "unauthorized"


def test_me_without_token_401(client: TestClient) -> None:
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401


def test_me_with_bad_token_401(client: TestClient) -> None:
    res = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert res.status_code == 401


def test_signout_returns_ok(client: TestClient) -> None:
    res = client.post("/api/v1/auth/signout", json={})
    assert res.status_code == 200
    assert res.json()["message"] == "Signed out"


def test_signup_validation_error_422(client: TestClient) -> None:
    res = client.post(
        "/api/v1/auth/signup",
        json={"email": "not-an-email", "password": "short"},
    )
    assert res.status_code == 422
