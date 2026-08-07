"""Simple in-memory rate limiter for AI generation endpoints.

Uses a sliding-window counter per user (identified by owner_id).
No external dependencies required.
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from app.core.exceptions import RateLimitError


@dataclass
class _Bucket:
    """Tracks request timestamps for a single user."""
    timestamps: list[float] = field(default_factory=list)


class RateLimiter:
    """In-memory sliding-window rate limiter."""

    def __init__(self, *, max_requests: int = 10, window_seconds: int = 60) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._buckets: dict[str, _Bucket] = defaultdict(_Bucket)

    def check(self, key: str) -> None:
        """Raise RateLimitError (429) if the key has exceeded the limit."""
        now = time.monotonic()
        bucket = self._buckets[key]

        # Prune timestamps outside the window.
        cutoff = now - self._window
        bucket.timestamps = [t for t in bucket.timestamps if t > cutoff]

        if len(bucket.timestamps) >= self._max:
            raise RateLimitError(
                f"Rate limit exceeded: {self._max} requests per {self._window}s. "
                "Please wait before trying again."
            )

        bucket.timestamps.append(now)


# Singleton instance used by the generation endpoint.
generation_limiter = RateLimiter(max_requests=10, window_seconds=60)
