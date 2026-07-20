"""Unit tests for the auth provider (fake) and the auth service."""
from __future__ import annotations

import pytest

from app.auth.jwt_verifier import JWTVerifier
from app.auth.providers.fake import FakeAuthProvider
from app.auth.providers.base import (
    InvalidCredentialsError,
    UserAlreadyExistsError,
)
from app.auth.schemas import SignInRequest, SignUpRequest
from app.auth.service import AuthService
from app.core.exceptions import ConflictError, UnauthorizedError


@pytest.fixture
def service() -> AuthService:
    provider = FakeAuthProvider("test-secret")
    verifier = JWTVerifier("test-secret")
    return AuthService(provider=provider, verifier=verifier)


async def test_signup_returns_user_and_tokens(service: AuthService) -> None:
    req = SignUpRequest(email="New@Example.com", password="password123", full_name="Neo")
    result = await service.sign_up(req)
    assert result.user.email == "new@example.com"
    assert result.tokens.access_token
    assert result.tokens.refresh_token


async def test_signup_duplicate_conflict(service: AuthService) -> None:
    req = SignUpRequest(email="dup@example.com", password="password123")
    await service.sign_up(req)
    with pytest.raises(ConflictError):
        await service.sign_up(req)
    # The underlying provider also raises its own error type.
    with pytest.raises(UserAlreadyExistsError):
        await service._provider.sign_up(email="dup@example.com", password="x")


async def test_signin_success(service: AuthService) -> None:
    await service.sign_up(SignUpRequest(email="u@e.com", password="password123"))
    result = await service.sign_in(SignInRequest(email="u@e.com", password="password123"))
    assert result.user.email == "u@e.com"


async def test_signin_wrong_password_unauthorized(service: AuthService) -> None:
    await service.sign_up(SignUpRequest(email="u@e.com", password="password123"))
    with pytest.raises(UnauthorizedError):
        await service.sign_in(SignInRequest(email="u@e.com", password="wrong"))


async def test_current_user_via_token(service: AuthService) -> None:
    res = await service.sign_up(SignUpRequest(email="t@e.com", password="password123"))
    user = await service.current_user(res.tokens.access_token)
    assert user.email == "t@e.com"


async def test_current_user_missing_token(service: AuthService) -> None:
    with pytest.raises(UnauthorizedError):
        await service.current_user(None)


async def test_signout_is_best_effort(service: AuthService) -> None:
    await service.sign_out(refresh_token=None)  # must not raise
