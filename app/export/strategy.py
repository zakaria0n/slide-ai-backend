"""Phase 12 — Export Engine (backend).

A small Strategy/Factory implementation that turns a stored
``PresentationSpec`` into a downloadable artifact. Three formats ship today:

- ``html``  — a fully self-contained HTML file (keeps the Slide AI
  animations, themes and typography). This is the primary product.
- ``pdf``   — print-optimized HTML (static, animation-free) intended to be
  printed / "Save as PDF" from the browser, preserving layout and theme.
- ``pptx``  — a native PowerPoint file with *content only* (no animations),
  one slide per spec slide. Generated with python-pptx.

The renderer-agnostic design (Strategy + Factory + Provider) makes adding
new formats a single new ``ExportStrategy`` subclass plus an enum entry.
"""
from __future__ import annotations

import io
from abc import ABC, abstractmethod
from enum import Enum
from typing import Protocol

from app.generation.spec import PresentationSpec


class ExportFormat(str, Enum):
    HTML = "html"
    PDF = "pdf"
    PPTX = "pptx"


class ExportedFile:
    """The result of an export: raw bytes + how to serve it."""

    def __init__(self, data: bytes, media_type: str, filename: str) -> None:
        self.data = data
        self.media_type = media_type
        self.filename = filename


class ExportStrategy(ABC):
    """One export format."""

    format: ExportFormat

    @abstractmethod
    def export(self, spec: PresentationSpec, theme_hint: str | None = None) -> ExportedFile:
        ...


class ExportFactory:
    """Builds the right strategy for a requested format."""

    _registry: dict[ExportFormat, type[ExportStrategy]] = {}

    @classmethod
    def register(cls, fmt: ExportFormat, strategy: type[ExportStrategy]) -> None:
        cls._registry[fmt] = strategy

    @classmethod
    def build(cls, fmt: ExportFormat) -> ExportStrategy:
        if fmt not in cls._registry:
            raise ValueError(f"Unsupported export format: {fmt}")
        return cls._registry[fmt]()

    @classmethod
    def supported(cls) -> list[ExportFormat]:
        return list(cls._registry.keys())


# Protocol used by strategies that need to resolve a theme palette.
class ThemePaletteProvider(Protocol):
    def tokens_for(self, theme_name: str | None) -> "ThemeTokens": ...
