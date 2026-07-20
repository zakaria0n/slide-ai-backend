"""Export service + provider wiring.

Builds the appropriate ``ExportStrategy`` via the ``ExportFactory`` and
runs it against a stored ``PresentationSpec``. Strategies are registered
once at import time so adding a format is a single registration line.
"""
from __future__ import annotations

from app.export.html_exporter import HtmlExportStrategy, PdfExportStrategy
from app.export.pptx_exporter import PptxExportStrategy
from app.export.strategy import ExportFactory, ExportFormat, ExportedFile
from app.generation.spec import PresentationSpec


def _register() -> None:
    ExportFactory.register(ExportFormat.HTML, HtmlExportStrategy)
    ExportFactory.register(ExportFormat.PDF, PdfExportStrategy)
    ExportFactory.register(ExportFormat.PPTX, PptxExportStrategy)


_register()


class ExportService:
    """Runs an export for a stored spec."""

    def export(self, spec: PresentationSpec, fmt: ExportFormat, theme_hint: str | None = None) -> ExportedFile:
        strategy = ExportFactory.build(fmt)
        return strategy.export(spec, theme_hint=theme_hint)


def build_export_service() -> ExportService:
    return ExportService()
