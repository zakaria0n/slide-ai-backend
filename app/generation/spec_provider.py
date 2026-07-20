"""Presentation Specification generation.

Builds a :class:`PresentationSpec` from a :class:`GenerationRequest`.

* The real provider (OpenCode Zen, surfaced only as "Slide AI") is prompted
  to return the strict specification JSON.
* The offline stub produces a valid spec deterministically so the full
  pipeline works without a network key.
* :func:`generate_spec` validates the provider output and **auto-retries**
  (re-asking the model to fix the JSON) when the schema is invalid, per the
  Phase 7 requirement.

This module reuses the existing :class:`GenerationProvider` abstraction; the
spec generator is a thin strategy over it.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import ValidationError

from app.core.config import Settings
from app.core.exceptions import ProviderError
from app.generation.schemas import GenerationRequest
from app.generation.spec import PresentationSpec

DISPLAYED_PROVIDER = "Slide AI"
_MAX_RETRIES = 2


class SpecProvider(ABC):
    """Contract for producing a validated PresentationSpec."""

    @abstractmethod
    async def generate_spec(self, request: GenerationRequest) -> PresentationSpec:
        ...


# The strict schema description embedded in prompts so the model returns the
# exact structure the renderer expects.
_SCHEMA_HINT = (
    "Return ONLY valid JSON (no markdown) with this shape:\n"
    "{\n"
    '  "meta": {"title": str, "theme": str|null, "background": str|null, '
    '"language": str, "tone": str},\n'
    '  "slides": [\n'
    "    {\n"
    '      "layout": one of hero/title/agenda/section/timeline/comparison/'
    "cards/statistics/pricing/gallery/process/flow/roadmap/team/quote/"
    "swot/table/chart/image-left/image-right/cta/conclusion/thank-you,\n"
    '      "background": str|null,\n'
    '      "theme": str|null,\n'
    '      "notes": str|null,\n'
    '      "elements": [ { "type": "title", "text": str, "level": int },\n'
    '                     { "type": "subtitle", "text": str },\n'
    '                     { "type": "paragraph", "text": str },\n'
    '                     { "type": "bullets", "items": [str] },\n'
    '                     { "type": "image", "src": str|null, "alt": str },\n'
    '                     { "type": "quote", "text": str, "author": str|null },\n'
    '                     { "type": "statistics", "items": [{"value":str,"label":str}] },\n'
    '                     { "type": "cards", "items": [{"title":str,"body":str}] },\n'
    '                     { "type": "table", "headers":[str], "rows":[[...]] },\n'
    '                     { "type": "code", "language": str, "code": str } ]\n'
    "    }\n"
    "  ]\n"
    "}\n"
    "Use varied, professional layouts across slides."
)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        # Remove opening fence (optionally "json").
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.startswith("json"):
            text = text[4:]
        # Remove closing fence.
        if "```" in text:
            text = text.rsplit("```", 1)[0]
    return text.strip()


def _parse_spec(raw: str) -> PresentationSpec:
    cleaned = _strip_fences(raw)
    try:
        data: Any = json.loads(cleaned)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise ProviderError("The generation response was not valid JSON") from exc
    try:
        return PresentationSpec.validate_spec(data)
    except ValidationError as exc:
        # Re-raise so the caller can retry.
        raise ProviderError("The specification did not match the required schema") from exc


class OpenCodeZenSpecProvider(SpecProvider):
    """Real provider client that returns a structured specification."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.ai_provider_base_url.rstrip("/")
        self._api_key = settings.ai_provider_api_key
        self._model = settings.ai_provider_default_model
        self._timeout = settings.ai_request_timeout_seconds

    async def generate_spec(self, request: GenerationRequest) -> PresentationSpec:
        user_prompt = (
            f"Topic: {request.prompt}\n"
            f"Number of slides: {request.slide_count}\n"
            f"Tone: {request.tone}\n"
            f"Language: {request.language}"
            + (f"\nTheme: {request.theme}" if request.theme else "")
        )
        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for attempt in range(_MAX_RETRIES + 1):
                system = _SYSTEM_PROMPT + (
                    "\nFix the previous output to match the schema exactly."
                    if attempt > 0
                    else ""
                )
                payload = {
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_prompt},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.7,
                }
                try:
                    resp = await client.post(
                        f"{self._base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
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
                except (KeyError, IndexError, ValueError) as exc:
                    raise ProviderError(
                        "The generation response was malformed"
                    ) from exc
                try:
                    return _parse_spec(content)
                except ProviderError as exc:
                    last_error = exc
                    # Auto-retry on schema failure.
                    continue
        raise ProviderError(
            f"{DISPLAYED_PROVIDER} could not produce a valid specification"
        ) from last_error


class OfflineSpecProvider(SpecProvider):
    """Deterministic specification stub for dev / tests (no provider key)."""

    async def generate_spec(self, request: GenerationRequest) -> PresentationSpec:
        count = max(1, min(request.slide_count, 30))
        topic = (request.prompt.strip() or "Presentation").capitalize()

        slides: list[dict[str, Any]] = [
            {
                "layout": "hero",
                "elements": [
                    {"type": "title", "text": topic, "level": 1},
                    {
                        "type": "subtitle",
                        "text": f"A {request.tone.lower()} presentation in {request.language}",
                    },
                ],
                "notes": "Opening hero slide.",
            }
        ]
        section_titles = [
            "Overview",
            "Why It Matters",
            "How It Works",
            "Key Results",
            "What's Next",
            "Call to Action",
        ]
        stat_layouts = ["statistics", "cards", "timeline", "comparison", "quote"]
        # Body slides: leave room for the hero (1) and thank-you (1).
        body_count = max(0, count - 2)
        for i in range(body_count):
            t = section_titles[i % len(section_titles)]
            layout = stat_layouts[i % len(stat_layouts)]
            if layout == "statistics":
                elements = [
                    {"type": "title", "text": f"{i + 1}. {t}", "level": 2},
                    {
                        "type": "statistics",
                        "items": [
                            {"value": "98%", "label": "Engagement"},
                            {"value": "3x", "label": "Faster delivery"},
                            {"value": "12k", "label": "Users"},
                        ],
                    },
                ]
            elif layout == "cards":
                elements = [
                    {"type": "title", "text": f"{i + 1}. {t}", "level": 2},
                    {
                        "type": "cards",
                        "items": [
                            {"title": "Pillar one", "body": f"Detail about {topic.lower()}."},
                            {"title": "Pillar two", "body": "Supporting point with evidence."},
                            {"title": "Pillar three", "body": "Outcome and impact."},
                        ],
                    },
                ]
            elif layout == "timeline":
                elements = [
                    {"type": "title", "text": f"{i + 1}. {t}", "level": 2},
                    {
                        "type": "timeline",
                        "items": [
                            {"year": "2024", "text": "Started"},
                            {"year": "2025", "text": "Scaled"},
                            {"year": "2026", "text": "Leader"},
                        ],
                    },
                ]
            elif layout == "comparison":
                elements = [
                    {"type": "title", "text": f"{i + 1}. {t}", "level": 2},
                    {
                        "type": "comparison",
                        "left": {"title": "Before", "points": ["Manual", "Slow"]},
                        "right": {"title": "After", "points": ["Automated", "Fast"]},
                    },
                ]
            else:  # quote
                elements = [
                    {"type": "title", "text": f"{i + 1}. {t}", "level": 2},
                    {
                        "type": "quote",
                        "text": f"{t} is what sets {topic} apart.",
                        "author": "Slide AI",
                    },
                ]
            slides.append({"layout": layout, "elements": elements})

        slides.append(
            {
                "layout": "thank-you",
                "elements": [
                    {"type": "title", "text": "Thank you", "level": 1},
                    {"type": "subtitle", "text": "Generated with Slide AI"},
                ],
            }
        )

        spec = {
            "meta": {
                "title": topic,
                "theme": request.theme,
                "background": None,
                "language": request.language,
                "tone": request.tone,
            },
            "slides": slides,
        }
        return PresentationSpec.validate_spec(spec)


def build_spec_provider(settings: Settings) -> SpecProvider:
    """Select a spec provider based on configuration."""
    if not settings.ai_provider_api_key or settings.ai_provider_api_key == "public":
        return OfflineSpecProvider()
    return OpenCodeZenSpecProvider(settings)


_SYSTEM_PROMPT = (
    "You are Slide AI, an expert presentation designer. "
    "Generate a structured presentation specification.\n"
    + _SCHEMA_HINT
)
