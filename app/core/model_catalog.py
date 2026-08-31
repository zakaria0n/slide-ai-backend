"""Model catalog for the AI provider.

The provider (surfaced to users only as "Slide AI") exposes an OpenAI
compatible ``GET /models`` endpoint. This module:

* fetches that catalog with a small TTL cache so settings pages can list the
  models users may pick from,
* falls back to a static snapshot when the provider is unreachable,
* resolves a user-selected model id against the catalog.

Models are only *validated* here — the concrete id travels to the provider
unchanged. Which ids actually work depends on the configured API key
(e.g. the shared public key only serves the ``-free`` tier).
"""
from __future__ import annotations

import time
import logging
from typing import Any

import httpx

from app.core.config import Settings
from app.core.exceptions import ValidationError

logger = logging.getLogger("slideai.model_catalog")

# Static snapshot of the provider catalog (2026-08). Used when the upstream
# /models endpoint cannot be reached so the settings page always has a list.
STATIC_MODELS: list[str] = [
    "claude-fable-5",
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-opus-4-5",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
    "claude-sonnet-4-5",
    "claude-sonnet-4",
    "claude-haiku-4-5",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.1-pro",
    "gemini-3-flash",
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.5",
    "gpt-5.5-pro",
    "gpt-5.4",
    "gpt-5.4-pro",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5.3-codex-spark",
    "gpt-5.3-codex",
    "gpt-5.2",
    "gpt-5.2-codex",
    "gpt-5.1",
    "gpt-5.1-codex-max",
    "gpt-5.1-codex",
    "gpt-5.1-codex-mini",
    "gpt-5",
    "gpt-5-codex",
    "gpt-5-nano",
    "grok-build-0.1",
    "grok-4.6",
    "grok-4.5",
    "muse-spark-1.2",
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "glm-5.2",
    "glm-5.1",
    "glm-5",
    "minimax-m3",
    "minimax-m2.7",
    "minimax-m2.5",
    "kimi-k3",
    "kimi-k2.7-code",
    "kimi-k2.6",
    "kimi-k2.5",
    "qwen3.6-plus",
    "qwen3.5-plus",
    "big-pickle",
    "deepseek-v4-flash-free",
    "muse-spark-1.2-contributor-free",
    "mimo-v2.5-free",
    "hy3-free",
    "ling-3.0-flash-fin-free",
    "nemotron-3-ultra-free",
    "nemotron-3.5-lightning-free",
    "laguna-s-2.1-free",
]

_CACHE_TTL_SECONDS = 300.0
_cache: dict[str, Any] = {"ids": None, "fetched_at": 0.0}

# With the shared free key, only these models actually work. Everything else
# (paid ids) is hidden from the catalog and rejected on use — unless
# allow_paid_models is enabled (paid key).
_FREE_SUFFIX = "-free"
_PUBLIC_MODEL_IDS = {"big-pickle"}


def _is_public_model(model_id: str) -> bool:
    return model_id.endswith(_FREE_SUFFIX) or model_id in _PUBLIC_MODEL_IDS


def _apply_policy(settings: Settings, ids: list[str]) -> list[str]:
    if settings.allow_paid_models:
        return list(ids)
    return [m for m in ids if _is_public_model(m)]


async def list_model_ids(settings: Settings) -> list[str]:
    """Return the provider's model ids, cached for a few minutes.

    Falls back to the static snapshot (and then to whatever the operator
    allowlisted) when the upstream request fails. The free-key policy
    (big-pickle + *-free only) is applied on every code path.
    """
    now = time.monotonic()
    if _cache["ids"] is not None and now - _cache["fetched_at"] < _CACHE_TTL_SECONDS:
        return _apply_policy(settings, list(_cache["ids"]))

    ids: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{settings.ai_provider_base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {settings.ai_provider_api_key}"},
            )
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                ids = [m["id"] for m in data if isinstance(m, dict) and m.get("id")]
    except Exception as exc:  # pragma: no cover - network dependent
        logger.warning("model catalog fetch failed, using static snapshot: %s", exc)

    if not ids:
        ids = list(STATIC_MODELS)

    if not settings.allow_paid_models:
        ids = [m for m in ids if _is_public_model(m)]
    return ids

    # The operator allowlist, when set, narrows the catalog (it never widens
    # it — ids outside the provider catalog cannot be invoked anyway).
    allowed = settings.ai_allowed_models
    if allowed:
        allowed_set = set(allowed)
        ids = [m for m in ids if m in allowed_set] or list(allowed)

    _cache["ids"] = list(ids)
    _cache["fetched_at"] = now
    return _apply_policy(settings, list(ids))


async def list_models(settings: Settings) -> list[dict[str, str]]:
    """Model catalog formatted for the API response."""
    ids = await list_model_ids(settings)
    return [{"id": i, "owned_by": "opencode"} for i in ids]


async def resolve_model(settings: Settings, requested: str | None) -> str:
    """Validate a user-selected model id, returning the id to use.

    ``None``/empty → the configured default. Unknown ids raise
    :class:`ValidationError` so callers return a clear 4xx instead of a
    confusing upstream error mid-stream.
    """
    default = settings.ai_provider_default_model
    if not requested or requested == default:
        return default
    ids = await list_model_ids(settings)
    if requested in ids:
        return requested
    raise ValidationError(
        f"Model '{requested}' is not available. Pick one from GET /api/v1/models."
    )
