"""Presentation Specification schema (the Slide AI spec engine).

The AI provider returns a *structured specification* — never raw HTML. The
backend validates it and stores it; the frontend renderer (Phase 8)
consumes it element-by-element.

A :class:`PresentationSpec` is:

    Presentation
      - meta (title, theme, background, ...)
      - slides[]  (each a typed layout with a list of elements)

Every slide carries a ``layout`` (which renderer component to use) and a
list of :class:`Element` values. Elements are a discriminated union on the
``type`` field so validation is strict and extensible.

The provider is always "Slide AI" to the outside world; the concrete model
name is allowed to appear (per project rules) but the provider identity is
never exposed.
"""
from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel, Field, ValidationError

# --- Element union ---------------------------------------------------------

LayoutName = Literal[
    "hero",
    "title",
    "agenda",
    "section",
    "timeline",
    "comparison",
    "cards",
    "statistics",
    "pricing",
    "gallery",
    "process",
    "flow",
    "roadmap",
    "team",
    "quote",
    "swot",
    "table",
    "chart",
    "image-left",
    "image-right",
    "cta",
    "conclusion",
    "thank-you",
]

ElementType = Literal[
    "title",
    "subtitle",
    "paragraph",
    "bullets",
    "image",
    "cards",
    "timeline",
    "comparison",
    "quote",
    "statistics",
    "code",
    "table",
    "diagram",
    "icon",
]


class _BaseElement(BaseModel):
    """Shared element fields."""

    id: str | None = None
    animation: str | None = Field(default=None, max_length=40)


class TitleElement(_BaseElement):
    type: Literal["title"] = "title"
    text: str
    level: int = Field(default=1, ge=1, le=6)


class SubtitleElement(_BaseElement):
    type: Literal["subtitle"] = "subtitle"
    text: str


class ParagraphElement(_BaseElement):
    type: Literal["paragraph"] = "paragraph"
    text: str


class BulletsElement(_BaseElement):
    type: Literal["bullets"] = "bullets"
    items: list[str] = Field(default_factory=list)


class ImageElement(_BaseElement):
    type: Literal["image"] = "image"
    src: str | None = None  # optional: asset reference / placeholder id
    alt: str = ""
    caption: str | None = None


class CardsElement(_BaseElement):
    type: Literal["cards"] = "cards"
    items: list[dict[str, Any]] = Field(default_factory=list)


class TimelineElement(_BaseElement):
    type: Literal["timeline"] = "timeline"
    items: list[dict[str, Any]] = Field(default_factory=list)


class ComparisonElement(_BaseElement):
    type: Literal["comparison"] = "comparison"
    left: dict[str, Any] = Field(default_factory=dict)
    right: dict[str, Any] = Field(default_factory=dict)


class QuoteElement(_BaseElement):
    type: Literal["quote"] = "quote"
    text: str
    author: str | None = None


class StatisticsElement(_BaseElement):
    type: Literal["statistics"] = "statistics"
    items: list[dict[str, Any]] = Field(default_factory=list)


class CodeElement(_BaseElement):
    type: Literal["code"] = "code"
    language: str = "text"
    code: str


class TableElement(_BaseElement):
    type: Literal["table"] = "table"
    headers: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)


class DiagramElement(_BaseElement):
    type: Literal["diagram"] = "diagram"
    kind: str = "placeholder"
    label: str | None = None


class IconElement(_BaseElement):
    type: Literal["icon"] = "icon"
    name: str = "spark"
    label: str | None = None


Element = Union[
    TitleElement,
    SubtitleElement,
    ParagraphElement,
    BulletsElement,
    ImageElement,
    CardsElement,
    TimelineElement,
    ComparisonElement,
    QuoteElement,
    StatisticsElement,
    CodeElement,
    TableElement,
    DiagramElement,
    IconElement,
]


# --- Slide & Presentation ------------------------------------------------


class SlideSpec(BaseModel):
    """One slide in the specification."""

    layout: LayoutName = "title"
    background: str | None = None
    theme: str | None = None
    elements: list[Element] = Field(default_factory=list)
    notes: str | None = None


class PresentationMeta(BaseModel):
    """Deck-level metadata."""

    title: str = ""
    theme: str | None = None
    background: str | None = None
    language: str = "English"
    tone: str = "Professional"


class PresentationSpec(BaseModel):
    """The full structured specification returned by the AI engine."""

    meta: PresentationMeta = Field(default_factory=PresentationMeta)
    slides: list[SlideSpec] = Field(default_factory=list)

    @classmethod
    def validate_spec(cls, data: Any) -> "PresentationSpec":
        """Validate raw provider JSON, raising :class:`ValidationError`."""
        if not isinstance(data, dict):
            raise ValidationError.from_exception_data("PresentationSpec", [])
        spec = cls.model_validate(data)
        if not spec.slides:
            raise ValidationError.from_exception_data(
                "PresentationSpec",
                [{"type": "missing", "loc": ("slides",), "msg": "slides required"}],
            )
        return spec
