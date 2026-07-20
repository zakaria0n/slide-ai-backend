"""Local verification of Supabase-issued JWT access tokens.

Supabase signs access tokens with HS256 using the project JWT secret.
Verifying them locally (no network round-trip) keeps the request path
fast and removes a dependency on the auth service for every request.

The application only reads the ``sub`` claim (user id) and optionally
``email``. Token issuance remains the provider's responsibility.
"""
from __future__ import annotations

import jwt
from jwt.exceptions import (
    DecodeError,
    InvalidKeyError,
    ExpiredSignatureError,
    InvalidSignatureError,
    InvalidTokenError,
)
from uuid import UUID

from app.auth.entities import User
from app.core.exceptions import UnauthorizedError


class JWTVerifier:
    """Verifies HS256 JWTs issued by Supabase."""

    def __init__(self, secret: str, *, leeway_seconds: int = 10) -> None:
        if not secret:
            raise ValueError("JWT secret is required to verify tokens")
        # HS256 verifies against the raw secret string.
        self._secret = secret
        self._leeway = leeway_seconds

    def _verify(self, token: str) -> dict[str, object]:
        """Return the decoded claims, or raise UnauthorizedError."""
        try:
            claims = jwt.decode(
                token,
                self._secret,  # type: ignore[arg-type]
                algorithms=["HS256"],
                options={"require": ["sub"]},
                leeway=self._leeway,
            )
        except ExpiredSignatureError as exc:
            raise UnauthorizedError("Session expired") from exc
        except (InvalidSignatureError, InvalidKeyError, DecodeError) as exc:
            raise UnauthorizedError("Invalid token") from exc
        except InvalidTokenError as exc:
            raise UnauthorizedError("Malformed token") from exc
        return claims

    def user_id(self, token: str) -> UUID:
        # Verify once and reuse the decoded claims.
        claims = self._verify(token)
        raw = str(claims.get("sub", ""))
        try:
            return UUID(raw)
        except ValueError as exc:
            raise UnauthorizedError("Token has no valid subject") from exc

    def to_user(self, token: str) -> User:
        """Build a lightweight User from token claims (no provider call)."""
        claims = self._verify(token)
        uid = self.user_id_from(claims)
        email = str(claims.get("email", ""))
        meta: dict[str, object] = {}
        if "full_name" in claims:
            meta["full_name"] = claims["full_name"]
        return User(id=uid, email=email, metadata=meta)

    def user_id_from(self, claims: dict[str, object]) -> UUID:
        raw = str(claims.get("sub", ""))
        try:
            return UUID(raw)
        except ValueError as exc:
            raise UnauthorizedError("Token has no valid subject") from exc
