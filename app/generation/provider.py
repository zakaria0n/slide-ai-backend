"""Generation provider abstraction.

The application talks to a single provider interface, :class:`GenerationProvider`.
Two implementations exist:

* :class:`OpenCodeZenProvider` — the production client that calls the real
  upstream model API (internally "OpenCode Zen"). It is never named in any
  surfaced message or schema; callers see the abstract "Slide AI".
* :class:`OfflineGenerationProvider` — a deterministic stub used when no
  real provider key is configured (local dev / tests). It produces a valid
  deck shape so the full feature works without network access.

The factory :func:`build_generation_provider` selects between them based on
settings so the rest of the app is provider-agnostic.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from app.core.config import Settings
from app.core.exceptions import ProviderError
from app.generation.schemas import (
    GeneratedSlide,
    GenerationRequest,
    GenerationResult,
)

# The name the application always exposes to users. The real provider name
# (OpenCode Zen) is intentionally never surfaced.
DISPLAYED_PROVIDER = "Slide AI"


class GenerationProvider(ABC):
    """Contract for turning a request into slides."""

    @abstractmethod
    async def generate(self, request: GenerationRequest) -> GenerationResult:
        ...


_SYSTEM_PROMPT = (
    "You are Slide AI, an expert presentation designer. "
    "Given a topic and options, return a JSON object with a 'slides' array. "
    "Each slide has: title (string), bullets (array of strings, 3-6 items), "
    "notes (string or null), layout (usually 'title-bullets'). "
    "Return ONLY valid JSON, no markdown."
)


def _parse_slides(raw: str, want: int) -> list[GeneratedSlide]:
    """Best-effort extraction of slides from a model response."""
    text = raw.strip()
    # Strip code fences if the model wrapped the JSON.
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise ProviderError("The generation response was not valid JSON") from exc
    items = data.get("slides") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise ProviderError("The generation response contained no slides")
    slides: list[GeneratedSlide] = []
    for item in items[: max(1, want)]:
        if not isinstance(item, dict):
            continue
        bullets = item.get("bullets") or []
        slides.append(
            GeneratedSlide(
                title=str(item.get("title", "Untitled slide"))[:200],
                bullets=[str(b) for b in bullets][:6],
                notes=item.get("notes") if isinstance(item.get("notes"), str) else None,
                layout=str(item.get("layout", "title-bullets"))[:40],
            )
        )
    if not slides:
        raise ProviderError("The generation response contained no usable slides")
    return slides


class OpenCodeZenProvider(GenerationProvider):
    """Production client for the real upstream model API.

    The internal provider name (OpenCode Zen) is never placed in any
    exception or response — :class:`ProviderError` masks it to "Slide AI".
    """

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.ai_provider_base_url.rstrip("/")
        self._api_key = settings.ai_provider_api_key
        self._model = settings.ai_provider_default_model
        self._timeout = settings.ai_request_timeout_seconds

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        user_prompt = (
            f"Topic: {request.prompt}\n"
            f"Number of slides: {request.slide_count}\n"
            f"Tone: {request.tone}\n"
            f"Language: {request.language}"
            + (f"\nTheme: {request.theme}" if request.theme else "")
        )
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.7,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.HTTPError as exc:
            # Mask any upstream identity; surface a neutral provider error.
            raise ProviderError(f"{DISPLAYED_PROVIDER} is temporarily unavailable") from exc

        if resp.status_code != 200:
            raise ProviderError(f"{DISPLAYED_PROVIDER} returned an error")

        try:
            body = resp.json()
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderError("The generation response was malformed") from exc

        slides = _parse_slides(content, request.slide_count)
        return GenerationResult(slides=slides)


class OfflineGenerationProvider(GenerationProvider):
    """Deterministic stub used without a real provider key.

    Produces a plausible deck so the feature is fully exercisable offline.
    """

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        count = max(1, min(request.slide_count, 30))
        topic = request.prompt.strip() or "Presentation"
        title_case = topic[:1].upper() + topic[1:]
        slides: list[GeneratedSlide] = [
            GeneratedSlide(
                title=title_case,
                bullets=[
                    f"{request.tone} overview of {topic}",
                    f"Prepared for a {request.language}-speaking audience",
                    f"Theme: {request.theme or 'default'}",
                ],
                notes="Title slide.",
                layout="title-bullets",
            )
        ]
        section_titles = [
            "The Big Idea",
            "Why It Matters",
            "How It Works",
            "Key Results",
            "What's Next",
            "Call to Action",
        ]
        for i in range(count - 1):
            t = section_titles[i % len(section_titles)]
            slides.append(
                GeneratedSlide(
                    title=f"{i + 1}. {t}",
                    bullets=[
                        f"Point one about {topic.lower()}",
                        f"Point two with supporting detail",
                        f"Point three to reinforce the message",
                    ],
                    notes=f"Discuss {t.lower()} in the {request.tone.lower()} tone.",
                    layout="title-bullets",
                )
            )
        return GenerationResult(slides=slides)


def build_generation_provider(settings: Settings) -> GenerationProvider:
    """Pick a provider based on configuration.

    When the API key is still the placeholder, use the offline stub so the
    app runs without a real provider. Otherwise use the production client.
    """
    if not settings.ai_provider_api_key or settings.ai_provider_api_key == "public":
        return OfflineGenerationProvider()
    return OpenCodeZenProvider(settings)
