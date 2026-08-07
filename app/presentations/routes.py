"""Presentation CRUD + generation routes.

Endpoints (all owner-scoped, require a Bearer access token):
- ``GET    /presentations``                 list the caller's presentations
- ``POST   /presentations``                 create a draft presentation
- ``POST   /presentations/generate``        generate a new deck end-to-end
- ``GET    /presentations/{id}``            fetch one (owner only)
- ``GET    /presentations/{id}/spec``       fetch the structured spec (owner only)
- ``PUT    /presentations/{id}/spec``       update the structured spec (owner only)
- ``POST   /presentations/{id}/edit``       AI-driven spec edit (owner only)
- ``GET    /presentations/{id}/export``    export to HTML/PDF/PPTX (owner only)
- ``PATCH  /presentations/{id}``            rename
- ``POST   /presentations/{id}/duplicate``  create an owned copy
- ``DELETE /presentations/{id}``            delete (owner only)

Routes contain no business logic; they delegate to the services and
translate domain errors into HTTP responses via the global handlers.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from supabase import AsyncClient

import app.db as db
from app.api.deps import extract_token, owner_id, supabase
from app.core.config import Settings
from app.core.exceptions import ForbiddenError, NotFoundError
from app.generation.service import GenerationService
from app.generation.spec import PresentationSpec
from app.export.strategy import ExportFormat
from app.export.service import ExportService
from app.generation.schemas import GenerationRequest
from app.presentations.schemas import (
    CreatePresentationRequest,
    PresentationListResponse,
    PresentationResponse,
    RenamePresentationRequest,
)
from app.presentations.service import PresentationService

router = APIRouter(prefix="/presentations", tags=["presentations"])

# Re-export shared deps as local names used by existing route signatures.
_extract_token = extract_token
_supabase = supabase
_owner_id = owner_id


async def _require_presentation(
    supabase: AsyncClient,
    presentation_id: UUID,
    user_id: UUID,
    *,
    write: bool = False,
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


def _to_response(row: dict) -> PresentationResponse:
    return PresentationResponse(
        id=UUID(row["id"]),
        owner_id=UUID(row["owner_id"]),
        title=row["title"],
        description=row.get("description"),
        slide_count=row.get("slide_count", 0),
        status=row.get("status", "draft"),
        theme=row.get("theme"),
        created_at=_parse_dt(row["created_at"]),
        updated_at=_parse_dt(row["updated_at"]),
    )


def _parse_dt(value: str) -> str:
    return value


async def _service(
    supabase: AsyncClient = Depends(_supabase),
) -> PresentationService:
    yield PresentationService(supabase)


async def _generation_service(
    request: Request,
    supabase: AsyncClient = Depends(_supabase),
) -> GenerationService:
    from app.generation.spec_provider import build_spec_provider

    settings: Settings = request.app.state.settings
    provider = build_spec_provider(settings)
    yield GenerationService(supabase, provider=provider)


@router.get("", response_model=PresentationListResponse)
async def list_presentations(
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
    service: PresentationService = Depends(_service),
    limit: int = 50,
    offset: int = 0,
) -> PresentationListResponse:
    items = await service.list_for_owner(owner_id, limit=limit, offset=offset)
    total = await db.count_presentations(supabase, owner_id)
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
    from app.core.ratelimit import generation_limiter

    generation_limiter.check(str(owner_id))

    row = await service.generate(owner_id, request=req)
    return _to_response(row)


@router.get("/{presentation_id}", response_model=PresentationResponse)
async def get_presentation(
    presentation_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    service: PresentationService = Depends(_service),
) -> PresentationResponse:
    p = await service.get(presentation_id, owner_id)
    return PresentationResponse.from_entity(p)


@router.get("/{presentation_id}/spec", response_model=PresentationSpec)
async def get_presentation_spec(
    presentation_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> PresentationSpec:
    """Return the full structured specification for a presentation."""
    row = await _require_presentation(supabase, presentation_id, owner_id)
    spec = row.get("spec")
    if not spec:
        raise NotFoundError("Presentation specification not found")
    return PresentationSpec.model_validate(spec)


@router.get("/{presentation_id}/export")
async def export_presentation(
    presentation_id: UUID,
    format: ExportFormat = ExportFormat.HTML,
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> Response:
    """Export a presentation to HTML / PDF / PPTX.

    - ``html`` returns a self-contained animated HTML file.
    - ``pdf`` returns a real vector PDF rendered via Playwright.
    - ``pptx`` returns a native PowerPoint file with content only.
    """
    row = await _require_presentation(supabase, presentation_id, owner_id)
    spec_raw = row.get("spec")
    if not spec_raw:
        raise NotFoundError("Presentation specification not found")
    spec = PresentationSpec.model_validate(spec_raw)
    exported = await ExportService().export(spec, fmt=format, theme_hint=spec.meta.theme if spec.meta else None)
    return Response(
        content=exported.data,
        media_type=exported.media_type,
        headers={"Content-Disposition": f'attachment; filename="{exported.filename}"'},
    )


@router.put("/{presentation_id}/spec", response_model=PresentationSpec)
async def update_presentation_spec(
    presentation_id: UUID,
    spec: PresentationSpec,
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> PresentationSpec:
    """Replace the presentation specification (live editing).

    Accepts a full ``PresentationSpec`` and persists it. The caller is
    responsible for conflict resolution (last-write-wins).
    """
    if not spec.slides:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="slides required")
    row = await _require_presentation(supabase, presentation_id, owner_id, write=True)
    old_spec = PresentationSpec.model_validate(row["spec"])
    from app.presentations.versioning import snapshot_if_changed
    await snapshot_if_changed(supabase, presentation_id, owner_id, old_spec, note="manual edit")
    await db.update_presentation(
        supabase, presentation_id,
        spec=spec.model_dump(),
        slide_count=len(spec.slides),
    )
    return spec


class SpecEditRequest(BaseModel):
    instruction: str
    target_indexes: list[int] | None = Field(default=None)


class SpecEditResponse(BaseModel):
    spec: PresentationSpec
    summary: str
    changed_indexes: list[int]


@router.post("/{presentation_id}/edit", response_model=SpecEditResponse)
async def ai_edit_presentation(
    presentation_id: UUID,
    req: SpecEditRequest,
    request: Request,
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> SpecEditResponse:
    """AI-driven spec editing.

    Takes an instruction (e.g. 'make it modern', 'reduce text') and applies
    it to the current spec. Only affected slides are modified.
    """
    from app.core.ratelimit import generation_limiter
    from app.generation.spec_editor import SpecEditResult, build_spec_edit_provider

    generation_limiter.check(str(owner_id))

    settings: Settings = request.app.state.settings
    provider = build_spec_edit_provider(settings)

    row = await _require_presentation(supabase, presentation_id, owner_id, write=True)
    current_spec = PresentationSpec.model_validate(row["spec"])

    result: SpecEditResult = await provider.edit_spec(
        current_spec, req.instruction, req.target_indexes
    )

    from app.presentations.versioning import snapshot_if_changed
    await snapshot_if_changed(supabase, presentation_id, owner_id, current_spec, note=f"before: {req.instruction}")

    await db.update_presentation(
        supabase, presentation_id,
        spec=result.modified_spec.model_dump(),
        slide_count=len(result.modified_spec.slides),
    )

    return SpecEditResponse(
        spec=result.modified_spec,
        summary=result.summary,
        changed_indexes=result.changed_indexes,
    )


# --- version history ---


class VersionResponse(BaseModel):
    id: str
    presentation_id: str
    version_note: str | None
    slide_count: int
    created_at: str
    spec: dict | None = None


class VersionListResponse(BaseModel):
    versions: list[VersionResponse]
    total: int


@router.get("/{presentation_id}/versions", response_model=VersionListResponse)
async def list_versions(
    presentation_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> VersionListResponse:
    """List version history for a presentation."""
    await _require_presentation(supabase, presentation_id, owner_id)
    versions = await db.list_versions(supabase, presentation_id)

    return VersionListResponse(
        versions=[
            VersionResponse(
                id=str(v["id"]),
                presentation_id=str(v["presentation_id"]),
                version_note=v.get("version_note"),
                slide_count=v.get("slide_count", 0),
                created_at=v["created_at"],
            )
            for v in versions
        ],
        total=len(versions),
    )


@router.get("/{presentation_id}/versions/{version_id}", response_model=VersionResponse)
async def get_version(
    presentation_id: UUID,
    version_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> VersionResponse:
    """Get a specific version snapshot with full spec."""
    await _require_presentation(supabase, presentation_id, owner_id)
    version = await db.get_version(supabase, version_id)
    if version is None:
        raise NotFoundError("Version not found")

    return VersionResponse(
        id=str(version["id"]),
        presentation_id=str(version["presentation_id"]),
        version_note=version.get("version_note"),
        slide_count=version.get("slide_count", 0),
        created_at=version["created_at"],
        spec=version.get("spec"),
    )


@router.post("/{presentation_id}/versions/{version_id}/restore", response_model=PresentationSpec)
async def restore_version(
    presentation_id: UUID,
    version_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> PresentationSpec:
    """Restore a presentation to a specific version snapshot."""
    from app.presentations.versioning import snapshot_if_changed, restore_conversation

    row = await _require_presentation(supabase, presentation_id, owner_id, write=True)
    version = await db.get_version(supabase, version_id)
    if version is None:
        raise NotFoundError("Version not found")

    old_spec = PresentationSpec.model_validate(row["spec"])
    restored_spec = PresentationSpec.model_validate(version["spec"])

    await snapshot_if_changed(supabase, presentation_id, owner_id, old_spec, note="before restore")

    await db.update_presentation(
        supabase, presentation_id,
        spec=restored_spec.model_dump(),
        slide_count=len(restored_spec.slides),
    )

    # Also restore conversation to the version's snapshot
    await restore_conversation(supabase, presentation_id, version_id, owner_id)

    return restored_spec


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
