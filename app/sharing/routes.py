"""Sharing routes.

Owner-scoped:
- ``POST   /presentations/{id}/shares``   create a share link
- ``GET    /presentations/{id}/shares``   list shares
- ``DELETE /shares/{token}``              revoke a share

Public (no auth required):
- ``GET    /shared/{token}``               view shared presentation spec
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from supabase import AsyncClient

import app.db as db
from app.api.deps import owner_id, supabase
from app.core.exceptions import ForbiddenError, NotFoundError
from app.generation.spec import PresentationSpec
from app.sharing.password import generate_token, hash_password, verify_password

router = APIRouter(tags=["sharing"])

_supabase = supabase


# --- request / response schemas ---


class CreateShareRequest(BaseModel):
    visibility: str = "public"  # public, private, password
    password: str | None = None
    expires_at: str | None = None  # ISO datetime
    permission: str = "view"  # view, present
    embed_allowed: bool = True


class ShareResponse(BaseModel):
    id: str
    token: str
    visibility: str
    permission: str
    embed_allowed: bool
    expires_at: str | None = None
    created_at: str


class ShareListResponse(BaseModel):
    shares: list[ShareResponse]


class SharedSpecResponse(BaseModel):
    spec: PresentationSpec
    title: str


# --- owner-scoped routes ---


_get_owner_id = owner_id


async def _require_presentation(
    supabase: AsyncClient, presentation_id: UUID, user_id: UUID, *, write: bool = False
) -> dict:
    """Return the presentation row if the caller may access it.

    Access is granted when the caller owns the presentation or is a member
    of a workspace that contains it. ``write=True`` additionally requires
    an ``owner``/``admin``/``editor`` role.
    """
    row = await db.get_presentation(supabase, presentation_id)
    if row is None:
        raise NotFoundError("Presentation not found")
    role = await db.get_presentation_access_role(supabase, presentation_id, user_id)
    if role is None:
        raise NotFoundError("Presentation not found")
    if write and role not in ("owner", "admin", "editor"):
        raise ForbiddenError("You have read-only access to this presentation")
    return row


@router.post("/presentations/{presentation_id}/shares", response_model=ShareResponse, status_code=201)
async def create_share(
    presentation_id: UUID,
    req: CreateShareRequest,
    owner_id: UUID = Depends(_get_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> ShareResponse:
    """Create a new share link for a presentation."""
    await _require_presentation(supabase, presentation_id, owner_id, write=True)

    token = generate_token()
    password_hash_val = hash_password(req.password) if req.visibility == "password" and req.password else None
    expires_at_val = None
    if req.expires_at:
        try:
            expires_at_val = datetime.fromisoformat(req.expires_at)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid expires_at format")

    share = await db.create_share(
        supabase,
        presentation_id=str(presentation_id),
        owner_id=str(owner_id),
        token=token,
        visibility=req.visibility,
        password_hash=password_hash_val,
        expires_at=expires_at_val.isoformat() if expires_at_val else None,
        permission=req.permission,
        embed_allowed=req.embed_allowed,
    )

    return ShareResponse(
        id=str(share["id"]),
        token=share["token"],
        visibility=share["visibility"],
        permission=share["permission"],
        embed_allowed=share["embed_allowed"],
        expires_at=share.get("expires_at"),
        created_at=share["created_at"],
    )


@router.get("/presentations/{presentation_id}/shares", response_model=ShareListResponse)
async def list_shares(
    presentation_id: UUID,
    owner_id: UUID = Depends(_get_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> ShareListResponse:
    """List all share links for a presentation."""
    await _require_presentation(supabase, presentation_id, owner_id)
    shares = await db.list_shares(supabase, presentation_id)

    return ShareListResponse(
        shares=[
            ShareResponse(
                id=str(s["id"]),
                token=s["token"],
                visibility=s["visibility"],
                permission=s["permission"],
                embed_allowed=s["embed_allowed"],
                expires_at=s.get("expires_at"),
                created_at=s["created_at"],
            )
            for s in shares
        ]
    )


@router.delete("/shares/{token}", status_code=204)
async def delete_share(
    token: str,
    owner_id: UUID = Depends(_get_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> None:
    """Revoke a share link."""
    share = await db.get_share_by_token(supabase, token)
    if share is None:
        raise NotFoundError("Share not found")
    await _require_presentation(
        supabase, UUID(share["presentation_id"]), owner_id, write=True
    )
    await db.delete_share(supabase, token)


# --- public routes (no auth) ---


def _validate_share(share: dict | None) -> None:
    if share is None:
        raise NotFoundError("Share not found")
    if share.get("expires_at"):
        try:
            exp = datetime.fromisoformat(share["expires_at"])
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < datetime.now(timezone.utc):
                raise HTTPException(status_code=410, detail="Share link has expired")
        except (ValueError, TypeError):
            # Fail closed: a malformed expiry must not grant access.
            raise HTTPException(status_code=410, detail="Share link has expired")
    if share["visibility"] == "private":
        raise NotFoundError("Share not found")


@router.get("/shared/{token}", response_model=SharedSpecResponse)
async def get_shared(
    token: str,
    password: str | None = Query(None),
    supabase: AsyncClient = Depends(_supabase),
) -> SharedSpecResponse:
    """Access a shared presentation (no auth required)."""
    share = await db.get_share_by_token(supabase, token)
    _validate_share(share)

    if share["visibility"] == "password":
        if not password or not verify_password(password, share.get("password_hash")):
            raise HTTPException(status_code=403, detail="Invalid password")

    presentation = await db.get_presentation(supabase, UUID(share["presentation_id"]))
    if presentation is None:
        raise NotFoundError("Presentation not found")

    spec = PresentationSpec.model_validate(presentation["spec"])
    return SharedSpecResponse(spec=spec, title=presentation["title"])