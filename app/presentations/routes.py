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

import json
from uuid import UUID

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from supabase import AsyncClient

import app.db as db
from app.api.deps import extract_token, owner_id, supabase
from app.core.config import Settings
from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
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
    from app.core.brand import get_brand_context
    from app.core.ratelimit import generation_limiter

    generation_limiter.check(str(owner_id))

    req = req.model_copy(update={"brand_context": await get_brand_context(supabase, owner_id)})
    row = await service.generate(owner_id, request=req)
    return _to_response(row)


# ── search & import (declared BEFORE /{presentation_id} so /search is not
#    captured by the dynamic UUID route) ──────────────────────────────────────


class OutlineRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    slide_count: int = Field(default=10, ge=1, le=30)
    language: str = Field(default="English", max_length=40)
    tone: str = Field(default="Professional", max_length=40)
    model: str | None = Field(default=None, max_length=80)


class OutlineResponse(BaseModel):
    outline: list[dict]


@router.post("/outline", response_model=OutlineResponse)
async def generate_outline_endpoint(
    req: OutlineRequest,
    request: Request,
    owner_id: UUID = Depends(_owner_id),
) -> OutlineResponse:
    """Outline-first flow: propose a slide plan WITHOUT generating the deck.

    The caller reviews/edits/reorders the plan, then passes it back via
    ``GenerationRequest.outline`` on /generate.
    """
    from app.core.ratelimit import generation_limiter
    from app.generation.outliner import generate_outline

    generation_limiter.check(str(owner_id))
    settings: Settings = request.app.state.settings
    items = await generate_outline(
        settings,
        prompt=req.prompt,
        slide_count=req.slide_count,
        language=req.language,
        tone=req.tone,
        model=req.model,
    )
    return OutlineResponse(outline=[item.model_dump() for item in items])


@router.post("/import/pptx", response_model=PresentationResponse, status_code=201)
async def import_pptx_file(
    request: Request,
    file: UploadFile,
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
    service: PresentationService = Depends(_service),
) -> PresentationResponse:
    """Import an existing .pptx into an editable deck (no AI rewriting).

    Text becomes editable elements at their original positions, tables and
    native charts become structured elements, speaker notes are kept.
    """
    from app.presentations.pptx_import import import_pptx_to_spec

    name = file.filename or "imported.pptx"
    if not name.lower().endswith(".pptx"):
        raise ValidationError("Only .pptx files are supported")
    data = await file.read()
    if len(data) > 20_000_000:
        raise ValidationError("File too large (max 20 MB)")

    spec = import_pptx_to_spec(data, title=name.rsplit(".", 1)[0][:200])
    created = await service.create(owner_id, title=spec.meta.title, theme=spec.meta.theme)
    await db.update_presentation(
        supabase, UUID(created.id),
        spec=spec.model_dump(),
        slide_count=len(spec.slides),
        status="ready",
    )
    row = await db.get_presentation(supabase, UUID(created.id))
    from app.presentations.service import _to_entity

    return PresentationResponse.from_entity(_to_entity(row or {}))


class TranslateRequest(BaseModel):
    target_language: str = Field(min_length=1, max_length=40)
    model: str | None = Field(default=None, max_length=80)


