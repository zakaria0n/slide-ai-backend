"""Minimal OAuth2 Authorization Server for MCP clients (Claude Code / ZKR).

Implements just enough of the spec for clients that auto-discover auth:
dynamic client registration, authorization-code + PKCE (S256/plain), and a
refresh-token grant. Access/refresh tokens are our own 30-day HS256 tokens.

Flow:
1. Client GETs /.well-known/oauth-protected-resource (advertised on 401).
2. Client registers (POST /oauth/register) and opens
   GET /oauth/authorize?... — we 302 to the web consent page.
3. The logged-in user approves (POST /oauth/authorize/approve).
4. Browser redirects to the client with ?code=...&state=...
5. Client POSTs /oauth/token (code + verifier) -> 30-day access token.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from app.api.deps import extract_token
from app.core.config import Settings

router = APIRouter(tags=["oauth"])

# Well-known discovery must live at the ROOT (RFC 9728 / MCP auth spec):
# clients look for /.well-known/... before trying path-inserted variants.
root_router = APIRouter(tags=["oauth"])

_TTL_SECONDS = 30 * 24 * 3600

# In-memory stores (single process; pending flows are short-lived).
_clients: dict[str, dict[str, Any]] = {}
_auth_requests: dict[str, dict[str, Any]] = {}
_codes: dict[str, dict[str, Any]] = {}

_NOW = time.time


def _prune() -> None:
    now = _NOW()
    for k in [k for k, v in _auth_requests.items() if now - v["created"] > 600]:
        _auth_requests.pop(k, None)
    for k in [k for k, v in _codes.items() if now - v["created"] > 600]:
        _codes.pop(k, None)
    for k in [k for k, v in _clients.items() if now - v["created"] > 3600]:
        _clients.pop(k, None)


def _mint(verifier, user_id, email, full_name=None) -> dict:
    access = verifier.mint_access_token(user_id, email, expires_in_seconds=_TTL_SECONDS,
                                        full_name=full_name, token_type="mcp")
    refresh = verifier.mint_access_token(user_id, email, expires_in_seconds=_TTL_SECONDS * 2,
                                         full_name=full_name, token_type="mcp_refresh")
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": _TTL_SECONDS,
        "refresh_token": refresh,
    }


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _api_base(request: Request) -> str:
    settings: Settings = request.app.state.settings
    return _base_url(request) + settings.api_v1_prefix


def _mcp_resource_uri(request: Request) -> str:
    """The MCP server URI as the CLIENT sees it.

    Behind the dev proxy (or a reverse proxy) the backend's own base URL is
    its internal host:port — clients connect via the public/web origin, and
    the MCP auth spec requires the advertised `resource` to match that URL
    (or its origin). So we build it from the frontend origin.
    """
    settings: Settings = request.app.state.settings
    origin = settings.resolved_frontend_origin
    if origin:
        return origin + settings.api_v1_prefix + "/mcp"
    return _api_base(request) + "/mcp"


def _protected_resource_payload(request: Request, resource_uri: str | None = None) -> dict:
    api = _api_base(request)
    return {
        "resource": resource_uri or _mcp_resource_uri(request),
        "authorization_servers": [api],
        "scopes_supported": ["mcp"],
        "bearer_methods_supported": ["header"],
    }


@root_router.get("/.well-known/oauth-protected-resource")
async def protected_resource_root(request: Request) -> dict:
    return _protected_resource_payload(request)


@root_router.get("/.well-known/oauth-protected-resource/api/v1/mcp")
async def protected_resource_root_pathed(request: Request) -> dict:
    return _protected_resource_payload(request, _mcp_resource_uri(request))


@router.get("/.well-known/oauth-protected-resource")
@router.get("/api/v1/.well-known/oauth-protected-resource")
async def protected_resource(request: Request) -> dict:
    return _protected_resource_payload(request)


def settings_api_prefix(request: Request) -> str:
    settings: Settings = request.app.state.settings
    return settings.api_v1_prefix


@root_router.get("/.well-known/oauth-authorization-server")
@root_router.get("/.well-known/oauth-authorization-server/api/v1")
@router.get("/.well-known/oauth-authorization-server")
@router.get("/api/v1/.well-known/oauth-authorization-server")
async def authorization_server_metadata(request: Request) -> dict:
    base = _base_url(request)
    api = _api_base(request)
    return {
        "issuer": api,
        "registration_endpoint": api + "/oauth/register",
        "authorization_endpoint": api + "/oauth/authorize",
        "token_endpoint": api + "/oauth/token",
        "scopes_supported": ["mcp"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256", "plain"],
        "token_endpoint_auth_methods_supported": ["none"],
    }


class RegisterRequest(BaseModel):
    redirect_uris: list[str] = []
    client_name: str | None = None
    grant_types: list[str] | None = None
    response_types: list[str] | None = None
    token_endpoint_auth_method: str | None = None


@router.post("/oauth/register")
async def register_client(req: RegisterRequest, request: Request) -> dict:
    _prune()
    client_id = "mcp-" + secrets.token_urlsafe(12)
    _clients[client_id] = {
        "redirect_uris": list(req.redirect_uris or []),
        "name": req.client_name or "MCP client",
        "created": _NOW(),
    }
    return {
        "client_id": client_id,
        "client_id_issued_at": int(_NOW()),
        "client_name": req.client_name or "MCP client",
        "redirect_uris": list(req.redirect_uris or []),
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }


class ApproveRequest(BaseModel):
    auth_id: str


@router.post("/oauth/authorize/approve")
async def approve_authorization(
    req: ApproveRequest,
    request: Request,
    token: str = Depends(extract_token),
) -> dict:
    """Consent endpoint used by the web page — approves a pending
    authorization request and returns the redirect target with the code."""
    from app.auth.jwt_verifier import JWTVerifier

    _prune()
    settings: Settings = request.app.state.settings
    pending = _auth_requests.get(req.auth_id)
    if pending is None:
        return JSONResponse(status_code=404, content={"detail": "Unknown or expired authorization request"})

    verifier = getattr(request.app.state, "jwt_verifier", None)
    if verifier is None:
        verifier = JWTVerifier(settings.supabase_jwt_secret or "dev-insecure-secret")
    user = verifier.to_user(token)
    full_name = (user.metadata or {}).get("full_name")

    code = secrets.token_urlsafe(24)
    _codes[code] = {
        "user_id": str(user.id),
        "email": user.email,
        "full_name": full_name,
        "redirect_uri": pending["redirect_uri"],
        "code_challenge": pending.get("code_challenge"),
        "code_challenge_method": pending.get("code_challenge_method", "S256"),
        "created": _NOW(),
    }
    _auth_requests.pop(req.auth_id, None)

    sep = "&" if "?" in pending["redirect_uri"] else "?"
    redirect = f"{pending['redirect_uri']}{sep}code={code}&state={pending['state']}"
    return {"redirect": redirect}


@router.get("/oauth/authorize")
async def authorize(
    request: Request,
    response_type: str = "code",
    client_id: str = "",
    redirect_uri: str = "",
    state: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "S256",
):
    """Authorization endpoint — 302s to the web consent page."""
    if response_type != "code" or not redirect_uri:
        return JSONResponse(status_code=400, content={"detail": "unsupported or missing response_type/redirect_uri"})
    _prune()
    auth_id = secrets.token_urlsafe(16)
    _auth_requests[auth_id] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge or None,
        "code_challenge_method": code_challenge_method or "S256",
        "created": _NOW(),
    }
    settings: Settings = request.app.state.settings
    consent_url = (
        f"{settings.resolved_frontend_origin}/oauth/authorize?auth_id={auth_id}"
        f"&client_name={_clients.get(client_id, {}).get('name', 'MCP client')}"
    )
    return RedirectResponse(consent_url, status_code=302)


class TokenRequest(BaseModel):
    grant_type: str = "authorization_code"
    code: str | None = None
    redirect_uri: str | None = None
    client_id: str | None = None
    code_verifier: str | None = None
    refresh_token: str | None = None


def _verify_pkce(verifier: str, challenge: str, method: str) -> bool:
    if method == "plain":
        return verifier == challenge
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return computed == challenge


@router.post("/oauth/token")
async def token_endpoint(req: TokenRequest, request: Request) -> dict:
    from app.auth.jwt_verifier import JWTVerifier

    _prune()
    settings: Settings = request.app.state.settings
    verifier = getattr(request.app.state, "jwt_verifier", None)
    if verifier is None:
        verifier = JWTVerifier(settings.supabase_jwt_secret or "dev-insecure-secret")

    if req.grant_type == "authorization_code":
        entry = _codes.get(req.code or "")
        if entry is None:
            return JSONResponse(status_code=400, content={"error": "invalid_grant", "error_description": "Unknown or expired code"})
        if req.redirect_uri != entry["redirect_uri"]:
            return JSONResponse(status_code=400, content={"error": "invalid_grant", "error_description": "redirect_uri mismatch"})
        if entry["code_challenge"]:
            if not req.code_verifier:
                return JSONResponse(status_code=400, content={"error": "invalid_grant", "error_description": "code_verifier required"})
            if not _verify_pkce(req.code_verifier, entry["code_challenge"], entry["code_challenge_method"]):
                return JSONResponse(status_code=400, content={"error": "invalid_grant", "error_description": "PKCE verification failed"})
        _codes.pop(req.code, None)
        payload = _mint(verifier, entry["user_id"], entry["email"], entry.get("full_name"))
        payload["scope"] = "mcp"
        return payload

    if req.grant_type == "refresh_token":
        try:
            claims = verifier.decode_claims(req.refresh_token or "")
        except Exception:
            return JSONResponse(status_code=400, content={"error": "invalid_grant", "error_description": "Invalid refresh token"})
        if claims.get("typ") != "mcp_refresh":
            return JSONResponse(status_code=400, content={"error": "invalid_grant", "error_description": "Not an MCP refresh token"})
        payload = _mint(verifier, claims.get("sub"), claims.get("email", ""), claims.get("full_name"))
        payload["scope"] = "mcp"
        return payload

    return JSONResponse(status_code=400, content={"error": "unsupported_grant_type"})
