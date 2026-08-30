"""MCP slide screenshot tool — server-side Chromium render returned as image."""
from __future__ import annotations

import json


def _headers(uid: str) -> dict:
    from tests.test_generation_routes import _auth, _token

    return _auth(_token(uid))


def test_mcp_get_slide_screenshot_returns_image(client) -> None:
    headers = _headers("22345678-1234-1234-1234-123456789012")

    created = client.post(
        "/api/v1/presentations/generate",
        json={"prompt": "Screenshot test deck about lighthouses", "slide_count": 2},
        headers=headers,
    ).json()
    pid = created["id"]

    res = client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "get_slide_screenshot",
                "arguments": {"presentation_id": pid, "slide_index": 0},
            },
        },
        headers=headers,
    )
    assert res.status_code == 200, res.text
    content = res.json()["result"]["content"]

    images = [c for c in content if c.get("type") == "image"]
    assert len(images) == 1
    assert images[0]["mimeType"] == "image/png"
    # A real render is a substantial PNG.
    assert len(images[0]["data"]) > 1000

    text = next(c for c in content if c.get("type") == "text")
    assert "slide 1/2" in text["text"].lower() or "screenshot" in text["text"].lower()


def test_mcp_screenshot_invalid_index(client) -> None:
    created = client.post(
        "/api/v1/presentations/generate",
        json={"prompt": "Index check deck", "slide_count": 1},
        headers=_headers("22345678-1234-1234-1234-123456789012"),
    ).json()
    pid = created["id"]

    res = client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "get_slide_screenshot",
                "arguments": {"presentation_id": pid, "slide_index": 99},
            },
        },
        headers=_headers("22345678-1234-1234-1234-123456789012"),
    )
    assert res.status_code == 200
    assert "error" in res.json()["result"]["content"][0]["text"]
