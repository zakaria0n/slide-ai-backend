"""Small shared helper for one-shot JSON LLM calls.

Used by the outliner and the translator — anything that needs a single
chat completion back as JSON but not the full spec pipeline.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from app.core.config import Settings
from app.core.exceptions import ProviderError
from app.generation.spec_provider import DISPLAYED_PROVIDER

# Same transient statuses and backoff philosophy as spec_provider.
_TRANSIENT_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 2
_BACKOFF_S = [2.0, 6.0]


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.startswith("json"):
            text = text[4:]
        if "```" in text:
            text = text.rsplit("```", 1)[0]
    return text.strip()


async def complete_json(
    settings: Settings,
    *,
    model: str,
    system: str,
    user: str,
    max_tokens: int = 4000,
) -> Any:
    """One chat completion forced to JSON; returns the parsed value.

    Raises :class:`ProviderError` on any failure after retries.
    """
    async with httpx.AsyncClient(timeout=settings.ai_request_timeout_seconds) as client:
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = await client.post(
                    f"{settings.ai_provider_base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.ai_provider_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "response_format": {"type": "json_object"},
                        "temperature": 0.4,
                        "max_tokens": max_tokens,
                    },
                )
            except httpx.HTTPError as exc:
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_BACKOFF_S[min(attempt, len(_BACKOFF_S) - 1)])
                    continue
                raise ProviderError(f"{DISPLAYED_PROVIDER} is temporarily unavailable") from exc
            if resp.status_code in _TRANSIENT_STATUS and attempt < _MAX_RETRIES:
                await asyncio.sleep(_BACKOFF_S[min(attempt, len(_BACKOFF_S) - 1)])
                continue
            if resp.status_code != 200:
                raise ProviderError(f"{DISPLAYED_PROVIDER} returned an error")
            try:
                content = resp.json()["choices"][0]["message"]["content"]
            except (KeyError, IndexError, ValueError) as exc:
                raise ProviderError("The response was malformed") from exc
            if not content or not str(content).strip():
                if attempt < _MAX_RETRIES:
                    continue
                raise ProviderError("The model returned an empty response")
            try:
                return json.loads(_strip_fences(str(content)))
            except json.JSONDecodeError as exc:
                if attempt < _MAX_RETRIES:
                    continue
                raise ProviderError("The response was not valid JSON") from exc
    raise ProviderError(f"{DISPLAYED_PROVIDER} could not complete the request")
