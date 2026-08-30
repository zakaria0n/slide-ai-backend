"""Tests for the batch: element style, notes/deck-meta tools, geometry
diagnostics, MCP rename/duplicate/upload/async-jobs, generation quality
feedback and optimistic locking."""
from __future__ import annotations

import asyncio
import json
import time
from uuid import uuid4

from app.export.html_exporter import render_spec_html
from app.export.html_theme import tokens_for
from app.generation.spec import PresentationSpec
from app.generation.spec_provider import _spec_quality_feedback
from app.chat.schemas import SendChatRequest
from app.chat.tools import dispatch_tool


def _rpc(method: str, params: dict | None = None, msg_id: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}}


def _headers() -> dict:
    from tests.test_generation_routes import _auth, _token

    return _auth(_token("12345678-1234-1234-1234-123456789012"))


def _call(client, name: str, arguments: dict, msg_id: int = 5) -> dict:
    res = client.post(
        "/api/v1/mcp",
        json=_rpc("tools/call", {"name": name, "arguments": arguments}, msg_id),
        headers=_headers(),
    )
    assert res.status_code == 200, res.text
    return json.loads(res.json()["result"]["content"][0]["text"])


def _spec() -> PresentationSpec:
    return PresentationSpec.validate_spec({
        "meta": {"title": "T", "theme": "modern"},
        "slides": [{
            "layout": "title",
            "elements": [
                {"type": "title", "text": "Hello", "level": 1},
                {"type": "subtitle", "text": "Sub"},
            ],
        }],
    })


# --- element style + notes + deck meta ---------------------------------------


def test_update_element_style_and_merge() -> None:
    r1 = asyncio.run(dispatch_tool(
        "update_element",
        {"slide_index": 0, "element_index": 0, "style": {"color": "#ff0000", "align": "center"}, "animation_delay": 300},
        _spec(),
    ))
    assert r1.success, r1.summary
    el = r1.spec.slides[0].elements[0]
    assert el.style.color == "#ff0000" and el.style.align == "center"
    assert el.animation_delay == 300

    r2 = asyncio.run(dispatch_tool(
        "update_element",
        {"slide_index": 0, "element_index": 0, "style": {"rotation": 10}},
        r1.spec,
    ))
    assert r2.success
    el2 = r2.spec.slides[0].elements[0]
    assert el2.style.color == "#ff0000" and el2.style.rotation == 10


def test_update_element_rejects_bad_style_key() -> None:
    r = asyncio.run(dispatch_tool(
        "update_element",
        {"slide_index": 0, "element_index": 0, "style": {"not_a_key": 1}},
        _spec(),
    ))
    assert not r.success


def test_update_slide_notes() -> None:
    r = asyncio.run(dispatch_tool(
        "update_slide",
        {"slide_index": 0, "notes": "Speak slowly here"},
        _spec(),
    ))
    assert r.success
    assert r.spec.slides[0].notes == "Speak slowly here"


def test_update_deck_meta() -> None:
    r = asyncio.run(dispatch_tool(
        "update_deck_meta",
        {"title": "Renamed Deck", "theme": "dark", "language": "French"},
        _spec(),
    ))
    assert r.success
    assert r.spec.meta.title == "Renamed Deck"
    assert r.spec.meta.theme == "dark"
    assert r.spec.meta.language == "French"
    assert all(s.theme == "dark" for s in r.spec.slides)


# --- diagnostics validation ----------------------------------------------------


def test_diagnostics_validated() -> None:
    req = SendChatRequest(message="fix", diagnostics=[
        {"element_index": 2, "problem": "overflows-slide", "detail": "bottom 104%"},
        {"element_index": -5, "problem": "junk"},  # dropped
        {"element_index": 3, "problem": "elements-overlap", "detail": "with 1"},
    ])
    assert req.diagnostics is not None
    assert len(req.diagnostics) == 2
    assert {d["problem"] for d in req.diagnostics} == {"overflows-slide", "elements-overlap"}


# --- MCP: rename / duplicate / upload / async jobs ------------------------------


def test_mcp_rename_presentation(client) -> None:
    created = _call(client, "create_presentation", {"title": "Old Name"})
    out = _call(client, "rename_presentation", {"presentation_id": created["id"], "title": "New Name"})
    assert out["title"] == "New Name"


def test_mcp_duplicate_presentation(client) -> None:
    created = _call(client, "create_presentation", {"title": "Original"})
    out = _call(client, "duplicate_presentation", {"presentation_id": created["id"]})
    assert out["id"] != created["id"]
    assert out["title"].startswith("Copy of")


