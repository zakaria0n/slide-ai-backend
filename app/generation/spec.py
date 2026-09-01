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

from pydantic import AliasChoices, BaseModel, Field, ValidationError, field_validator

# --- Element union ---------------------------------------------------------

LayoutName = Literal[
    "hero",
    "title",
    "blank",
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
    "custom",
]

ElementType = Literal[
    "title",
    "subtitle",
    "paragraph",
    "bullets",
    "image",
    "video",
    "audio",
    "shape",
    "cards",
    "timeline",
    "comparison",
    "quote",
    "statistics",
    "code",
    "table",
    "diagram",
    "icon",
    "chart",
]


class ElementStyle(BaseModel):
    """Optional per-element style overrides (structured layouts).

    All fields optional — anything unset inherits from the theme tokens.
    """

    model_config = {"extra": "forbid"}

    color: str | None = Field(default=None, max_length=60)
    font_size: str | None = Field(default=None, max_length=24)
    font_weight: str | None = Field(default=None, max_length=12)
    align: Literal["left", "center", "right", "justify"] | None = None
    opacity: float | None = Field(default=None, ge=0, le=1)
    rotation: float | None = Field(default=None, ge=-360, le=360)


class _BaseElement(BaseModel):
    """Shared element fields."""

    id: str | None = None
    # The frontend speaks camelCase (animationDelay); accept both spellings so
    # client-authored specs never silently drop data.
    animation: str | None = Field(default=None, max_length=40)
    # Extra delay (ms) before this element's entrance animation starts,
    # on top of the automatic stagger.
    animation_delay: int | None = Field(
        default=None, ge=0, le=10000,
        validation_alias=AliasChoices("animation_delay", "animationDelay"),
    )
    # Per-element style overrides.
    style: ElementStyle | None = None
    # Free (Canvas-style) placement, in percent of the slide size. When set,
    # the element is rendered as a floating overlay instead of inside the
    # layout flow — this is how manually inserted elements are positioned.
    x: float | None = Field(default=None, ge=0, le=100)
    y: float | None = Field(default=None, ge=0, le=100)
    # Fixed width in percent of the slide width (text wrap / image sizing).
    w: float | None = Field(default=None, ge=1, le=100)
    # Fixed height in percent of the slide height (shapes / media).
    h: float | None = Field(default=None, ge=1, le=100)
    # Editing lock — a locked element can't be moved/resized/deleted in the
    # editor until unlocked. Purely an authoring concern; renderers ignore it.
    locked: bool = False


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
    # Stable reference to a file_assets row. Signed URLs expire — when this
    # is set, renderers/exports resolve a FRESH src from the file id instead
    # of trusting the possibly-expired src.
    file_id: str | None = Field(
        default=None, max_length=80,
        validation_alias=AliasChoices("file_id", "fileId"),
    )
    alt: str = ""
    caption: str | None = None
    # Light image controls: horizontal mirror + CSS object-position.
    flip: bool = False
    object_position: str | None = Field(
        default=None, max_length=40,
        validation_alias=AliasChoices("object_position", "objectPosition"),
    )


class VideoElement(_BaseElement):
    type: Literal["video"] = "video"
    src: str | None = None
    file_id: str | None = Field(
        default=None, max_length=80,
        validation_alias=AliasChoices("file_id", "fileId"),
    )
    alt: str = ""
    poster: str | None = None
    # Start playing automatically when the slide becomes active (muted).
    autoplay: bool = False


class AudioElement(_BaseElement):
    type: Literal["audio"] = "audio"
    src: str | None = None
    file_id: str | None = Field(
        default=None, max_length=80,
        validation_alias=AliasChoices("file_id", "fileId"),
    )
    alt: str = ""


class ShapeElement(_BaseElement):
    """Simple vector shapes for free (Canvas-style) composition."""

    type: Literal["shape"] = "shape"
    shape: Literal["rect", "circle", "line", "arrow"] = "rect"
    # Fill color — defaults to the theme accent.
    fill: str | None = Field(default=None, max_length=60)
    # Border color for rect/circle (defaults to fill at 40% alpha look).
    border_color: str | None = Field(default=None, max_length=60)


# --- Inner element payloads -------------------------------------------------


class CardItem(BaseModel):
    title: str = ""
    body: str = ""


