"""Tests for the model catalog and the new AI animation/custom tools."""
from __future__ import annotations

import asyncio

import pytest

from app.core import model_catalog as mc
from app.core.config import Settings
from app.core.exceptions import ValidationError
from app.chat.tools import dispatch_tool
from app.generation.spec import PresentationSpec


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)


@pytest.fixture
def cached_ids(monkeypatch):
    """Seed the model cache so catalog lookups never hit the network."""
    monkeypatch.setattr(mc, "_cache", {"ids": ["alpha", "beta", "hy3-free"], "fetched_at": mc.time.monotonic()})


# --- resolve_model -----------------------------------------------------------


async def test_resolve_model_default_when_none(settings, cached_ids) -> None:
    assert await mc.resolve_model(settings, None) == settings.ai_provider_default_model
    assert await mc.resolve_model(settings, "") == settings.ai_provider_default_model


async def test_resolve_model_accepts_catalog_id(settings, cached_ids) -> None:
    assert await mc.resolve_model(settings, "hy3-free") == "hy3-free"


async def test_resolve_model_rejects_unknown(settings, cached_ids) -> None:
    with pytest.raises(ValidationError):
        await mc.resolve_model(settings, "not-a-real-model")


# --- GET /models endpoint ----------------------------------------------------


async def test_list_model_ids_hides_paid_models(settings, monkeypatch) -> None:
    """Free key: only big-pickle + *-free models are exposed."""
    monkeypatch.setattr(
        mc, "_cache",
        {"ids": ["claude-opus-5", "big-pickle", "hy3-free", "gpt-5"], "fetched_at": mc.time.monotonic()},
    )
    ids = await mc.list_model_ids(settings)
    assert "claude-opus-5" not in ids and "gpt-5" not in ids
    assert "big-pickle" in ids and "hy3-free" in ids


async def test_list_model_ids_keeps_all_when_paid_allowed(settings, monkeypatch) -> None:
    paid = Settings(_env_file=None, ai_provider_api_key="real-key", allow_paid_models=True)
    monkeypatch.setattr(
        mc, "_cache",
        {"ids": ["claude-opus-5", "hy3-free"], "fetched_at": mc.time.monotonic()},
    )
    ids = await mc.list_model_ids(paid)
    assert "claude-opus-5" in ids


def test_models_endpoint_requires_auth(client) -> None:
    res = client.get("/api/v1/models")
    assert res.status_code == 401


def test_models_endpoint_lists_catalog(client, monkeypatch) -> None:
    monkeypatch.setattr(
        mc, "_cache", {"ids": ["hy3-free", "nemotron-3-ultra-free"], "fetched_at": mc.time.monotonic()}
    )
    uid = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    from tests.test_generation_routes import _auth, _token  # reuse token helpers

    res = client.get("/api/v1/models", headers=_auth(_token(uid)))
    assert res.status_code == 200
    body = res.json()
    assert body["provider"] == "Slide AI"
    assert body["default"] == "nemotron-3-ultra-free"
    assert {m["id"] for m in body["models"]} >= {"hy3-free", "nemotron-3-ultra-free"}


# --- animation / custom tools -------------------------------------------------


def _spec() -> PresentationSpec:
    return PresentationSpec.validate_spec(
        {
            "meta": {"title": "T", "theme": "modern"},
            "slides": [
                {
                    "layout": "title",
                    "elements": [
                        {"type": "title", "text": "Aurora Launch", "level": 1},
                        {"type": "subtitle", "text": "Real-time rendering"},
                    ],
                }
            ],
        }
    )


def test_define_and_apply_custom_animation() -> None:
    spec = _spec()
    r1 = asyncio.run(
        dispatch_tool(
            "define_custom_animation",
            {
                "name": "riseGlow",
                "keyframes": "@keyframes riseGlow { 0% { opacity: 0; transform: translateY(36px) } 100% { opacity: 1; transform: none } }",
                "duration": 700,
                "easing": "cubic-bezier(0.16, 1, 0.3, 1)",
            },
            spec,
        )
    )
    assert r1.success
    r2 = asyncio.run(
        dispatch_tool("set_element_animation", {"slide_index": 0, "animation": "riseGlow", "element_text": "Aurora"}, r1.spec)
    )
    assert r2.success
    assert r2.spec.slides[0].elements[0].animation == "riseGlow"


