"""Tests for the Phase 12 export engine (backend)."""
from __future__ import annotations

import asyncio

from app.export.service import ExportService
from app.export.strategy import ExportFactory, ExportFormat
from app.generation.spec import PresentationSpec
from app.generation.spec_provider import OfflineSpecProvider


def _sample_spec() -> PresentationSpec:
    provider = OfflineSpecProvider()
    req = type(
        "R",
        (),
        {"prompt": "AI in healthcare", "slide_count": 5, "tone": "professional", "language": "en", "theme": "modern"},
    )()
    return asyncio.run(provider.generate_spec(req))


def _export(spec, fmt, theme_hint=None):
    return asyncio.run(ExportService().export(spec, fmt, theme_hint=theme_hint))


def test_factory_supports_all_formats():
    supported = {f.value for f in ExportFactory.supported()}
    assert supported == {"html", "pdf", "pptx"}


def test_html_export_returns_bytes():
    spec = _sample_spec()
    out = _export(spec, ExportFormat.HTML)
    assert out.media_type == "text/html"
    assert out.data.startswith(b"<!DOCTYPE html>")


def test_pdf_export_is_real_pdf():
    spec = _sample_spec()
    out = _export(spec, ExportFormat.PDF)
    assert out.media_type == "application/pdf"
    assert out.data[:4] == b"%PDF"


def test_pptx_export_is_valid_zip():
    spec = _sample_spec()
    out = _export(spec, ExportFormat.PPTX)
    assert out.media_type.endswith("presentationml.presentation")
    # A .pptx is a ZIP; the magic bytes are "PK".
    assert out.data[:2] == b"PK"
    assert len(out.data) > 1000


def test_pptx_contains_real_slide_count():
    spec = _sample_spec()
    assert len(spec.slides) == 5