@router.post("/{presentation_id}/translate", response_model=PresentationSpec)
async def translate_presentation(
    presentation_id: UUID,
    req: TranslateRequest,
    request: Request,
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> PresentationSpec:
    """Translate every text in the deck into ``target_language`` (one call)."""
    from app.core.ratelimit import generation_limiter
    from app.generation.translator import translate_spec

    generation_limiter.check(str(owner_id))

    row = await _require_presentation(supabase, presentation_id, owner_id, write=True)
    if not row.get("spec"):
        raise NotFoundError("Presentation specification not found")
    current_spec = PresentationSpec.model_validate(row["spec"])

    settings: Settings = request.app.state.settings
    translated = await translate_spec(
        current_spec.model_copy(deep=True),
        settings,
        target_language=req.target_language,
        model=req.model,
    )

    from app.presentations.versioning import snapshot_if_changed

    await snapshot_if_changed(supabase, presentation_id, owner_id, current_spec, note=f"before translate → {req.target_language}")
    await db.update_presentation(
        supabase, presentation_id,
        spec=translated.model_dump(),
        slide_count=len(translated.slides),
    )
    return translated


@router.get("/search", response_model=PresentationListResponse)
async def search_presentations(
    q: str,
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> PresentationListResponse:
    """Full-deck search: matches title, description AND slide content."""
    query = (q or "").strip().lower()
    if not query:
        return PresentationListResponse(items=[], total=0)
    rows = await db.list_presentations(supabase, owner_id, limit=200, offset=0)
    hits = []
    for row in rows:
        haystack = " ".join([
            str(row.get("title") or ""),
            str(row.get("description") or ""),
            json.dumps(row.get("spec") or {}, ensure_ascii=False, default=str),
        ]).lower()
        if query in haystack:
            hits.append(row)
    from app.presentations.service import _to_entity

    items = [PresentationResponse.from_entity(_to_entity(r)) for r in hits]
    return PresentationListResponse(items=items, total=len(items))


class ImportRequest(BaseModel):
    source: str = Field(pattern="^(markdown|url)$")
    content: str | None = Field(default=None, max_length=200000)
    url: str | None = Field(default=None, max_length=2000)
    slide_count: int | None = Field(default=None, ge=1, le=30)
    language: str = Field(default="English", max_length=40)
    theme: str | None = Field(default=None, max_length=40)
    model: str | None = Field(default=None, max_length=80)


_PRIVATE_HOST_RE = None  # compiled lazily in _fetch_url_text


def _is_private_host(host: str) -> bool:
    import re as _re

    return bool(
        _re.match(
            r"^(localhost|127\.|10\.|192\.168\.|169\.254\.|0\.|\[::1\]|172\.(1[6-9]|2\d|3[01])\.|.*\.local$)",
            (host or "").lower(),
        )
    )


async def _fetch_url_text(url: str) -> str:
    """Fetch a web page and extract readable text (SSRF-guarded)."""
    from urllib.parse import urlparse

    import httpx

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValidationError("Only http(s) URLs are supported")
    if _is_private_host(parsed.hostname or ""):
        raise ValidationError("This URL is not reachable")

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(url)
    if resp.status_code != 200:
        raise ValidationError(f"The page returned HTTP {resp.status_code}")
    if len(resp.content) > 800_000:
        raise ValidationError("Page too large to import (max 800 KB)")
    content_type = resp.headers.get("content-type", "")
    text = resp.text
    if "html" in content_type or text.lstrip().startswith("<"):
        import html as _html
        import re as _re

        text = _re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", text)
        text = _re.sub(r"(?s)<[^>]+>", " ", text)
        text = _html.unescape(text)
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    return text[:20000]


@router.post("/import", response_model=PresentationResponse, status_code=201)
async def import_presentation(
    req: ImportRequest,
    request: Request,
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
    service: GenerationService = Depends(_generation_service),
) -> PresentationResponse:
    """Create a deck from imported material (markdown text or a web page URL).

    The AI structures the deck around the source material's facts instead of
    inventing content.
    """
    from app.core.model_catalog import resolve_model
    from app.core.ratelimit import generation_limiter

    generation_limiter.check(str(owner_id))

    settings: Settings = request.app.state.settings
    model = await resolve_model(settings, req.model)

    if req.source == "url":
        if not req.url:
            raise ValidationError("A URL is required when source is 'url'")
        source_content = await _fetch_url_text(req.url)
        prompt = "Create a presentation faithful to the imported web page below"
    else:
        content = (req.content or "").strip()
        if not content:
            raise ValidationError("Markdown content is required when source is 'markdown'")
        source_content = content[:20000]
        prompt = "Create a presentation based on the imported markdown below"

    slide_count = req.slide_count
    if slide_count is None:
        words = max(1, len(source_content.split()))
        slide_count = max(3, min(12, words // 120 + 1))

    from app.generation.schemas import GenerationRequest as _GenReq

    gen_request = _GenReq(
        prompt=prompt,
        slide_count=slide_count,
        language=req.language,
        theme=req.theme,
        model=model,
        source_content=source_content,
    )
    from app.core.brand import get_brand_context

    gen_request = gen_request.model_copy(
        update={"brand_context": await get_brand_context(supabase, owner_id)}
    )
    saved = await service.generate(owner_id, request=gen_request)
    from app.presentations.service import _to_entity

    return PresentationResponse.from_entity(_to_entity(saved))


@router.get("/{presentation_id}", response_model=PresentationResponse)
async def get_presentation(
    presentation_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    service: PresentationService = Depends(_service),
    supabase: AsyncClient = Depends(_supabase),
) -> PresentationResponse:
    p = await service.get(presentation_id, owner_id)
    resp = PresentationResponse.from_entity(p)
    resp.access_role = await db.get_presentation_access_role(supabase, presentation_id, owner_id)
    return resp


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
    request: Request,
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
    # Images referenced by file_id get FRESH signed URLs for the export.
    try:
        from app.files.service import resolve_spec_image_urls

        spec = await resolve_spec_image_urls(
            supabase, request.app.state.storage, spec, owner_id
        )
    except Exception:
        pass  # export proceeds with whatever srcs exist
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
    expected_updated_at: str | None = None,
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

    # Optimistic locking: reject the write when the deck changed since the
    # caller loaded it, instead of silently overwriting concurrent edits.
    if expected_updated_at and row.get("updated_at"):
        from datetime import datetime as _dt
        from datetime import timezone as _timezone

        def _parse_ts(value):
            parsed = _dt.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=_timezone.utc)
            return parsed

        try:
            incoming = _parse_ts(expected_updated_at)
            current = _parse_ts(row["updated_at"])
        except (ValueError, TypeError):
            pass
        else:
            if incoming.replace(microsecond=0) != current.replace(microsecond=0):
                from app.core.exceptions import ConflictError

                raise ConflictError(
                    "This presentation was modified elsewhere after you loaded it. "
                    "Reload to get the latest version before saving."
                )

    # Specless decks (e.g. drafts from the "Blank deck" flow) are valid:
    # the PUT defines their first spec, so there is nothing to snapshot.
    old_spec = PresentationSpec.model_validate(row["spec"]) if row.get("spec") else None
    from app.presentations.versioning import snapshot_if_changed
    if old_spec is not None:
        await snapshot_if_changed(supabase, presentation_id, owner_id, old_spec, note="manual edit")
    saved = await db.update_presentation(
        supabase, presentation_id,
        spec=spec.model_dump(),
        slide_count=len(spec.slides),
    )
    # Echo the fresh updated_at so clients can keep the optimistic lock current.
    from fastapi.responses import JSONResponse

    return JSONResponse(
        content=spec.model_dump(mode="json"),
        headers={"X-Updated-At": str((saved or {}).get("updated_at") or "")},
    )


class SpecEditRequest(BaseModel):
    instruction: str
    target_indexes: list[int] | None = Field(default=None)
    # Model the caller picked (Quick AI edit modal). None → backend default.
    model: str | None = Field(default=None, max_length=80)


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

    from app.core.model_catalog import resolve_model

    model = await resolve_model(settings, req.model)

    row = await _require_presentation(supabase, presentation_id, owner_id, write=True)
    if not row.get("spec"):
        raise NotFoundError("Presentation specification not found")
    current_spec = PresentationSpec.model_validate(row["spec"])

    from app.core.brand import get_brand_context

    brand_context = await get_brand_context(supabase, owner_id)
    result: SpecEditResult = await provider.edit_spec(
        current_spec, req.instruction, req.target_indexes, model=model,
        brand_context=brand_context,
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

    if not row.get("spec"):
        raise NotFoundError("Presentation specification not found")
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
