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

from app.core.exceptions import NotFoundError, UnauthorizedError
from app.db.dependencies import Database
from app.db.repositories.presentation import PresentationRepository
from app.db.repositories.presentation_share import PresentationShareRepository
from app.generation.spec import PresentationSpec
from app.models.presentation import Presentation
from app.models.presentation_share import PresentationShare
from app.sharing.password import generate_token, hash_password, verify_password

router = APIRouter(tags=["sharing"])


def _db(request: Request) -> Database:
    return request.app.state.db


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


from fastapi.security import HTTPBearer  # noqa: E402

_bearer_dep = HTTPBearer(auto_error=False)


def _extract_owner_token(
    creds=Depends(_bearer_dep),
) -> str:
    if creds is None or not creds.credentials:
        raise UnauthorizedError("Missing authentication token")
    return creds.credentials


def _get_owner_id(request: Request, token: str = Depends(_extract_owner_token)) -> UUID:
    verifier = getattr(request.app.state, "jwt_verifier", None)
    if verifier is None:
        raise UnauthorizedError("Authentication is not configured")
    return verifier.user_id(token)


@router.post("/presentations/{presentation_id}/shares", response_model=ShareResponse, status_code=201)
async def create_share(
    presentation_id: UUID,
    req: CreateShareRequest,
    request: Request,
    owner_id: UUID = Depends(_get_owner_id),
    db: Database = Depends(_db),
) -> ShareResponse:
    """Create a new share link for a presentation."""
    session = db.session_factory()
    try:
        presentation = await PresentationRepository(session).get_owned(presentation_id, owner_id)
        if presentation is None:
            raise NotFoundError("Presentation not found")

        token = generate_token()
        password_hash_val = hash_password(req.password) if req.visibility == "password" and req.password else None
        expires_at_val = None
        if req.expires_at:
            try:
                expires_at_val = datetime.fromisoformat(req.expires_at)
            except ValueError:
                raise HTTPException(status_code=422, detail="Invalid expires_at format")

        share = PresentationShare(
            presentation_id=presentation_id,
            owner_id=owner_id,
            token=token,
            visibility=req.visibility,
            password_hash=password_hash_val,
            expires_at=expires_at_val,
            permission=req.permission,
            embed_allowed=req.embed_allowed,
        )
        session.add(share)
        await session.commit()
        await session.refresh(share)
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()

    return ShareResponse(
        id=str(share.id),
        token=share.token,
        visibility=share.visibility,
        permission=share.permission,
        embed_allowed=share.embed_allowed,
        expires_at=share.expires_at.isoformat() if share.expires_at else None,
        created_at=share.created_at.isoformat(),
    )


@router.get("/presentations/{presentation_id}/shares", response_model=ShareListResponse)
async def list_shares(
    presentation_id: UUID,
    request: Request,
    owner_id: UUID = Depends(_get_owner_id),
    db: Database = Depends(_db),
) -> ShareListResponse:
    """List all share links for a presentation."""
    session = db.session_factory()
    try:
        presentation = await PresentationRepository(session).get_owned(presentation_id, owner_id)
        if presentation is None:
            raise NotFoundError("Presentation not found")
        shares = await PresentationShareRepository(session).list_for_presentation(presentation_id)
    finally:
        await session.close()

    return ShareListResponse(
        shares=[
            ShareResponse(
                id=str(s.id),
                token=s.token,
                visibility=s.visibility,
                permission=s.permission,
                embed_allowed=s.embed_allowed,
                expires_at=s.expires_at.isoformat() if s.expires_at else None,
                created_at=s.created_at.isoformat(),
            )
            for s in shares
        ]
    )


@router.delete("/shares/{token}", status_code=204)
async def delete_share(
    token: str,
    request: Request,
    owner_id: UUID = Depends(_get_owner_id),
    db: Database = Depends(_db),
) -> None:
    """Revoke a share link."""
    session = db.session_factory()
    try:
        share = await PresentationShareRepository(session).get_by_token(token)
        if share is None or share.owner_id != owner_id:
            raise NotFoundError("Share not found")
        await session.delete(share)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


# --- public routes (no auth) ---


def _validate_share(share: PresentationShare | None) -> None:
    if share is None:
        raise NotFoundError("Share not found")
    if share.expires_at and share.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Share link has expired")
    if share.visibility == "private":
        raise NotFoundError("Share not found")


@router.get("/shared/{token}", response_model=SharedSpecResponse)
async def get_shared(
    token: str,
    password: str | None = Query(None),
    db: Database = Depends(_db),
) -> SharedSpecResponse:
    """Access a shared presentation (no auth required)."""
    session = db.session_factory()
    try:
        share = await PresentationShareRepository(session).get_by_token(token)
        _validate_share(share)

        if share.visibility == "password":
            if not password or not verify_password(password, share.password_hash):
                raise HTTPException(status_code=403, detail="Invalid password")

        presentation = await session.get(Presentation, share.presentation_id)
        if presentation is None:
            raise NotFoundError("Presentation not found")

        spec = PresentationSpec.model_validate(presentation.spec)
    finally:
        await session.close()

    return SharedSpecResponse(spec=spec, title=presentation.title)
