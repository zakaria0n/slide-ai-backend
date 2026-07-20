"""Authentication routes.

Endpoints:
- POST /api/v1/auth/signup  -> create account, return user + tokens
- POST /api/v1/auth/signin   -> authenticate, return user + tokens
- POST /api/v1/auth/signout  -> invalidate session
- GET  /api/v1/auth/me       -> current authenticated user

Routes contain no business logic; they delegate to :class:`AuthService`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.auth.schemas import (
    AuthResponse,
    MessageResponse,
    SignInRequest,
    SignOutRequest,
    SignUpRequest,
    UserResponse,
)
from app.auth.service import AuthService
from app.core.config import Settings

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


def _extract_token(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str | None:
    return creds.credentials if creds else None


def _app_settings(request: Request) -> Settings:
    """Resolve the per-application settings from app.state."""
    return request.app.state.settings


def _service(
    request: Request,
    settings: Settings = Depends(_app_settings),
) -> AuthService:
    """Resolve the auth service.

    The provider is shared per-application via ``app.state`` so an
    in-memory provider keeps its state across requests. Production wiring
    replaces this with the Supabase-backed provider through the DI container.
    """
    from app.auth.jwt_verifier import JWTVerifier
    from app.auth.providers.fake import FakeAuthProvider
    from app.auth.service import AuthService

    secret = settings.supabase_jwt_secret or "dev-insecure-secret"
    verifier = JWTVerifier(secret)
    provider = getattr(request.app.state, "auth_provider", None)
    if provider is None:
        provider = FakeAuthProvider(secret)
    return AuthService(provider=provider, verifier=verifier)


@router.post("/signup", response_model=AuthResponse, status_code=201)
async def signup(
    req: SignUpRequest,
    service: AuthService = Depends(_service),
) -> AuthResponse:
    result = await service.sign_up(req)
    return AuthResponse(
        user=UserResponse.from_entity(result.user),
        tokens=_tokens(result.tokens),
    )


@router.post("/signin", response_model=AuthResponse)
async def signin(
    req: SignInRequest,
    service: AuthService = Depends(_service),
) -> AuthResponse:
    result = await service.sign_in(req)
    return AuthResponse(
        user=UserResponse.from_entity(result.user),
        tokens=_tokens(result.tokens),
    )


@router.post("/signout", response_model=MessageResponse)
async def signout(
    req: SignOutRequest | None = None,
    service: AuthService = Depends(_service),
) -> MessageResponse:
    refresh = req.refresh_token if req else None
    await service.sign_out(refresh_token=refresh)
    return MessageResponse(message="Signed out")


@router.get("/me", response_model=UserResponse)
async def me(
    token: str | None = Depends(_extract_token),
    service: AuthService = Depends(_service),
) -> UserResponse:
    user = await service.current_user(token)
    return UserResponse.from_entity(user)


def _tokens(pair):  # type: ignore[no-untyped-def]
    from app.auth.schemas import TokenResponse

    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.expires_in,
    )
