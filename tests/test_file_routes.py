"""Integration tests for the files API endpoints using FakeAsyncClient."""
from __future__ import annotations

import jwt
import pytest
from fastapi.testclient import TestClient

SECRET = "test-secret"


def _token(user_id: str, secret: str = SECRET) -> str:
    return jwt.encode({"sub": user_id, "email": "u@example.com", "aud": "authenticated"}, secret, algorithm="HS256")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_upload_requires_auth(client: TestClient) -> None:
    res = client.post("/api/v1/files", files={"file": ("a.pdf", b"data", "application/pdf")})
    assert res.status_code == 401


def test_upload_list_and_delete_flow(client: TestClient) -> None:
    uid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    headers = _auth(_token(uid))

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

    listing = client.get("/api/v1/files", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

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


def test_get_signed_url_owner_scoped(client: TestClient) -> None:
    owner = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    intruder = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    owner_headers = _auth(_token(owner))

    fid = client.post(
        "/api/v1/files",
        files={"file": ("pic.png", b"PNG-DATA", "image/png")},
        headers=owner_headers,
    ).json()["id"]

    res = client.get(f"/api/v1/files/{fid}/url", headers=owner_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["expires_in"] == 3600
    assert body["url"]

    intruder_headers = _auth(_token(intruder))
    res2 = client.get(f"/api/v1/files/{fid}/url", headers=intruder_headers)
    assert res2.status_code == 404


def test_get_signed_url_requires_auth(client: TestClient) -> None:
    res = client.get("/api/v1/files/12345678-1234-1234-1234-123456789012/url")
    assert res.status_code == 401