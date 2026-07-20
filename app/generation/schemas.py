"""Schemas for AI slide generation.

These describe the *request* the application sends to the generation
provider and the *result* it receives back. The provider is always
referred to as "Slide AI" to the outside world; its concrete identity
(OpenCode Zen) never leaves this backend.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

_TONE_MAX = 40
_LANG_MAX = 40
_PROMPT_MAX = 4000
_TITLE_MAX = 200


class GenerationRequest(BaseModel):
    """What the user asked the generator to produce."""

    prompt: str = Field(min_length=1, max_length=_PROMPT_MAX)
    slide_count: int = Field(default=10, ge=1, le=30)
    tone: str = Field(default="Professional", max_length=_TONE_MAX)
    language: str = Field(default="English", max_length=_LANG_MAX)
    theme: str | None = Field(default=None, max_length=40)


class GeneratedSlide(BaseModel):
    """A single generated slide."""

    title: str = Field(min_length=1, max_length=_TITLE_MAX)
    bullets: list[str] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=4000)
    layout: str = "title-bullets"


class GenerationResult(BaseModel):
    """All slides for one presentation."""

    slides: list[GeneratedSlide]