class StatItem(BaseModel):
    value: str = ""
    label: str = ""


class TimelineItem(BaseModel):
    year: str = ""
    text: str = ""


class ComparisonSide(BaseModel):
    title: str = ""
    points: list[str] = Field(default_factory=list)


class CardsElement(_BaseElement):
    type: Literal["cards"] = "cards"
    items: list[CardItem] = Field(default_factory=list)


class TimelineElement(_BaseElement):
    type: Literal["timeline"] = "timeline"
    items: list[TimelineItem] = Field(default_factory=list)


class ComparisonElement(_BaseElement):
    type: Literal["comparison"] = "comparison"
    left: ComparisonSide = Field(default_factory=ComparisonSide)
    right: ComparisonSide = Field(default_factory=ComparisonSide)


class QuoteElement(_BaseElement):
    type: Literal["quote"] = "quote"
    text: str
    author: str | None = None


class StatisticsElement(_BaseElement):
    type: Literal["statistics"] = "statistics"
    items: list[StatItem] = Field(default_factory=list)


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


class ChartDataset(BaseModel):
    """One data series of a chart element."""

    label: str = ""
    data: list[float] = Field(default_factory=list)


class ChartElement(_BaseElement):
    """Native data chart — real Chart.js on the frontend and a REAL editable
    PowerPoint chart in the PPTX export (not a picture, not a text block)."""

    type: Literal["chart"] = "chart"
    chart_type: Literal["bar", "line", "pie", "doughnut", "radar"] = Field(
        default="bar",
        validation_alias=AliasChoices("chart_type", "chartType"),
    )
    labels: list[str] = Field(default_factory=list, max_length=24)
    datasets: list[ChartDataset] = Field(default_factory=list, max_length=6)


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
    VideoElement,
    AudioElement,
    ShapeElement,
    ChartElement,
]


# --- Slide & Presentation ------------------------------------------------


class CustomSlideCode(BaseModel):
    """Free-coded slide payload (layout='custom')."""

    html: str = ""
    css: str = ""
    js: str = ""


class SlideSpec(BaseModel):
    """One slide in the specification."""

    layout: LayoutName = "title"
    background: str | None = None
    theme: str | None = None
    elements: list[Element] = Field(default_factory=list)
    notes: str | None = None
    # Only for layout="custom": AI-authored HTML/CSS/JS rendered in a sandboxed
    # iframe on the frontend. No validation by design — the sandbox is the guard.
    code: CustomSlideCode | None = None


class PresentationMeta(BaseModel):
    """Deck-level metadata."""

    title: str = ""
    theme: str | None = None
    background: str | None = None
    language: str = "English"
    tone: str = "Professional"
    # AI-authored custom animations. Each is validated (CSS-parsed, property
    # whitelist, duration/easing bounds) on the frontend; invalid defs are
    # dropped silently and the element falls back to a built-in animation.
    # Kept camelCase to match the frontend spec shape exactly.
    customAnimations: list["CustomAnimationDef"] | None = None
    # Full renderer token set for a USER-SAVED theme (colors, fonts, ambient).
    # Stored verbatim on the deck so any viewer/renderer/export can re-skin it
    # without a themes lookup. camelCase to match the frontend meta shape.
    themeTokens: dict | None = None


class CustomAnimationDef(BaseModel):
    """A named keyframe animation the model can attach to elements."""

    name: str = ""
    # Raw "@keyframes <name> { ... }" rule (or just the body). Only transform,
    # opacity and filter are allowed inside. Must stay small.
    keyframes: str = ""
    # Animation length in milliseconds (validated: 100–2000ms).
    duration: int = 0
    # Timing function — a cubic-bezier(...), steps(...) or non-linear keyword.
    easing: str | None = None
    # Extra delay (ms) before the animation starts.
    delay: int = Field(default=0, ge=0, le=5000)
    # Repeat count — a positive integer or the literal "infinite".
    loop: int | str = Field(default=1)

    @field_validator("loop")
    @classmethod
    def _validate_loop(cls, value):
        if isinstance(value, str):
            if value.lower() == "infinite":
                return "infinite"
            raise ValueError("loop must be a positive integer or 'infinite'")
        return max(1, min(int(value), 50))


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
