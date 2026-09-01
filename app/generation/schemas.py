"""Schemas for AI slide generation.

The provider is always referred to as "Slide AI" to the outside world.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

_TONE_MAX = 40
_LANG_MAX = 40
_PROMPT_MAX = 4000


class OutlineItem(BaseModel):
    """One approved slide from the outline-first flow."""

    title: str = Field(min_length=1, max_length=300)
    points: list[str] = Field(default_factory=list, max_length=12)


class GenerationRequest(BaseModel):
    """What the user asked the generator to produce."""

    prompt: str = Field(min_length=1, max_length=_PROMPT_MAX)
    slide_count: int = Field(default=10, ge=1, le=30)
    tone: str = Field(default="Professional", max_length=_TONE_MAX)
    language: str = Field(default="English", max_length=_LANG_MAX)
    theme: str | None = Field(default=None, max_length=40)
    template_name: str | None = Field(default=None, max_length=40)
    # Model the caller picked on the settings page. None → backend default.
    model: str | None = Field(default=None, max_length=80)
    # Optional source material (markdown / extracted web page text) the deck
    # must be based on — used by the import endpoint.
    source_content: str | None = Field(default=None, max_length=20000)
    # Approved outline (outline-first flow): the deck MUST follow it — one
    # slide per entry, in order.
    outline: list[OutlineItem] | None = Field(default=None, max_length=30)
