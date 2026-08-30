"""Authentication routes.

Endpoints:
- POST /api/v1/auth/signup  -> create account, return user + tokens
- POST /api/v1/auth/signin   -> authenticate, return user + tokens
- POST /api/v1/auth/signout  -> invalidate session
- GET  /api/v1/auth/me       -> current authenticated user

Routes contain no business logic; they delegate to :class:`AuthService`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.deps import extract_token
from app.api.deps import extract_token
from fastapi import HTTPException
from pydantic import BaseModel
from app.auth.schemas import (
    AuthResponse,
    MessageResponse,
    SignInRequest,
    SignOutRequest,
    SignUpRequest,
    UpdateProfileRequest,
    UserResponse,
)
from app.auth.service import AuthService
from app.core.config import Settings

router = APIRouter(prefix="/auth", tags=["auth"])


class RefreshRequest(BaseModel):
    refresh_token: str


class DeviceAuthorizeRequest(BaseModel):
    user_code: str


class DevicePollRequest(BaseModel):
    device_code: str


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
    from app.auth.providers.fake import FakeAuthProvider
    from app.auth.service import AuthService

    verifier = getattr(request.app.state, "jwt_verifier", None)
    if verifier is None:
        from app.auth.jwt_verifier import JWTVerifier
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
    token: str = Depends(extract_token),
    service: AuthService = Depends(_service),
) -> UserResponse:
    user = await service.current_user(token)
    return UserResponse.from_entity(user)


@router.post("/mcp-token")
async def create_mcp_token(
    request: Request,
    token: str = Depends(extract_token),
) -> dict:
    """Mint a personal access token for MCP clients (72h validity).

    Long-lived on purpose: AI coding tools configured with the session's
    1h login token would silently break at every reconnection. Requires an
    authenticated session; the minted token carries the same identity.
    """
    verifier = getattr(request.app.state, "jwt_verifier", None)
    if verifier is None:
        from app.auth.jwt_verifier import JWTVerifier

        settings: Settings = _app_settings(request)
        verifier = JWTVerifier(settings.supabase_jwt_secret or "dev-insecure-secret")
    user = verifier.to_user(token)
    expires_in = 30 * 24 * 3600  # 30 days
    full_name = (user.metadata or {}).get("full_name")
    access_token = verifier.mint_access_token(
        user.id, user.email, expires_in_seconds=expires_in,
        full_name=str(full_name) if full_name else None,
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "purpose": "mcp",
    }


@router.post("/refresh")
async def refresh_session(req: RefreshRequest, request: Request) -> dict:
    """Refresh a Supabase session (rotates the refresh token).

    Keeps web sessions alive for as long as the refresh token stays valid —
    the frontend calls this automatically before the access token expires.
    """
    import httpx

    settings: Settings = _app_settings(request)
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(status_code=501, detail="Session refresh is not configured")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{settings.supabase_url}/auth/v1/token?grant_type=refresh_token",
            headers={"apikey": settings.supabase_anon_key, "Content-Type": "application/json"},
            json={"refresh_token": req.refresh_token},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    body = resp.json()
    return {
        "access_token": body.get("access_token"),
        "refresh_token": body.get("refresh_token"),
        "expires_in": body.get("expires_in"),
        "user": body.get("user"),
    }


@router.post("/device/start")
async def device_start(request: Request) -> dict:
    """Start a device-flow pairing: the CLI shows a code, the user approves
    it in the browser — no manual token copy-paste."""
    from app.auth.device_flow import start_pairing

    settings: Settings = _app_settings(request)
    frontend = settings.resolved_frontend_origin
    pairing = start_pairing()
    return {
        "device_code": pairing["device_code"],
        "user_code": pairing["user_code"],
        "verification_url": f"{frontend}/oauth/device?user_code={pairing['user_code']}",
        "expires_in": pairing["expires_in"],
        "interval": 2,
    }


@router.post("/device/authorize")
async def device_authorize(
    req: DeviceAuthorizeRequest,
    request: Request,
    token: str = Depends(extract_token),
) -> dict:
    from app.auth.device_flow import approve
    from app.core.exceptions import NotFoundError

    verifier = getattr(request.app.state, "jwt_verifier", None)
    if verifier is None:
        from app.auth.jwt_verifier import JWTVerifier

        verifier = JWTVerifier(_app_settings(request).supabase_jwt_secret or "dev-insecure-secret")
    user = verifier.to_user(token)
    full_name = (user.metadata or {}).get("full_name")
    access_token = verifier.mint_access_token(
        user.id, user.email, expires_in_seconds=30 * 24 * 3600,
        full_name=str(full_name) if full_name else None, token_type="mcp",
    )
    try:
        approve(req.user_code, user_id=user.id, email=user.email, access_token=access_token)
    except KeyError as exc:
        raise NotFoundError("Unknown or expired device code") from exc
    return {"status": "approved"}


@router.post("/device/poll")
async def device_poll(req: DevicePollRequest, request: Request) -> dict:
    from app.auth.device_flow import poll

    settings: Settings = _app_settings(request)
    result = poll(req.device_code, settings.supabase_jwt_secret or "dev-insecure-secret")
    if result is None:
        raise HTTPException(status_code=404, detail="Unknown or expired device code")
    return result


@router.patch("/me", response_model=UserResponse)
async def update_me(
    req: UpdateProfileRequest,
    token: str = Depends(extract_token),
    service: AuthService = Depends(_service),
) -> UserResponse:
    user = await service.update_profile(token, req.full_name)
    return UserResponse.from_entity(user)


def _tokens(pair):  # type: ignore[no-untyped-def]
    from app.auth.schemas import TokenResponse

    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.expires_in,
    )
