"""Integration tests for the presentations API endpoints.

Uses FakeAsyncClient from conftest.py (in-memory dict-backed Supabase
stand-in) and a locally signed JWT for authentication.
"""
from __future__ import annotations

import jwt
import pytest
from fastapi.testclient import TestClient

SECRET = "test-secret"


def _token(user_id: str, secret: str = SECRET) -> str:
    return jwt.encode({"sub": user_id, "email": "u@example.com", "aud": "authenticated"}, secret, algorithm="HS256")


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