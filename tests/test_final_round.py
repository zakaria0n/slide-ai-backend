"""Tests for the final round: image URL resolution, versioning throttle,
import, search, brand kit, diagnostics (-1), language enforcement."""
from __future__ import annotations

import json
import time

from app.chat.context import build_system_message
from app.chat.schemas import SendChatRequest
from app.generation.spec import PresentationSpec


def _headers(uid: str = "12345678-1234-1234-1234-123456789012") -> dict:
    from tests.test_generation_routes import _auth, _token

    return _auth(_token(uid))


# --- diagnostics: slide-level index allowed -----------------------------------


def test_diagnostics_allow_slide_level_index() -> None:
    req = SendChatRequest(message="fix", diagnostics=[
        {"element_index": -1, "problem": "content-overflows-layout", "detail": "~80px"},
    ])
    assert req.diagnostics == [
        {"element_index": -1, "problem": "content-overflows-layout", "detail": "~80px"},
    ]


# --- language enforcement ------------------------------------------------------


def test_chat_prompt_enforces_deck_language() -> None:
    spec = PresentationSpec.validate_spec({
        "meta": {"title": "T", "language": "French"},
        "slides": [{"layout": "title", "elements": [{"type": "title", "text": "Bonjour", "level": 1}]}],
    })
    msg = build_system_message(spec, 0)
    assert "French" in msg
    assert "language" in msg.lower()


# --- import (markdown → offline provider deck) ---------------------------------


def test_import_markdown_creates_deck(client) -> None:
    headers = _headers("92345678-1234-1234-1234-123456789012")
    res = client.post(
        "/api/v1/presentations/import",
        json={
            "source": "markdown",
            "content": "# Coral Reefs\n\nCoral reefs host 25% of marine species. "
                       "Bleaching threatens 70% of reefs by 2050. Conservation efforts "
                       "focus on marine protected areas and sustainable tourism. " * 6,
            "slide_count": 4,
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["slide_count"] == 4

    spec = client.get(f"/api/v1/presentations/{body['id']}/spec", headers=headers).json()
    assert spec["slides"]


def test_import_rejects_empty_markdown(client) -> None:
    res = client.post(
        "/api/v1/presentations/import",
        json={"source": "markdown", "content": "   "},
        headers=_headers("92345678-1234-1234-1234-123456789012"),
    )
    assert res.status_code in (400, 422)


def test_import_rejects_private_url(client) -> None:
    res = client.post(
        "/api/v1/presentations/import",
        json={"source": "url", "url": "http://localhost:8000/secret"},
        headers=_headers("92345678-1234-1234-1234-123456789012"),
    )
    assert res.status_code in (400, 422)


# --- full-deck search ------------------------------------------------------------


def test_search_finds_deck_by_content(client) -> None:
    uid = "82345678-1234-1234-1234-123456789012"
    headers = _headers(uid)
    created = client.post(
        "/api/v1/presentations/generate",
        json={"prompt": "Quantum knitting patterns", "slide_count": 2},
        headers=headers,
    ).json()

    res = client.get("/api/v1/presentations/search?q=quantum knitting", headers=headers)
    assert res.status_code == 200
    ids = [p["id"] for p in res.json()["items"]]
    assert created["id"] in ids


# --- brand kit ---------------------------------------------------------------------


def test_brand_kit_get_put_get(client) -> None:
    uid = "72345678-1234-1234-1234-123456789012"
    headers = _headers(uid)

    empty = client.get("/api/v1/brand-kit", headers=headers)
    assert empty.status_code == 200
    assert empty.json()["color_primary"] is None

    put = client.put(
        "/api/v1/brand-kit",
        json={"color_primary": "#0ea5e9", "color_secondary": "#facc15",
              "font_heading": "'Syne', sans-serif"},
        headers=headers,
    )
    assert put.status_code == 200, put.text
    assert put.json()["color_primary"] == "#0ea5e9"

    again = client.get("/api/v1/brand-kit", headers=headers)
    assert again.json()["color_secondary"] == "#facc15"
    assert again.json()["font_heading"] == "'Syne', sans-serif"


def test_brand_kit_requires_auth(client) -> None:
    assert client.get("/api/v1/brand-kit").status_code == 401


# --- image URL resolution on export ------------------------------------------------


def test_export_resolves_file_id_urls(client) -> None:
    headers = _headers("62345678-1234-1234-1234-123456789012")

    # Upload an image via MCP → file_id + fresh URL.
    rpc = {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {
            "name": "upload_image",
            "arguments": {
                "filename": "dot.png",
                "file_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
            },
        },
    }
    res = client.post("/api/v1/mcp", json=rpc, headers=headers)
    uploaded = json.loads(res.json()["result"]["content"][0]["text"])
    file_id = uploaded["file_id"]

    # Create a deck and point an image element at the file_id with a STALE src.
    created = client.post(
        "/api/v1/presentations/generate",
        json={"prompt": "Image resolution deck", "slide_count": 2},
        headers=headers,
    ).json()
    pid = created["id"]
    spec = client.get(f"/api/v1/presentations/{pid}/spec", headers=headers).json()
    spec["slides"][0]["elements"].append({
        "type": "image", "src": "https://expired.example/old.png", "file_id": file_id, "alt": "dot",
    })
    put = client.put(f"/api/v1/presentations/{pid}/spec", json=spec, headers=headers)
    assert put.status_code == 200, put.text

    exported = client.get(f"/api/v1/presentations/{pid}/export?format=html", headers=headers)
    assert exported.status_code == 200
    html = exported.text
    assert "https://expired.example/old.png" not in html  # stale URL replaced


# --- versioning throttle ------------------------------------------------------------


def test_manual_edit_snapshots_throttled(client) -> None:
    uid = "52345678-1234-1234-1234-123456789012"
    headers = _headers(uid)
    created = client.post(
        "/api/v1/presentations/generate",
        json={"prompt": "Throttle deck", "slide_count": 2},
        headers=headers,
    ).json()
    pid = created["id"]
    spec = client.get(f"/api/v1/presentations/{pid}/spec", headers=headers).json()

    def put_new_spec():
        new_spec = json.loads(json.dumps(spec))
        new_spec["slides"][0]["elements"][0]["text"] = f"Edited at {time.monotonic()}"
        return client.put(f"/api/v1/presentations/{pid}/spec", json=new_spec, headers=headers)

    assert put_new_spec().status_code == 200  # first manual save → snapshot
    v1 = client.get(f"/api/v1/presentations/{pid}/versions", headers=headers).json()["total"]
    assert put_new_spec().status_code == 200  # immediate second save → throttled
    v2 = client.get(f"/api/v1/presentations/{pid}/versions", headers=headers).json()["total"]
    assert v2 == v1
