"""Shared FastAPI dependencies used across all route modules.

Centralises token extraction, owner resolution, and Supabase client
access so they are defined once instead of copy-pasted per router.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import AsyncClient

from app.core.exceptions import UnauthorizedError

_bearer = HTTPBearer(auto_error=False)


def extract_token(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Return the raw Bearer token string or raise 401."""
    if creds is None or not creds.credentials:
        raise UnauthorizedError("Missing authentication token")
    return creds.credentials


def owner_id(request: Request, token: str = Depends(extract_token)) -> UUID:
    """Resolve the authenticated user's UUID from the JWT."""
    verifier = getattr(request.app.state, "jwt_verifier", None)
    if verifier is None:
        raise UnauthorizedError("Authentication is not configured")
    return verifier.user_id(token)


def user_email(request: Request, token: str = Depends(extract_token)) -> str:
    """Return the authenticated user's email from the JWT (lowercased)."""
    verifier = getattr(request.app.state, "jwt_verifier", None)
    if verifier is None:
        raise UnauthorizedError("Authentication is not configured")
    return verifier.to_user(token).email.lower()


def supabase(request: Request) -> AsyncClient:
    """Return the application-wide Supabase AsyncClient."""
    return request.app.state.supabase
