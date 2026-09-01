"""ONLINE integration tests — real AI provider (opencode zen, public key).

These tests hit the REAL provider: they are slower (10-60s per generation)
and depend on free-tier availability, so they are opt-in:

    SLIDE_AI_TESTS_ONLINE=1 pytest tests/test_online_provider.py -m online -v

(or run the whole suite online: SLIDE_AI_TESTS_ONLINE=1 pytest)
"""
from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.online,
    pytest.mark.skipif(
        os.environ.get("SLIDE_AI_TESTS_ONLINE") != "1",
        reason="online provider tests — run with SLIDE_AI_TESTS_ONLINE=1",
    ),
]


def _headers(uid: str) -> dict:
    from tests.test_generation_routes import _auth, _token

    return _auth(_token(uid))


def test_online_generate_real_provider(client) -> None:
    """Generation through the REAL provider returns a real structured deck."""
    headers = _headers("62345678-1234-1234-1234-123456789012")

    res = client.post(
        "/api/v1/presentations/generate",
        json={
            "prompt": "Online integration test: lighthouse engineering",
            "slide_count": 3,
            "language": "English",
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    pid = body["id"]
    assert body["slide_count"] >= 1

    spec = client.get(f"/api/v1/presentations/{pid}/spec", headers=headers).json()
    assert spec["meta"]["title"]
    assert len(spec["slides"]) >= 1
    # Real model output: titles are non-generic real text.
    texts = " ".join(
        str(e.get("text", "")) for s in spec["slides"] for e in s["elements"]
    )
    assert len(texts) > 40


def test_online_ai_edit_real_provider(client) -> None:
    """AI edit through the REAL provider modifies the deck."""
    headers = _headers("62345678-1234-1234-1234-123456789012")

    created = client.post(
        "/api/v1/presentations/generate",
        json={"prompt": "AI edit online test: mountain railways", "slide_count": 2},
        headers=headers,
    ).json()

    res = client.post(
        f"/api/v1/presentations/{created['id']}/edit",
        json={
            "instruction": "Rewrite the first slide title to mention alpine engineering",
            "target_indexes": [0],
        },
        headers=headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["summary"]
    assert 0 in body["changed_indexes"]


def test_online_mcp_create_and_screenshot(client) -> None:
    """MCP: create a deck via tools, then screenshot it with Chromium."""
    headers = _headers("62345678-1234-1234-1234-123456789012")

    def call(name: str, arguments: dict, msg_id: int = 1) -> dict:
        res = client.post(
            "/api/v1/mcp",
            json={
                "jsonrpc": "2.0",
                "id": msg_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
            headers=headers,
        )
        assert res.status_code == 200, res.text
        return json.loads(res.json()["result"]["content"][0]["text"])

    created = call("create_presentation", {"title": "Online MCP deck"}, 1)
    pid = created["id"]

    call(
        "update_slide",
        {"presentation_id": pid, "slide_index": 0, "title": "Visible title"},
        2,
    )

    shot = call(
        "get_slide_screenshot",
        {"presentation_id": pid, "slide_index": 0},
        3,
    )
    assert "error" not in shot, shot
