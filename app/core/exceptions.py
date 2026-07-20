"""Domain and application exception hierarchy.

All custom exceptions derive from ``AppError``. They carry an HTTP status
code and a stable machine-readable ``code`` so the frontend can branch on
errors without parsing messages.
"""
from __future__ import annotations


class AppError(Exception):
    """Base class for all application errors."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict[str, str]:
        payload = {"error": self.code, "message": self.message}
        if self.detail:
            payload["detail"] = self.detail
        return payload


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"


class ProviderError(AppError):
    """Raised when the upstream AI provider fails.

    The real provider identity (OpenCode Zen) is never surfaced; callers
    see the abstract ``Slide AI`` provider name instead.
    """

    status_code = 502
    code = "provider_error"

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        provider_msg = message.replace("OpenCode Zen", "Slide AI")
        super().__init__(provider_msg, detail=detail)