def test_define_custom_animation_rejects_forbidden_css() -> None:
    r = asyncio.run(
        dispatch_tool(
            "define_custom_animation",
            {"name": "bad", "keyframes": "@keyframes bad { 0% { background: url(https://evil) } }"},
            _spec(),
        )
    )
    assert not r.success


def test_set_element_animation_rejects_unknown_name() -> None:
    r = asyncio.run(
        dispatch_tool("set_element_animation", {"slide_index": 0, "animation": "nope"}, _spec())
    )
    assert not r.success


def test_set_element_animation_builtin_and_remove() -> None:
    r1 = asyncio.run(dispatch_tool("set_element_animation", {"slide_index": 0, "animation": "blur", "element_index": 1}, _spec()))
    assert r1.success
    r2 = asyncio.run(dispatch_tool("set_element_animation", {"slide_index": 0, "animation": "none", "element_index": 1}, r1.spec))
    assert r2.success
    assert r2.spec.slides[0].elements[1].animation is None


def test_add_element_with_free_placement() -> None:
    r = asyncio.run(
        dispatch_tool(
            "add_element",
            {"slide_index": 0, "element": {"type": "paragraph", "text": "note", "x": 55, "y": 70, "w": 35}},
            _spec(),
        )
    )
    assert r.success
    added = r.spec.slides[0].elements[-1]
    assert (added.x, added.y, added.w) == (55, 70, 35)


def test_update_custom_slide() -> None:
    r = asyncio.run(
        dispatch_tool(
            "update_custom_slide",
            {"slide_index": 0, "html": "<h1>hi</h1>", "css": "h1{color:red}"},
            _spec(),
        )
    )
    assert r.success
    slide = r.spec.slides[0]
    assert slide.layout == "custom"
    assert slide.code is not None and slide.code.html == "<h1>hi</h1>"


# --- element-level control ----------------------------------------------------


def test_update_element_patches_text_and_animation() -> None:
    r1 = asyncio.run(
        dispatch_tool("define_custom_animation", {"name": "glow", "keyframes": "@keyframes glow { 0% { opacity: 0 } 100% { opacity: 1 } }"}, _spec())
    )
    r2 = asyncio.run(
        dispatch_tool(
            "update_element",
            {"slide_index": 0, "element_text": "Aurora", "text": "New headline", "animation": "glow", "level": 2},
            r1.spec,
        )
    )
    assert r2.success, r2.summary
    el = r2.spec.slides[0].elements[0]
    assert el.text == "New headline"
    assert el.level == 2
    assert el.animation == "glow"
    # untouched element preserved
    assert r2.spec.slides[0].elements[1].text == "Real-time rendering"


def test_update_element_sets_free_position() -> None:
    r = asyncio.run(
        dispatch_tool(
            "update_element",
            {"slide_index": 0, "element_index": 1, "x": 55, "y": 70, "w": 35},
            _spec(),
        )
    )
    assert r.success, r.summary
    el = r.spec.slides[0].elements[1]
    assert (el.x, el.y, el.w) == (55, 70, 35)


def test_update_element_removes_animation_with_none() -> None:
    r1 = asyncio.run(dispatch_tool("set_element_animation", {"slide_index": 0, "animation": "fade", "element_index": 0}, _spec()))
    r2 = asyncio.run(
        dispatch_tool("update_element", {"slide_index": 0, "element_index": 0, "animation": "none"}, r1.spec)
    )
    assert r2.success
    assert r2.spec.slides[0].elements[0].animation is None


def test_update_element_rejects_invalid_shape() -> None:
    # items is not valid on a title element — must be rejected, not persisted
    r = asyncio.run(
        dispatch_tool(
            "update_element",
            {"slide_index": 0, "element_index": 0, "items": ["a", "b"]},
            _spec(),
        )
    )
    assert not r.success


def test_update_element_ambiguous_text_fails() -> None:
    from copy import deepcopy

    spec = deepcopy(_spec())
    spec.slides[0].elements.append(type(spec.slides[0].elements[0])(text="Aurora Returns", level=2))
    r = asyncio.run(
        dispatch_tool("update_element", {"slide_index": 0, "element_text": "Aurora", "text": "x"}, spec)
    )
    assert not r.success
    assert "matched 2" in r.summary


def test_move_element_reorders() -> None:
    r = asyncio.run(
        dispatch_tool(
            "move_element",
            {"slide_index": 0, "element_index": 0, "to_index": 1},
            _spec(),
        )
    )
    assert r.success
    els = r.spec.slides[0].elements
    assert els[1].type == "title"
    assert els[0].type == "subtitle"
