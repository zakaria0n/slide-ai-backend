"""Presentation CRUD routes.

Endpoints (all owner-scoped, require a Bearer access token):
- ``GET    /presentations``       list the caller's presentations
- ``POST   /presentations``       create a draft presentation
- ``GET    /presentations/{id}``  fetch one (owner only)
- ``PATCH  /presentations/{id}``  rename
- ``POST   /presentations/{id}/duplicate``  create an owned copy
- ``DELETE /presentations/{id}``  delete (owner only)

Routes contain no business logic; they delegate to
:class:`PresentationService` and translate domain errors into HTTP
responses via the global exception handlers.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.exceptions import UnauthorizedError
from app.db.dependencies import Database
from app.presentations.schemas import (
    CreatePresentationRequest,
    PresentationListResponse,
    PresentationResponse,
    RenamePresentationRequest,
)
from app.presentations.service import PresentationService

router = APIRouter(prefix="/presentations", tags=["presentations"])

_bearer = HTTPBearer(auto_error=False)


def _extract_token(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    if creds is None or not creds.credentials:
        raise UnauthorizedError("Missing authentication token")
    return creds.credentials


def _db(request: Request) -> Database:
    return request.app.state.db


async def _owner_id(request: Request, token: str = Depends(_extract_token)) -> UUID:
    verifier = getattr(request.app.state, "jwt_verifier", None)
    if verifier is None:
        raise UnauthorizedError("Authentication is not configured")
    return verifier.user_id(token)


async def _service(
    request: Request,
    db: Database = Depends(_db),
) -> PresentationService:
    """Yield a service bound to a session committed on success."""
    session = db.session_factory()
    try:
        yield PresentationService(session)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


@router.get("", response_model=PresentationListResponse)
async def list_presentations(
    owner_id: UUID = Depends(_owner_id),
    service: PresentationService = Depends(_service),
    limit: int = 50,
    offset: int = 0,
) -> PresentationListResponse:
    items = await service.list_for_owner(owner_id, limit=limit, offset=offset)
    total = len(items)  # owner-scoped listing fits in one page for this stage
    return PresentationListResponse(
        items=[PresentationResponse.from_entity(p) for p in items],
        total=total,
    )


@router.post("", response_model=PresentationResponse, status_code=201)
async def create_presentation(
    req: CreatePresentationRequest,
    owner_id: UUID = Depends(_owner_id),
    service: PresentationService = Depends(_service),
) -> PresentationResponse:
    created = await service.create(
        owner_id,
        title=req.title,
        description=req.description,
        theme=req.theme,
    )
    return PresentationResponse.from_entity(created)


@router.get("/{presentation_id}", response_model=PresentationResponse)
async def get_presentation(
    presentation_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    service: PresentationService = Depends(_service),
) -> PresentationResponse:
    p = await service.get(presentation_id, owner_id)
    return PresentationResponse.from_entity(p)


@router.patch("/{presentation_id}", response_model=PresentationResponse)
async def rename_presentation(
    presentation_id: UUID,
    req: RenamePresentationRequest,
    owner_id: UUID = Depends(_owner_id),
    service: PresentationService = Depends(_service),
) -> PresentationResponse:
    p = await service.rename(presentation_id, owner_id, title=req.title)
    return PresentationResponse.from_entity(p)


@router.post("/{presentation_id}/duplicate", response_model=PresentationResponse)
async def duplicate_presentation(
    presentation_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    service: PresentationService = Depends(_service),
) -> PresentationResponse:
    p = await service.duplicate(presentation_id, owner_id)
    return PresentationResponse.from_entity(p)


@router.delete("/{presentation_id}", status_code=204)
async def delete_presentation(
    presentation_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    service: PresentationService = Depends(_service),
) -> None:
    await service.delete(presentation_id, owner_id)