def test_mcp_upload_image(client) -> None:
    # 1x1 red PNG
    png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    out = _call(client, "upload_image", {"filename": "dot.png", "file_base64": f"data:image/png;base64,{png_b64}"})
    assert "url" in out, out
    assert out["filename"] == "dot.png"


def test_mcp_upload_image_rejects_bad_base64(client) -> None:
    out = _call(client, "upload_image", {"filename": "x.png", "file_base64": "!!!not-base64!!!"})
    assert "error" in out


def test_mcp_generate_async_mode(client) -> None:
    job = _call(client, "generate_presentation", {
        "prompt": "Async test deck about railways",
        "slide_count": 2,
        "async_mode": True,
    })
    assert job["status"] == "running"
    assert "job_id" in job

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        status = _call(client, "get_generation_job", {"job_id": job["job_id"]})
        if status["status"] != "running":
            break
        time.sleep(0.2)
    assert status["status"] == "ready", status
    assert status.get("presentation_id")

    spec_text = _call(client, "get_presentation", {"presentation_id": status["presentation_id"]})
    assert "railways" in json.dumps(spec_text).lower()


def test_mcp_get_generation_job_unknown(client) -> None:
    out = _call(client, "get_generation_job", {"job_id": "nope"})
    assert "error" in out


# --- quality feedback ------------------------------------------------------------


def test_quality_feedback_flags_underfilled_slides() -> None:
    bad = PresentationSpec.validate_spec({
        "meta": {"title": "T"},
        "slides": [{
            "layout": "statistics",
            "elements": [
                {"type": "title", "text": "Overview", "level": 2},
                {"type": "statistics", "items": [{"value": "1", "label": "x"}]},
            ],
        }],
    })
    issues = _spec_quality_feedback(bad)
    assert any("statistics" in i for i in issues)
    assert any("generic" in i for i in issues)

    good = PresentationSpec.validate_spec({
        "meta": {"title": "T"},
        "slides": [{
            "layout": "statistics",
            "elements": [
                {"type": "title", "text": "The Market Window", "level": 2},
                {"type": "statistics", "items": [
                    {"value": "1", "label": "a"}, {"value": "2", "label": "b"}, {"value": "3", "label": "c"},
                ]},
            ],
        }],
    })
    assert _spec_quality_feedback(good) == []


# --- optimistic locking ------------------------------------------------------------


def test_spec_put_optimistic_lock(client) -> None:
    from tests.test_generation_routes import _auth, _token

    headers = _auth(_token("32345678-1234-1234-1234-123456789012"))
    created = client.post(
        "/api/v1/presentations/generate",
        json={"prompt": "Locking deck", "slide_count": 2},
        headers=headers,
    ).json()
    pid = created["id"]

    row = client.get(f"/api/v1/presentations/{pid}", headers=headers).json()
    assert row["updated_at"]

    spec = client.get(f"/api/v1/presentations/{pid}/spec", headers=headers).json()

    # Stale timestamp → 409.
    stale = client.put(
        f"/api/v1/presentations/{pid}/spec?expected_updated_at=2000-01-01T00%3A00%3A00%2B00%3A00",
        json=spec, headers=headers,
    )
    assert stale.status_code == 409, stale.text

    # Current timestamp → 200 and the fresh updated_at comes back.
    ok = client.put(
        f"/api/v1/presentations/{pid}/spec?expected_updated_at={row['updated_at']}",
        json=spec, headers=headers,
    )
    assert ok.status_code == 200, ok.text
    assert ok.headers.get("X-Updated-At")


# --- export parity -------------------------------------------------------------------


def test_export_positions_and_custom_animations() -> None:
    spec = PresentationSpec.validate_spec({
        "meta": {"title": "Export", "theme": "dark", "customAnimations": [{
            "name": "riseGlow",
            "keyframes": "@keyframes whatever { 0% { opacity: 0 } 100% { opacity: 1 } }",
            "duration": 700, "easing": "cubic-bezier(0.16,1,0.3,1)", "delay": 200, "loop": 2,
        }]},
        "slides": [{
            "layout": "title",
            "elements": [{
                "type": "title", "text": "Positioned", "level": 1,
                "x": 10, "y": 20, "w": 50,
                "animation": "riseGlow", "animation_delay": 250,
                "style": {"color": "#ff8800", "font_size": "40px", "rotation": -5},
            }],
        }],
    })
    html = render_spec_html(spec, tokens_for("dark"))
    assert "position:absolute;left:10%;top:20%;width:50%" in html
    assert "@keyframes riseGlow" in html
    assert "animation:riseGlow 700ms" in html
    assert "0.45s" in html  # 200ms def delay + 250ms element delay
    assert "color:#ff8800" in html and "rotate(-5deg)" in html  # :g format
