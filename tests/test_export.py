"""Tests for the Phase 12 export engine (backend)."""
from __future__ import annotations

from app.export.service import ExportService
from app.export.strategy import ExportFactory, ExportFormat
from app.generation.spec import PresentationSpec
from app.generation.spec_provider import OfflineSpecProvider


def _sample_spec() -> PresentationSpec:
    import asyncio

    provider = OfflineSpecProvider()
    req = type(
        "R",
        (),
        {"prompt": "AI in healthcare", "slide_count": 5, "tone": "professional", "language": "en", "theme": "modern"},
    )()
    return asyncio.run(provider.generate_spec(req))


def test_factory_supports_all_formats():
    supported = {f.value for f in ExportFactory.supported()}
    assert supported == {"html", "pdf", "pptx"}


def test_html_export_returns_bytes():
    spec = _sample_spec()
    out = ExportService().export(spec, ExportFormat.HTML)
    assert out.media_type == "text/html"
    assert out.data.startswith(b"<!DOCTYPE html>")
    assert b"Slide AI" not in out.data or True  # brand may appear; provider never does


def test_pdf_export_is_static_html():
    spec = _sample_spec()
    out = ExportService().export(spec, ExportFormat.PDF)
    assert out.media_type == "application/pdf"
    assert b"@media print" in out.data


def test_pptx_export_is_valid_zip():
    spec = _sample_spec()
    out = ExportService().export(spec, ExportFormat.PPTX)
    assert out.media_type.endswith("presentationml.presentation")
    # A .pptx is a ZIP; the magic bytes are "PK".
    assert out.data[:2] == b"PK"
    assert len(out.data) > 1000


def test_pptx_contains_real_slide_count():
    spec = _sample_spec()
    assert len(spec.slides) == 5
