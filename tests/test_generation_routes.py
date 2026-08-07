"""Integration tests for the generation endpoints (offline provider).

Verifies the full generate -> store spec flow and ownership scoping.
Uses FakeAsyncClient from conftest.py.
"""
from __future__ import annotations

import jwt
from fastapi.testclient import TestClient

SECRET = "test-secret"


def _token(user_id: str) -> str:
    return jwt.encode({"sub": user_id, "email": "u@example.com", "aud": "authenticated"}, SECRET, algorithm="HS256")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_generate_creates_deck(client: TestClient) -> None:
    uid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    headers = _auth(_token(uid))

    res = client.post(
        "/api/v1/presentations/generate",
        json={
            "prompt": "A go-to-market plan for a new AI product",
            "slide_count": 5,
            "tone": "Professional",
            "language": "English",
            "theme": "modern",
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "ready"
    assert body["slide_count"] == 5
    assert body["title"]


def test_generate_requires_auth(client: TestClient) -> None:
    res = client.post(
        "/api/v1/presentations/generate",
        json={"prompt": "x", "slide_count": 3},
    )
    assert res.status_code == 401


def test_generate_accepts_template_name(client: TestClient) -> None:
    uid = "11111111-1111-1111-1111-111111111111"
    headers = _auth(_token(uid))

    res = client.post(
        "/api/v1/presentations/generate",
        json={
            "prompt": "Pitch for a fintech startup",
            "slide_count": 5,
            "tone": "Professional",
            "language": "English",
            "template_name": "startup_pitch",
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    assert res.json()["slide_count"] == 5


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


def test_generate_persists_spec_only(client: TestClient) -> None:
    """Generation persists the spec on the presentation — the legacy slides
    table is no longer written to and its endpoint is gone."""
    uid = "12345678-1234-1234-1234-123456789012"
    headers = _auth(_token(uid))

    pid = client.post(
        "/api/v1/presentations/generate",
        json={"prompt": "Quarterly review", "slide_count": 4},
        headers=headers,
    ).json()["id"]

    slides = client.get(f"/api/v1/presentations/{pid}/slides", headers=headers)
    assert slides.status_code == 404

    res = client.get(f"/api/v1/presentations/{pid}/spec", headers=headers)
    assert res.status_code == 200
    spec = res.json()
    assert spec["meta"]["title"]
    assert len(spec["slides"]) == 4
    for slide in spec["slides"]:
        assert isinstance(slide["elements"], list)
        assert slide["elements"]