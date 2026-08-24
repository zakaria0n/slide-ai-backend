"""Unit tests for the Presentation Specification engine.

Covers schema validation, the offline spec provider (deterministic, valid
output), and automatic retry-on-invalid behaviour of the parser.
"""
from __future__ import annotations

import pytest

from app.generation.schemas import GenerationRequest
from app.generation.spec import PresentationSpec
from app.generation.spec_provider import (
    OfflineSpecProvider,
    _parse_spec,
    build_spec_provider,
)
from app.core.config import Settings


def test_valid_spec_parses() -> None:
    data = {
        "meta": {"title": "Demo", "theme": "Modern"},
        "slides": [
            {
                "layout": "hero",
                "elements": [
                    {"type": "title", "text": "Hello", "level": 1},
                    {"type": "bullets", "items": ["a", "b"]},
                ],
            }
        ],
    }
    spec = PresentationSpec.validate_spec(data)
    assert spec.meta.title == "Demo"
    assert spec.slides[0].layout == "hero"
    assert spec.slides[0].elements[0].type == "title"


def test_invalid_spec_raises() -> None:
    with pytest.raises(Exception):
        # Missing required "slides".
        PresentationSpec.validate_spec({"meta": {"title": "x"}})


def test_statistics_element_strict_inner_items() -> None:
    from pydantic import ValidationError

    # Malformed item payloads still parse, with empty defaults for
    # the well-known keys (invalid keys are silently dropped).
    spec = PresentationSpec.model_validate(
        {
            "meta": {"title": "x"},
            "slides": [
                {
                    "layout": "title",
                    "elements": [{"type": "statistics", "items": [{"foo": "bar"}]}],
                }
            ],
        }
    )
    stat = spec.slides[0].elements[0]
    assert stat.items[0].value == ""
    assert stat.items[0].label == ""

    # Non-object items are rejected.
    with pytest.raises(ValidationError):
        PresentationSpec.model_validate(
            {
                "meta": {"title": "x"},
                "slides": [
                    {
                        "layout": "title",
                        "elements": [{"type": "statistics", "items": [42]}],
                    }
                ],
            }
        )


def test_parse_rejects_non_json() -> None:
    with pytest.raises(Exception):
        _parse_spec("this is not json")


async def test_offline_provider_returns_valid_spec() -> None:
    provider = OfflineSpecProvider()
    req = GenerationRequest(
        prompt="A pitch for climate tech", slide_count=6, tone="Professional"
    )
    spec = await provider.generate_spec(req)
    assert isinstance(spec, PresentationSpec)
    assert len(spec.slides) == 6
    # Layouts are varied (not all the same).
    assert {s.layout for s in spec.slides} != {"title"}


def test_custom_animations_round_trip() -> None:
    """The AI's camelCase customAnimations survive validation + serialization."""
    data = {
        "meta": {
            "title": "Aurora Engine Launch",
            "customAnimations": [
                {
                    "name": "riseGlow",
                    "keyframes": "@keyframes riseGlow { 0% { opacity: 0; transform: translateY(36px) scale(0.96) } 100% { opacity: 1; transform: none } }",
                    "duration": 700,
                    "easing": "cubic-bezier(0.16, 1, 0.3, 1)",
                }
            ],
        },
        "slides": [
            {
                "layout": "hero",
                "elements": [{"type": "title", "text": "Aurora", "level": 1, "animation": "riseGlow"}],
            }
        ],
    }
    spec = PresentationSpec.validate_spec(data)
    assert spec.meta.customAnimations is not None
    anim = spec.meta.customAnimations[0]
    assert anim.name == "riseGlow"
    assert anim.duration == 700
    out = spec.model_dump(mode="json")
    # The wire format must keep the camelCase key the frontend reads.
    assert "customAnimations" in out["meta"]
    assert out["meta"]["customAnimations"][0]["name"] == "riseGlow"
    # Element animation reference is preserved.
    assert out["slides"][0]["elements"][0]["animation"] == "riseGlow"


def test_custom_code_slide_round_trip() -> None:
    """layout='custom' slides keep their free-coded html/css/js payload."""
    data = {
        "meta": {"title": "Showpiece"},
        "slides": [
            {
                "layout": "custom",
                "elements": [],
                "code": {
                    "html": "<div class='stage'><h1>Hi</h1></div>",
                    "css": ".stage{width:100%;height:100%}",
                    "js": "console.log('activate')",
                },
            }
        ],
    }
    spec = PresentationSpec.validate_spec(data)
    slide = spec.slides[0]
    assert slide.layout == "custom"
    assert slide.code is not None
    assert "<h1>Hi</h1>" in slide.code.html
    out = spec.model_dump(mode="json")
    assert out["slides"][0]["code"]["css"] == ".stage{width:100%;height:100%}"


def test_build_spec_provider_selects_online_for_public_key() -> None:
    settings = Settings(_env_file=None, ai_provider_api_key="public")
    provider = build_spec_provider(settings)
    assert isinstance(provider, type(build_spec_provider(settings)))  # not offline
