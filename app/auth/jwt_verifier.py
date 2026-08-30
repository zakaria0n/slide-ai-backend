"""Local verification of Supabase-issued JWT access tokens.

Supabase signs access tokens with ES256 (asymmetric, JWKS) on newer
projects, or HS256 (symmetric secret) on older/legacy projects.

This verifier supports both: it first tries ES256 via the project's
JWKS endpoint, and falls back to HS256 when the token header says so.
JWKS keys are cached in memory by ``PyJWKClient``.
"""
from __future__ import annotations

import jwt
from jwt import PyJWKClient
from jwt.exceptions import (
    DecodeError,
    ExpiredSignatureError,
    InvalidAudienceError,
    InvalidSignatureError,
    InvalidTokenError,
    InvalidKeyError,
)
from uuid import UUID

from app.auth.entities import User
from app.core.exceptions import UnauthorizedError


class JWTVerifier:
    """Verifies Supabase JWTs (ES256 via JWKS or HS256 via secret)."""

    def __init__(
        self,
        secret: str,
        supabase_url: str = "",
        *,
        leeway_seconds: int = 10,
    ) -> None:
        if not secret:
            raise ValueError("JWT secret is required to verify tokens")
        self._secret = secret
        self._supabase_url = supabase_url.rstrip("/")
        self._leeway = leeway_seconds

        if self._supabase_url:
            jwks_uri = f"{self._supabase_url}/auth/v1/.well-known/jwks.json"
            self._jwks_client = PyJWKClient(jwks_uri, cache_keys=True)
        else:
            self._jwks_client = None

    # --- public API ---

    def _verify(self, token: str) -> dict[str, object]:
        """Return the decoded claims, or raise UnauthorizedError."""
        try:
            header = jwt.get_unverified_header(token)
            alg = header.get("alg", "HS256")
            kid = header.get("kid")

            if alg == "ES256" and kid and self._jwks_client:
                key = self._jwks_client.get_signing_key_from_jwt(token).key
                claims = jwt.decode(
                    token,
                    key,
                    algorithms=["ES256"],
                    audience="authenticated",
                    options={"require": ["sub"]},
                    leeway=self._leeway,
                )
            else:
                claims = jwt.decode(
                    token,
                    self._secret,
                    algorithms=["HS256"],
                    audience="authenticated",
                    options={"require": ["sub"]},
                    leeway=self._leeway,
                )
        except ExpiredSignatureError as exc:
            raise UnauthorizedError("Session expired") from exc
        except (InvalidSignatureError, InvalidKeyError, DecodeError, InvalidAudienceError) as exc:
            raise UnauthorizedError("Invalid token") from exc
        except InvalidTokenError as exc:
            raise UnauthorizedError("Malformed token") from exc
        return claims

    def user_id(self, token: str) -> UUID:
        claims = self._verify(token)
        raw = str(claims.get("sub", ""))
        try:
            return UUID(raw)
        except ValueError as exc:
            raise UnauthorizedError("Token has no valid subject") from exc

    def to_user(self, token: str) -> User:
        """Build a lightweight User from token claims (no provider call)."""
        claims = self._verify(token)
        uid = self._user_id_from(claims)
        email = str(claims.get("email", ""))
        meta: dict[str, object] = {}
        if "full_name" in claims:
            meta["full_name"] = claims["full_name"]
        return User(id=uid, email=email, metadata=meta)

    def mint_access_token(self, user_id: UUID, email: str, *, expires_in_seconds: int, full_name: str | None = None) -> str:
        """Mint a long-lived access token signed with the same secret and
        audience as the session verifier.

        Used for personal access tokens (e.g. a 72h MCP token) so external
        tools keep working without refreshing a 1h login session.
        """
        import time as _time

        now = int(_time.time())
        claims: dict[str, object] = {
            "sub": str(user_id),
            "email": email,
            "role": "authenticated",
            "aud": "authenticated",
            "iat": now,
            "exp": now + expires_in_seconds,
        }
        if full_name:
            claims["full_name"] = full_name
        return jwt.encode(claims, self._secret, algorithm="HS256")

    @staticmethod
    def _user_id_from(claims: dict[str, object]) -> UUID:
        raw = str(claims.get("sub", ""))
        try:
            return UUID(raw)
        except ValueError as exc:
            raise UnauthorizedError("Token has no valid subject") from exc
