"""Auth provider abstraction.

The application depends only on :class:`AuthProvider`. The concrete
implementation (Supabase, or an in-memory fake for tests/offline dev)
is selected by the DI container. This keeps Supabase client models out of
the service and route layers.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.auth.entities import AuthResult, User


class AuthProvider(ABC):
    """Contract for authentication backends."""

    @abstractmethod
    async def sign_up(
        self, *, email: str, password: str, full_name: str | None = None
    ) -> AuthResult:
        """Create a new user and return its identity + tokens."""

    @abstractmethod
    async def sign_in(self, *, email: str, password: str) -> AuthResult:
        """Authenticate an existing user and return tokens."""

    @abstractmethod
    async def sign_out(self, *, refresh_token: str | None = None) -> None:
        """Invalidate the given session (best-effort)."""

    @abstractmethod
    async def get_user(self, *, access_token: str) -> User:
        """Resolve a user from an access token."""


class UserAlreadyExistsError(Exception):
    """Raised when sign-up collides with an existing email."""


class InvalidCredentialsError(Exception):
    """Raised on failed sign-in (wrong email/password)."""


class AuthProviderError(Exception):
    """Raised on unexpected provider failures."""
