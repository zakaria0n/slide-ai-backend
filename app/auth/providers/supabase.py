"""Supabase-backed auth provider (production implementation).

Wraps the ``supabase-auth`` async client. The client is injected so the
provider is unit-testable with a fake. Only the access/refresh tokens and
the user identity are mapped into application entities; Supabase-specific
models never escape this module.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from app.auth.entities import AuthResult, TokenPair, User
from app.auth.providers.base import (
    AuthProvider,
    AuthProviderError,
    InvalidCredentialsError,
    UserAlreadyExistsError,
)
from app.core.exceptions import ProviderError

if TYPE_CHECKING:  # pragma: no cover
    pass


class SupabaseAuthProvider(AuthProvider):
    """AuthProvider implementation backed by Supabase Auth."""

    def __init__(self, client: object) -> None:
        # Typed as object to avoid a hard import on the concrete client
        # during tests; the expected shape is ``AsyncGoTrueClient``.
        self._client = client

    async def sign_up(
        self, *, email: str, password: str, full_name: str | None = None
    ) -> AuthResult:
        options = {}
        if full_name:
            options["data"] = {"full_name": full_name}
        try:
            resp = await self._client.sign_up(
                {
                    "email": email,
                    "password": password,
                    **({"options": options} if options else {}),
                }
            )
        except Exception as exc:  # noqa: BLE001 - provider boundary
            self._raise_from(exc)
        return self._to_result(resp)

    async def sign_in(self, *, email: str, password: str) -> AuthResult:
        try:
            resp = await self._client.sign_in_with_password(
                {"email": email, "password": password}
            )
        except Exception as exc:  # noqa: BLE001 - provider boundary
            self._raise_from(exc)
        return self._to_result(resp)

    async def sign_out(self, *, refresh_token: str | None = None) -> None:
        try:
            scope = "local"
            await self._client.sign_out(scope=scope, refresh_token=refresh_token)
        except Exception as exc:  # noqa: BLE001 - provider boundary
            # Sign-out is best-effort; a failure must not break the caller.
            if getattr(exc, "status", None) != 404:
                self._raise_from(exc, soft=True)

    async def get_user(self, *, access_token: str) -> User:
        try:
            resp = await self._client.get_user(access_token)
        except Exception as exc:  # noqa: BLE001 - provider boundary
            self._raise_from(exc, soft=True)
        user = getattr(resp, "user", None)
        if user is None:
            raise InvalidCredentialsError("Invalid or expired session")
        return self._to_user(user)

    # --- Mapping helpers ---

    def _to_result(self, resp: object) -> AuthResult:
        user = getattr(resp, "user", None)
        session = getattr(resp, "session", None)
        if user is None or session is None:
            raise AuthProviderError("Provider returned an incomplete response")
        return AuthResult(
            user=self._to_user(user),
            tokens=TokenPair(
                access_token=getattr(session, "access_token", ""),
                refresh_token=getattr(session, "refresh_token", ""),
                expires_in=getattr(session, "expires_in", None),
            ),
        )

    def _to_user(self, user: object) -> User:
        raw_id = getattr(user, "id", None) or uuid4()
        try:
            user_id = UUID(str(raw_id))
        except (ValueError, TypeError):
            user_id = uuid4()
        email = getattr(user, "email", "") or ""
        raw_meta = getattr(user, "user_metadata", None) or {}
        if not isinstance(raw_meta, dict):
            raw_meta = {}
        created_raw = getattr(user, "created_at", None)
        created = self._parse_dt(created_raw)
        return User(
            id=user_id,
            email=email,
            created_at=created,
            metadata=dict(raw_meta),
        )

    @staticmethod
    def _parse_dt(value: object) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str) and value:
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                return datetime.now(timezone.utc)
        return datetime.now(timezone.utc)

    @staticmethod
    def _raise_from(exc: Exception, *, soft: bool = False) -> None:
        msg = str(exc).lower()
        if "user already registered" in msg or "already exists" in msg:
            raise UserAlreadyExistsError("This email is already registered") from exc
        if "invalid login" in msg or "invalid credentials" in msg or "wrong password" in msg:
            raise InvalidCredentialsError("Invalid email or password") from exc
        if soft:
            raise InvalidCredentialsError("Invalid or expired session") from exc
        # Surface upstream failures as a provider error (masked to 'Slide AI').
        raise ProviderError(f"Auth provider error: {exc}") from exc
