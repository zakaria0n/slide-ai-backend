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
from fastapi.responses import Response
from pydantic import BaseModel, Field
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
    view_count: int = 0
    # Seconds spent per slide by shared viewers: {"0": 12, "1": 8}
    slide_time_json: dict | None = None
    comments: list[dict] = []


class ShareListResponse(BaseModel):
    shares: list[ShareResponse]


class SharedSpecResponse(BaseModel):
    spec: PresentationSpec
    title: str
    comments: list[dict] = []


class ShareCommentRequest(BaseModel):
    author_name: str | None = Field(default=None, max_length=40)
    content: str = Field(min_length=1, max_length=500)


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
async def list_shares_with_stats(
    presentation_id: UUID,
    owner_id: UUID = Depends(_get_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> ShareListResponse:
    """List all share links for a presentation."""
    await _require_presentation(supabase, presentation_id, owner_id)
    shares = await db.list_shares(supabase, presentation_id)

    items = []
    for s_row in shares:
        try:
            comments = await db.list_share_comments(supabase, s_row["token"])
        except Exception:
            comments = []
        items.append(ShareResponse(
            id=str(s_row["id"]),
            token=s_row["token"],
            visibility=s_row["visibility"],
            permission=s_row["permission"],
            embed_allowed=s_row["embed_allowed"],
            expires_at=s_row.get("expires_at"),
            created_at=s_row["created_at"],
            view_count=int(s_row.get("view_count") or 0),
            slide_time_json=s_row.get("slide_time_json"),
            comments=comments,
        ))

    return ShareListResponse(shares=items)


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

    # Best-effort analytics + reviewer comments.
    try:
        await db.increment_share_views(supabase, token)
        comments = await db.list_share_comments(supabase, token)
    except Exception:
        comments = []

    spec = PresentationSpec.model_validate(presentation["spec"])
    return SharedSpecResponse(spec=spec, title=presentation["title"], comments=comments)


class ShareSlideTimeRequest(BaseModel):
    time_json: dict = Field(default_factory=dict, description='{"0": 12, "1": 8} — seconds per slide')


@router.post("/shared/{token}/analytics", status_code=204)
async def post_share_slide_time(
    token: str,
    req: ShareSlideTimeRequest,
    supabase: AsyncClient = Depends(_supabase),
) -> Response:
    """Record time-per-slide from a shared-deck viewer (fire-and-forget)."""
    share = await db.get_share_by_token(supabase, token)
    _validate_share(share)

    cleaned = {}
    for key, seconds in list(req.time_json.items())[:100]:
        try:
            cleaned[str(int(key))] = max(0, min(int(seconds), 3600))
        except (TypeError, ValueError):
            continue
    try:
        await supabase.table("presentation_shares").update({"slide_time_json": cleaned}).eq("token", token).execute()
    except Exception as _exc:
        import logging

        logging.getLogger("sharing").warning("slide_time update failed: %s", _exc)
    return Response(status_code=204)


@router.post("/shared/{token}/comments", status_code=201)
async def post_share_comment(
    token: str,
    req: ShareCommentRequest,
    request: Request,
    supabase: AsyncClient = Depends(_supabase),
) -> dict:
    """Leave a reviewer comment on a shared presentation (no auth required).

    Rate-limited: one comment per IP every 15 minutes (anti-spam on a
    public, unauthenticated endpoint).
    """
    from app.core.ratelimit import comment_limiter

    client_ip = request.client.host if request.client else "unknown"
    comment_limiter.check(client_ip)

    share = await db.get_share_by_token(supabase, token)
    _validate_share(share)

    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="Comment must not be empty")
    author = (req.author_name or "").strip()[:40] or "Anonymous"
    row = await db.create_share_comment(
        supabase, share_token=token, author_name=author, content=content[:500],
    )
    return {"id": row.get("id"), "author_name": author, "content": content[:500]}