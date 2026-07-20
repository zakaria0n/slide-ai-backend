"""Unit tests for the Supabase-backed auth provider.

Exercises :class:`SupabaseAuthProvider` against a fake async client so no
network or live Supabase project is required. Verifies mapping of the
provider's response models into application entities and error translation.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.auth.entities import AuthResult
from app.auth.providers.base import (
    InvalidCredentialsError,
    UserAlreadyExistsError,
)
from app.auth.providers.supabase import SupabaseAuthProvider
from app.core.exceptions import ProviderError, UnauthorizedError


def _user(uid, email="u@e.com", meta=None):
    return SimpleNamespace(id=str(uid), email=email, user_metadata=meta or {}, created_at="2026-01-01T00:00:00Z")


def _session(access="a", refresh="r", expires_in=3600):
    return SimpleNamespace(access_token=access, refresh_token=refresh, expires_in=expires_in)


def _client(sign_up=None, sign_in=None, sign_out=None, get_user=None):
    """Build a fake AsyncGoTrueClient-like object."""

    class FakeClient:
        async def sign_up(self, payload):
            return sign_up(payload)

        async def sign_in_with_password(self, payload):
            return sign_in(payload)

        async def sign_out(self, scope="local", refresh_token=None):
            return sign_out(scope, refresh_token) if sign_out else None

        async def get_user(self, token):
            return get_user(token)

    return FakeClient()


async def test_sign_up_maps_result() -> None:
    uid = uuid4()
    client = _client(
        sign_up=lambda p: SimpleNamespace(user=_user(uid, "new@e.com", {"full_name": "Neo"}), session=_session())
    )
    provider = SupabaseAuthProvider(client)
    result: AuthResult = await provider.sign_up(email="new@e.com", password="pw", full_name="Neo")
    assert result.user.email == "new@e.com"
    assert result.user.display_name == "Neo"
    assert result.tokens.access_token == "a"


async def test_sign_in_maps_result() -> None:
    uid = uuid4()
    client = _client(
        sign_in=lambda p: SimpleNamespace(user=_user(uid), session=_session("tok", "ref"))
    )
    provider = SupabaseAuthProvider(client)
    result = await provider.sign_in(email="u@e.com", password="pw")
    assert result.tokens.access_token == "tok"
    assert result.tokens.refresh_token == "ref"


async def test_sign_up_duplicate_raises_conflict() -> None:
    def boom(payload):
        raise RuntimeError("User already registered")
    provider = SupabaseAuthProvider(_client(sign_up=boom))
    try:
        await provider.sign_up(email="x@e.com", password="pw")
        assert False, "expected error"
    except UserAlreadyExistsError:
        pass


async def test_sign_in_bad_password_raises_invalid() -> None:
    def boom(payload):
        raise RuntimeError("Invalid login credentials")
    provider = SupabaseAuthProvider(_client(sign_in=boom))
    try:
        await provider.sign_in(email="x@e.com", password="wrong")
        assert False, "expected error"
    except InvalidCredentialsError:
        pass


async def test_get_user_maps_from_token() -> None:
    uid = uuid4()
    client = _client(get_user=lambda t: SimpleNamespace(user=_user(uid, "g@e.com")))
    provider = SupabaseAuthProvider(client)
    user = await provider.get_user(access_token="sometoken")
    assert user.id == uid
    assert user.email == "g@e.com"


async def test_unexpected_provider_error_is_masked() -> None:
    def boom(payload):
        raise RuntimeError("internal 500")
    provider = SupabaseAuthProvider(_client(sign_up=boom))
    try:
        await provider.sign_up(email="x@e.com", password="pw")
        assert False, "expected error"
    except ProviderError as exc:
        # The provider name must never leak.
        assert "OpenCode" not in str(exc)
        assert "Zen" not in str(exc)


async def test_sign_out_best_effort() -> None:
    provider = SupabaseAuthProvider(_client())
    await provider.sign_out(refresh_token="r")  # must not raise
