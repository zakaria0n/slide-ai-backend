"""Vision-capability probing for AI models.

Whether a model can actually READ images varies per model and per API key
(the free tier of the provider, for example, serves text-only endpoints for
every model). Instead of guessing from model names, we probe once per model
with a trivial red/blue image and cache the verdict for an hour.

Probe design notes:
* HTTP status alone is NOT enough — some text-only models answer image
  messages with 200 and simply ignore the picture (the answer then lives in
  reasoning content and says "I cannot see"). So the verdict ALSO inspects
  the answer: a model that sees must name the left-half color, and must not
  be apologizing about being unable to see.
"""
from __future__ import annotations

import logging
import re
import time

import httpx

from app.core.config import Settings

logger = logging.getLogger("slideai.vision")

_CACHE_TTL_SECONDS = 3600.0
_verdict_cache: dict[str, tuple[bool, float]] = {}

# 64x64 PNG: solid red left half, solid blue right half.
_PROBE_IMAGE = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAVUlEQVR4nO3PMQ0AMAgAMERwo2T+lRB0IGEXX5MaaHTVqXxzKgQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEfhY6YbEPEWbFTgAAAABJRU5ErkJggg=="
)

_PROBE_QUESTION = (
    "Look at the image: the LEFT half and the RIGHT half have different solid "
    "colors. Answer with ONLY the color of the LEFT half, one word."
)

_SEES_COLOR_RE = re.compile(r"\b(red|rouge)\b", re.IGNORECASE)
_CANNOT_SEE_RE = re.compile(
    r"cannot see|can't see|unable to see|not able to see|no image|"
    "don't see any|do not see any|ne peux pas voir|ne peut pas voir|"
    "je ne vois pas|text-only|as a text",
    re.IGNORECASE,
)


def interpret_probe_response(status_code: int, content: str, reasoning: str) -> bool:
    """Decide whether a probe reply proves real image understanding."""
    if status_code != 200:
        return False
    text = f"{content} {reasoning}"
    if _CANNOT_SEE_RE.search(text):
        return False
    return bool(_SEES_COLOR_RE.search(text))


async def supports_vision(settings: Settings, model: str) -> bool:
    """Whether ``model`` genuinely reads image content (probed, then cached)."""
    cached = _verdict_cache.get(model)
    now = time.monotonic()
    if cached and now - cached[1] < _CACHE_TTL_SECONDS:
        return cached[0]

    sees = False
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                f"{settings.ai_provider_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.ai_provider_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": _PROBE_QUESTION},
                                {"type": "image_url", "image_url": {"url": _PROBE_IMAGE}},
                            ],
                        }
                    ],
                    "max_tokens": 60,
                },
            )
            if resp.status_code == 200:
                message = resp.json()["choices"][0]["message"]
                sees = interpret_probe_response(
                    resp.status_code,
                    str(message.get("content") or ""),
                    str(message.get("reasoning_content") or message.get("reasoning") or ""),
                )
            else:
                logger.info(
                    "vision probe %s -> HTTP %s", model, resp.status_code
                )
    except Exception as exc:  # noqa: BLE001 — probe must never break chat
        logger.warning("vision probe %s failed: %s", model, exc)

    _verdict_cache[model] = (sees, now)
    logger.info("vision probe %s -> %s", model, "VISION" if sees else "text-only")
    return sees
