"""Tests for the sharing feature using FakeAsyncClient."""
from __future__ import annotations

import jwt
import pytest
from fastapi.testclient import TestClient

SECRET = "test-secret"


def _token(user_id: str, secret: str = SECRET) -> str:
    return jwt.encode({"sub": user_id, "email": "u@example.com", "aud": "authenticated"}, secret, algorithm="HS256")


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

    shared = client.get(f"/api/v1/shared/{token}")
    assert shared.status_code == 200
    assert "spec" in shared.json()


def test_private_share_denied(client: TestClient) -> None:
    uid = "33333333-3333-3333-3333-333333333333"
    pid = _create_presentation(client, uid)

    create = client.post(
        f"/api/v1/presentations/{pid}/shares",
        json={"visibility": "private"},
        headers=_auth(_token(uid)),
    ).json()
    token = create["token"]

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

    res = client.get(f"/api/v1/shared/{token}")
    assert res.status_code == 403

    res = client.get(f"/api/v1/shared/{token}?password=wrong")
    assert res.status_code == 403

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

    res = client.delete(
        f"/api/v1/shares/{token}",
        headers=_auth(_token(uid)),
    )
    assert res.status_code == 204

    shared = client.get(f"/api/v1/shared/{token}")
    assert shared.status_code == 404