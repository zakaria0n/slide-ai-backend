"""Auth domain entities.

Plain dataclasses (no ORM coupling) describing the auth concepts the
application cares about. These are returned by the auth provider and
consumed by the service layer, keeping Supabase's client models out of
the rest of the codebase.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class User:
    """An authenticated application user."""

    id: UUID
    email: str
    created_at: datetime = field(default_factory=_utcnow)
    # Arbitrary Supabase user metadata (display name, avatar, etc.).
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        name = self.metadata.get("full_name") or self.metadata.get("name")
        return str(name) if name else self.email


@dataclass(frozen=True)
class TokenPair:
    """Access + refresh tokens returned on sign-up / sign-in."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int | None = None


@dataclass(frozen=True)
class AuthResult:
    """Combined result of an authentication operation."""

    user: User
    tokens: TokenPair
