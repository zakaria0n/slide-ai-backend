"""In-memory auth provider for tests and offline development.

Implements :class:`AuthProvider` without any network calls. Tokens are
opaque random strings; password verification is a plain equality check
(never use this in production — it exists only so the suite runs with no
Supabase instance).
"""
from __future__ import annotations

import secrets
import jwt
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from app.auth.entities import AuthResult, TokenPair, User
from app.auth.providers.base import (
    AuthProvider,
    InvalidCredentialsError,
    UserAlreadyExistsError,
)

if TYPE_CHECKING:  # pragma: no cover
    pass


def _make_token() -> str:
    return secrets.token_urlsafe(32)


class FakeAuthProvider(AuthProvider):
    """Volatile in-memory user store."""

    def __init__(self, secret: str = "dev-insecure-secret") -> None:
        self._secret = secret
        # email -> (password, User)
        self._users: dict[str, tuple[str, User]] = {}
        # access_token -> user id
        self._sessions: dict[str, UUID] = {}

    async def sign_up(
        self, *, email: str, password: str, full_name: str | None = None
    ) -> AuthResult:
        key = email.lower()
        if key in self._users:
            raise UserAlreadyExistsError(f"Email already registered: {email}")
        user = User(
            id=uuid4(),
            email=email,
            created_at=datetime.now(timezone.utc),
            metadata={"full_name": full_name} if full_name else {},
        )
        self._users[key] = (password, user)
        tokens = self._issue(user)
        return AuthResult(user=user, tokens=tokens)

    async def sign_in(self, *, email: str, password: str) -> AuthResult:
        key = email.lower()
        stored = self._users.get(key)
        if stored is None or stored[0] != password:
            raise InvalidCredentialsError("Invalid email or password")
        tokens = self._issue(stored[1])
        return AuthResult(user=stored[1], tokens=tokens)

    async def sign_out(self, *, refresh_token: str | None = None) -> None:
        # Best-effort: drop any session tied to the supplied refresh token.
        if refresh_token and refresh_token in self._sessions:
            del self._sessions[refresh_token]

    async def get_user(self, *, access_token: str) -> User:
        user_id = self._sessions.get(access_token)
        if user_id is None:
            raise InvalidCredentialsError("Invalid or expired session")
        for _pwd, user in self._users.values():
            if user.id == user_id:
                return user
        raise InvalidCredentialsError("Invalid or expired session")

    def _issue(self, user: User) -> TokenPair:
        claims = {"sub": str(user.id), "email": user.email}
        access = jwt.encode(claims, self._secret, algorithm="HS256")
        refresh = jwt.encode(claims, self._secret, algorithm="HS256")
        self._sessions[access] = user.id
        self._sessions[refresh] = user.id
        return TokenPair(access_token=access, refresh_token=refresh)
