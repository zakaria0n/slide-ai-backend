"""Auth service — the only place holding authentication business logic.

Routes must call this service; the service calls the (abstracted) auth
provider and the JWT verifier. No Supabase models or JWT libraries
appear in the route layer.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.auth.entities import User
from app.auth.jwt_verifier import JWTVerifier
from app.auth.providers.base import (
    AuthProvider,
    InvalidCredentialsError,
    UserAlreadyExistsError,
)
from app.auth.schemas import SignInRequest, SignUpRequest
from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    UnauthorizedError,
)

if TYPE_CHECKING:  # pragma: no cover
    pass


class AuthService:
    """Orchestrates sign-up, sign-in, sign-out and current-user."""

    def __init__(self, provider: AuthProvider, verifier: JWTVerifier) -> None:
        self._provider = provider
        self._verifier = verifier

    async def sign_up(self, req: SignUpRequest):
        email = req.email.strip().lower()
        try:
            result = await self._provider.sign_up(
                email=email,
                password=req.password,
                full_name=req.full_name,
            )
        except UserAlreadyExistsError as exc:
            raise ConflictError(str(exc)) from exc
        return result

    async def sign_in(self, req: SignInRequest):
        try:
            result = await self._provider.sign_in(
                email=req.email.strip().lower(),
                password=req.password,
            )
        except InvalidCredentialsError as exc:
            raise UnauthorizedError(str(exc)) from exc
        return result

    async def sign_out(self, refresh_token: str | None) -> None:
        await self._provider.sign_out(refresh_token=refresh_token)

    async def current_user(self, access_token: str | None) -> User:
        if not access_token:
            raise UnauthorizedError("Missing authentication token")
        try:
            return self._verifier.to_user(access_token)
        except UnauthorizedError:
            # Fall back to the provider only if local verification failed but
            # a token was supplied (e.g. clock skew handled by provider).
            raise
