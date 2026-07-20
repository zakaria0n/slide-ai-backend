"""Unit tests for the exception hierarchy and provider masking."""
from __future__ import annotations

import pytest

from app.core.exceptions import (
    AppError,
    BadRequestError,
    ForbiddenError,
    NotFoundError,
    ProviderError,
    UnauthorizedError,
    ValidationError,
)


def test_base_error_payload() -> None:
    err = AppError("boom", detail="extra")
    assert err.status_code == 500
    assert err.code == "internal_error"
    assert err.to_dict() == {"error": "internal_error", "message": "boom", "detail": "extra"}


def test_specific_status_codes() -> None:
    assert NotFoundError("x").status_code == 404
    assert ValidationError("x").status_code == 422
    assert UnauthorizedError("x").status_code == 401
    assert ForbiddenError("x").status_code == 403
    assert BadRequestError("x").status_code == 400


def test_provider_error_masks_internal_provider_name() -> None:
    """The internal provider (OpenCode Zen) must never leak to users."""
    err = ProviderError("OpenCode Zen returned 502")
    payload = err.to_dict()
    assert "OpenCode Zen" not in payload["message"]
    assert payload["message"] == "Slide AI returned 502"
    assert err.status_code == 502
    assert err.code == "provider_error"


def test_app_error_is_exception() -> None:
    with pytest.raises(AppError):
        raise NotFoundError("missing")
