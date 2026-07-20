"""Pydantic request/response schemas for the auth API."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


# --- Requests ---

class SignUpRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=120)


class SignInRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class SignOutRequest(BaseModel):
    """Optional refresh token to revoke; defaults to local session only."""

    refresh_token: str | None = None
    scope: str | None = None


# --- Responses ---

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int | None = None


class UserResponse(BaseModel):
    id: UUID
    email: str
    display_name: str
    created_at: datetime

    @classmethod
    def from_entity(cls, user: "User") -> "UserResponse":
        return cls(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            created_at=user.created_at,
        )


class AuthResponse(BaseModel):
    user: UserResponse
    tokens: TokenResponse


class MessageResponse(BaseModel):
    message: str
