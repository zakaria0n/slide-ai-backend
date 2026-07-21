"""AI-powered spec editing — modifies a PresentationSpec via natural language.

Providers:
- ``OnlineSpecEditProvider``: sends current spec + instruction to the LLM and
  returns a fully patched spec.  Used when an API key is configured.
- ``OfflineSpecEditProvider``: deterministic rule-based fallback for dev / tests.
"""
from __future__ import annotations

import copy
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import Settings
from app.core.exceptions import ProviderError
from app.generation.spec import PresentationSpec

DISPLAYED_PROVIDER = "Slide AI"
_MAX_RETRIES = 1


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


# ---------------------------------------------------------------------------
# Real LLM-based editor
# ---------------------------------------------------------------------------

_EDIT_SYSTEM_PROMPT = """\
You are Slide AI, an expert presentation editor. You receive a presentation specification in JSON and a user instruction. Modify the spec according to the instruction and return the COMPLETE modified specification.

RULES:
1. Return ONLY valid JSON (no markdown fences). The entire spec must be returned — every slide, every element.
2. Preserve all slides and elements that are not affected by the instruction.
3. If the instruction says to change colors/theme, update meta.theme and any slide theme fields.
4. If the instruction says to rewrite text, improve the text — make it concise and professional.
5. If the instruction says to add a slide, insert it at a logical position.
6. If the instruction says to delete a slide, remove it (but never delete the last slide).
7. If the instruction says to move/reorder slides, rearrange the slides array.
8. If the instruction says to change layout, change the layout field of the target slide.
9. Always respond with a short summary of what you changed as a top-level "summary" field.
10. Return a "changed_indexes" array of slide indices (0-based) that were modified.

Response shape:
{
  "summary": "What you changed in one sentence.",
  "changed_indexes": [0, 2, 5],
  "meta": { ... },
  "slides": [ ... ]
}
"""


class OnlineSpecEditProvider(SpecEditProvider):
    """Real LLM-based spec editor."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.ai_provider_base_url.rstrip("/")
        self._api_key = settings.ai_provider_api_key
        self._model = settings.ai_provider_default_model
        self._timeout = settings.ai_request_timeout_seconds

    async def edit_spec(
        self,
        spec: PresentationSpec,
        instruction: str,
        target_indexes: list[int] | None = None,
    ) -> SpecEditResult:
        spec_json = spec.model_dump(mode="json")

        user_msg = (
            f"Instruction: {instruction}\n\n"
            f"Current presentation:\n```json\n{json.dumps(spec_json, ensure_ascii=False)}\n```"
        )
        if target_indexes is not None:
            user_msg += f"\nTarget slide indexes: {target_indexes}"

        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for attempt in range(_MAX_RETRIES + 1):
                system = _EDIT_SYSTEM_PROMPT + (
                    "\n\nThe previous response was invalid JSON or missing fields. "
                    "Fix it and return valid JSON only."
                    if attempt > 0
                    else ""
                )
                try:
                    resp = await client.post(
                        f"{self._base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self._model,
                            "messages": [
                                {"role": "system", "content": system},
                                {"role": "user", "content": user_msg},
                            ],
                            "response_format": {"type": "json_object"},
                            "temperature": 0.4,
                        },
                    )
                except httpx.HTTPError as exc:
                    raise ProviderError(
                        f"{DISPLAYED_PROVIDER} is temporarily unavailable"
                    ) from exc

                if resp.status_code != 200:
                    raise ProviderError(f"{DISPLAYED_PROVIDER} returned an error")

                try:
                    body = resp.json()
                    content = body["choices"][0]["message"]["content"]
                    data = json.loads(content.strip())
                except (KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
                    last_error = exc
                    continue

                # Extract summary and changed_indexes, then validate the spec.
                summary = data.pop("summary", f"Applied: {instruction}")
                changed = data.pop("changed_indexes", list(range(len(spec.slides))))

                try:
                    modified = PresentationSpec.model_validate(data)
                except Exception as exc:
                    last_error = exc
                    continue

                return SpecEditResult(
                    modified_spec=modified,
                    summary=str(summary),
                    changed_indexes=changed if isinstance(changed, list) else [],
                )

        raise ProviderError(
            f"{DISPLAYED_PROVIDER} could not process the edit instruction"
        ) from last_error


# ---------------------------------------------------------------------------
# Offline rule-based editor (dev / tests)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_spec_edit_provider(settings: Settings) -> SpecEditProvider:
    """Select a spec edit provider based on configuration."""
    if not settings.ai_provider_api_key:
        return OfflineSpecEditProvider()
    return OnlineSpecEditProvider(settings)