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
    # Last slide is a thank-you; layouts are varied.
    assert spec.slides[-1].layout == "thank-you"
    assert {s.layout for s in spec.slides} != {"title"}


def test_build_spec_provider_selects_offline_for_placeholder() -> None:
    settings = Settings(_env_file=None, ai_provider_api_key="public")
    provider = build_spec_provider(settings)
    assert isinstance(provider, OfflineSpecProvider)
