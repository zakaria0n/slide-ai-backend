"""Presentation CRUD + generation routes.

Endpoints (all owner-scoped, require a Bearer access token):
- ``GET    /presentations``                 list the caller's presentations
- ``POST   /presentations``                 create a draft presentation
- ``POST   /presentations/generate``        generate a new deck end-to-end
- ``GET    /presentations/{id}``            fetch one (owner only)
- ``GET    /presentations/{id}/slides``     fetch the ordered slides (owner only)
- ``PATCH  /presentations/{id}``            rename
- ``POST   /presentations/{id}/duplicate``  create an owned copy
- ``DELETE /presentations/{id}``            delete (owner only)

Routes contain no business logic; they delegate to the services and
translate domain errors into HTTP responses via the global handlers.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.config import Settings
from app.core.exceptions import NotFoundError, UnauthorizedError
from app.db.dependencies import Database
from app.db.repositories.presentation import PresentationRepository
from app.db.repositories.slide import SlideRepository
from app.generation.schemas import GenerationRequest
from app.generation.service import GenerationService
from app.generation.spec import PresentationSpec
from app.presentations.entities import Presentation
from app.presentations.schemas import (
    CreatePresentationRequest,
    PresentationListResponse,
    PresentationResponse,
    RenamePresentationRequest,
    SlideResponse,
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


def _to_response(model: object) -> PresentationResponse:
    m = model  # type: ignore[assignment]
    return PresentationResponse.from_entity(
        Presentation(
            id=m.id,
            owner_id=m.owner_id,
            title=m.title,
            description=m.description,
            slide_count=m.slide_count,
            status=m.status,
            theme=m.theme,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )
    )


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


async def _generation_service(
    request: Request,
    db: Database = Depends(_db),
) -> GenerationService:
    """Yield a generation service committed on success."""
    from app.generation.spec_provider import build_spec_provider

    settings: Settings = request.app.state.settings
    provider = build_spec_provider(settings)
    session = db.session_factory()
    try:
        yield GenerationService(session, provider=provider)
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
    total = len(items)
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


@router.post("/generate", response_model=PresentationResponse, status_code=201)
async def generate_presentation(
    req: GenerationRequest,
    owner_id: UUID = Depends(_owner_id),
    service: GenerationService = Depends(_generation_service),
) -> PresentationResponse:
    """Generate a full deck from a prompt and store it.

    Creates a draft, asks the provider (exposed only as "Slide AI") for
    slides, persists them, and returns the ready presentation.
    """
    model = await service.generate(owner_id, request=req)
    return _to_response(model)


@router.get("/{presentation_id}", response_model=PresentationResponse)
async def get_presentation(
    presentation_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    service: PresentationService = Depends(_service),
) -> PresentationResponse:
    p = await service.get(presentation_id, owner_id)
    return PresentationResponse.from_entity(p)


@router.get("/{presentation_id}/slides", response_model=list[SlideResponse])
async def get_presentation_slides(
    presentation_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    db: Database = Depends(_db),
) -> list[SlideResponse]:
    """Return the ordered slides for a presentation (owner only)."""
    session = db.session_factory()
    try:
        # Ownership check first.
        await PresentationService(session).get(presentation_id, owner_id)
        slides = await SlideRepository(session).list_for_presentation(
            presentation_id, owner_id=owner_id
        )
    finally:
        await session.close()
    return [SlideResponse.from_content(s.slide_index, s.content) for s in slides]


@router.get("/{presentation_id}/spec", response_model=PresentationSpec)
async def get_presentation_spec(
    presentation_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    db: Database = Depends(_db),
) -> PresentationSpec:
    """Return the full structured specification for a presentation."""
    session = db.session_factory()
    try:
        presentation = await PresentationRepository(session).get_owned(
            presentation_id, owner_id
        )
        if presentation is None:
            raise NotFoundError("Presentation not found")
        spec = presentation.spec
    finally:
        await session.close()
    if not spec:
        raise NotFoundError("Presentation specification not found")
    return PresentationSpec.model_validate(spec)


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
