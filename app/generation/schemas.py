"""Schemas for AI slide generation.

The provider is always referred to as "Slide AI" to the outside world.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

_TONE_MAX = 40
_LANG_MAX = 40
_PROMPT_MAX = 4000


class GenerationRequest(BaseModel):
    """What the user asked the generator to produce."""

    prompt: str = Field(min_length=1, max_length=_PROMPT_MAX)
    slide_count: int = Field(default=10, ge=1, le=30)
    tone: str = Field(default="Professional", max_length=_TONE_MAX)
    language: str = Field(default="English", max_length=_LANG_MAX)
    theme: str | None = Field(default=None, max_length=40)
