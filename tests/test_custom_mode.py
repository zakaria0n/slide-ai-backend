"""Custom creative mode: template opt-out + quality enforcement."""
from __future__ import annotations

from app.generation.spec_provider import _spec_quality_feedback
from app.generation.spec import PresentationSpec


def _spec() -> PresentationSpec:
    return PresentationSpec.validate_spec({
        "meta": {"title": "T", "theme": "custom"},
        "slides": [
            {"layout": "hero", "elements": [{"type": "title", "text": "A", "level": 1}]},
            {"layout": "hero", "elements": [{"type": "title", "text": "B", "level": 1}]},
            {"layout": "hero", "elements": [{"type": "title", "text": "C", "level": 1}]},
        ],
    })


def test_custom_mode_flags_zero_custom_slides() -> None:
    issues = _spec_quality_feedback(_spec())
    assert any("ZERO custom-coded" in i for i in issues)


def test_custom_mode_flags_missing_animations() -> None:
    issues = _spec_quality_feedback(_spec())
    assert any("custom keyframe" in i for i in issues)


def test_custom_mode_compliant_deck_is_clean() -> None:
    spec = PresentationSpec.validate_spec({
        "meta": {
            "title": "T", "theme": "custom",
            "customAnimations": [
                {"name": "a", "keyframes": "@keyframes a { 0% {opacity:0} 100% {opacity:1} }", "duration": 500},
                {"name": "b", "keyframes": "@keyframes b { 0% {opacity:0} 100% {opacity:1} }", "duration": 500},
            ],
        },
        "slides": [
            {"layout": "custom", "code": {"html": "<div>x</div>"}},
            {"layout": "custom", "code": {"html": "<div>y</div>"}},
            {"layout": "title", "elements": [{"type": "title", "text": "Real title", "level": 1}]},
        ],
    })
    assert _spec_quality_feedback(spec) == []


def test_generate_service_selects_template_except_custom(client) -> None:
    """Offline provider: custom theme deck keeps meta.theme and the service
    skips the auto-template only in custom mode."""
    headers = _headers("41345678-1234-1234-1234-123456789012")

    custom = client.post(
        "/api/v1/presentations/generate",
        json={"prompt": "Custom creative deck", "slide_count": 2, "theme": "custom"},
        headers=headers,
    )
    assert custom.status_code == 201
    spec = client.get(f"/api/v1/presentations/{custom.json()['id']}/spec", headers=headers).json()
    assert spec["meta"]["theme"] == "custom"

    structured = client.post(
        "/api/v1/presentations/generate",
        json={"prompt": "Structured deck", "slide_count": 2, "theme": "modern"},
        headers=headers,
    )
    assert structured.status_code == 201
    spec2 = client.get(f"/api/v1/presentations/{structured.json()['id']}/spec", headers=headers).json()
    assert spec2["meta"]["theme"] == "modern"


def _headers(uid: str) -> dict:
    from tests.test_generation_routes import _auth, _token

    return _auth(_token(uid))
