"""AI-powered spec editing — modifies only affected slides via natural language.

The provider takes an existing PresentationSpec + instruction and returns a
patched spec. The offline provider applies deterministic rule-based edits so
the feature works without a real AI key.
"""
from __future__ import annotations

import copy
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings
from app.generation.spec import PresentationSpec

DISPLAYED_PROVIDER = "Slide AI"


@dataclass
class SpecEditResult:
    """Result of an AI spec edit operation."""

    modified_spec: PresentationSpec
    summary: str
    changed_indexes: list[int] = field(default_factory=list)


class SpecEditProvider(ABC):
    """Contract for AI-driven spec modification."""

    @abstractmethod
    async def edit_spec(
        self,
        spec: PresentationSpec,
        instruction: str,
        target_indexes: list[int] | None = None,
    ) -> SpecEditResult:
        ...


class OfflineSpecEditProvider(SpecEditProvider):
    """Rule-based deterministic edits for dev / tests (no AI key).

    Recognised instructions (case-insensitive, partial match):
    - "make it modern"        -> theme = "modern"
    - "make it minimal"       -> theme = "minimal"
    - "make it bold"          -> theme = "bold"
    - "make it elegant"       -> theme = "elegant"
    - "make it dark"          -> theme = "dark"
    - "reduce text" / "less text" -> truncate paragraphs/bullets
    - "add statistic" / "add stat" -> append a statistics element
    - "add slide" / "new slide"    -> append a blank title slide
    - "remove last slide" / "delete last slide" -> remove final slide
    """

    _THEME_MAP: dict[str, str] = {
        "modern": "modern",
        "minimal": "minimal",
        "bold": "bold",
        "elegant": "elegant",
        "dark": "dark",
        "default": "default",
        "gradient": "gradient",
        "sunset": "sunset",
        "ocean": "ocean",
        "forest": "forest",
        "neon": "neon",
        "pastel": "pastel",
        "coral": "coral",
        "midnight": "midnight",
        "monochrome": "monochrome",
    }

    async def edit_spec(
        self,
        spec: PresentationSpec,
        instruction: str,
        target_indexes: list[int] | None = None,
    ) -> SpecEditResult:
        lowered = instruction.lower().strip()
        modified = copy.deepcopy(spec)
        changed: list[int] = []
        summary = ""

        # Determine target slides.
        if target_indexes is not None:
            targets = [i for i in target_indexes if 0 <= i < len(modified.slides)]
        else:
            targets = list(range(len(modified.slides)))

        # Theme change.
        matched_theme: str | None = None
        for keyword, theme_name in self._THEME_MAP.items():
            if keyword in lowered and ("theme" in lowered or f"make it {keyword}" in lowered or f"change to {keyword}" in lowered):
                matched_theme = theme_name
                break
        if matched_theme:
            modified.meta.theme = matched_theme
            for idx in targets:
                modified.slides[idx].theme = matched_theme
                changed.append(idx)
            summary = f"Changed theme to '{matched_theme}'"
            return SpecEditResult(modified_spec=modified, summary=summary, changed_indexes=list(set(changed)))

        # Reduce text.
        if "reduce text" in lowered or "less text" in lowered or "shorter" in lowered or "condense" in lowered:
            for idx in targets:
                slide = modified.slides[idx]
                for el in slide.elements:
                    if el.type == "paragraph" and hasattr(el, "text"):
                        words = el.text.split()
                        el.text = " ".join(words[: max(3, len(words) // 2)])
                    elif el.type == "bullets" and hasattr(el, "items"):
                        el.items = el.items[: max(1, len(el.items) - 1)]
                    elif el.type == "title" and hasattr(el, "text"):
                        words = el.text.split()
                        if len(words) > 8:
                            el.text = " ".join(words[:6]) + "..."
                changed.append(idx)
            summary = "Reduced text on targeted slides"
            return SpecEditResult(modified_spec=modified, summary=summary, changed_indexes=list(set(changed)))

        # Add statistic.
        if "add statistic" in lowered or "add stat" in lowered or "add metric" in lowered:
            for idx in targets:
                slide = modified.slides[idx]
                stat_el = {
                    "type": "statistics",
                    "items": [
                        {"value": "98%", "label": "Engagement"},
                        {"value": "3x", "label": "Growth"},
                        {"value": "12k", "label": "Users"},
                    ],
                }
                slide.elements.append(stat_el)  # type: ignore[arg-type]
                changed.append(idx)
            summary = "Added statistics element"
            return SpecEditResult(modified_spec=modified, summary=summary, changed_indexes=list(set(changed)))

        # Add slide.
        if "add slide" in lowered or "new slide" in lowered or "insert slide" in lowered:
            new_slide = {
                "layout": "title",
                "elements": [
                    {"type": "title", "text": "New Slide", "level": 1},
                    {"type": "subtitle", "text": "Click to edit"},
                ],
            }
            modified.slides.append(new_slide)  # type: ignore[arg-type]
            changed.append(len(modified.slides) - 1)
            summary = "Added a new slide"
            return SpecEditResult(modified_spec=modified, summary=summary, changed_indexes=changed)

        # Remove last slide.
        if "remove last slide" in lowered or "delete last slide" in lowered:
            if len(modified.slides) > 1:
                removed_idx = len(modified.slides) - 1
                modified.slides.pop()
                summary = f"Removed slide {removed_idx + 1}"
                return SpecEditResult(modified_spec=modified, summary=summary, changed_indexes=[removed_idx])
            summary = "Cannot remove the only slide"
            return SpecEditResult(modified_spec=modified, summary=summary, changed_indexes=[])

        # Fallback: no-op.
        summary = f"Instruction not recognised: '{instruction}'"
        return SpecEditResult(modified_spec=modified, summary=summary, changed_indexes=[])


def build_spec_edit_provider(settings: Settings) -> SpecEditProvider:
    """Select a spec edit provider based on configuration."""
    if not settings.ai_provider_api_key or settings.ai_provider_api_key == "public":
        return OfflineSpecEditProvider()
    # Real provider can be added later; for now fall back to offline.
    return OfflineSpecEditProvider()
