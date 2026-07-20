"""Unit tests for JWT verification."""
from __future__ import annotations

import jwt
import pytest
from jwt import PyJWK

from app.auth.jwt_verifier import JWTVerifier
from app.core.exceptions import UnauthorizedError


def _make_token(secret: str, *, sub: str, exp: object = None, email: str = "") -> str:
    claims = {"sub": sub, "email": email}
    if exp is not None:
        claims["exp"] = exp
    return jwt.encode(claims, secret, algorithm="HS256")


def test_verifier_accepts_valid_token() -> None:
    secret = "unit-test-secret"
    verifier = JWTVerifier(secret)
    token = _make_token(secret, sub="123e4567-e89b-12d3-a456-426614174000", email="a@b.co")
    user = verifier.to_user(token)
    assert str(user.id) == "123e4567-e89b-12d3-a456-426614174000"
    assert user.email == "a@b.co"


def test_verifier_rejects_expired_token() -> None:
    import time

    secret = "unit-test-secret"
    verifier = JWTVerifier(secret)
    token = _make_token(secret, sub="abc", exp=int(time.time()) - 10)
    with pytest.raises(UnauthorizedError):
        verifier.to_user(token)


def test_verifier_rejects_wrong_secret() -> None:
    verifier = JWTVerifier("right-secret")
    token = _make_token("wrong-secret", sub="abc")
    with pytest.raises(UnauthorizedError):
        verifier.to_user(token)


def test_verifier_rejects_malformed() -> None:
    verifier = JWTVerifier("secret")
    with pytest.raises(UnauthorizedError):
        verifier.to_user("not-a-jwt")


def test_verifier_rejects_missing_sub() -> None:
    secret = "secret"
    token = jwt.encode({"email": "x@y.z"}, secret, algorithm="HS256")
    verifier = JWTVerifier(secret)
    with pytest.raises(UnauthorizedError):
        verifier.to_user(token)


def test_verifier_requires_secret() -> None:
    with pytest.raises(ValueError):
        JWTVerifier("")


def test_pyjwk_supported() -> None:
    # Sanity check that PyJWK is importable (used by the verifier).
    assert PyJWK.from_dict({"k": "secret", "kty": "oct"}) is not None
