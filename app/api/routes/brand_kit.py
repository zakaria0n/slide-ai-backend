"""Per-user brand kit — logo + colors + fonts applied to every deck render."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.deps import owner_id
from app.core.config import Settings

router = APIRouter(prefix="/brand-kit", tags=["brand-kit"])


def _supabase_dep(request: Request):
    return request.app.state.supabase

_COLOR_MAX = 40
_FONT_MAX = 120


class BrandKitRequest(BaseModel):
    logo_url: str | None = Field(default=None, max_length=2000)
    color_primary: str | None = Field(default=None, max_length=_COLOR_MAX)
    color_secondary: str | None = Field(default=None, max_length=_COLOR_MAX)
    font_heading: str | None = Field(default=None, max_length=_FONT_MAX)
    font_body: str | None = Field(default=None, max_length=_FONT_MAX)


class BrandKitResponse(BaseModel):
    logo_url: str | None = None
    color_primary: str | None = None
    color_secondary: str | None = None
    font_heading: str | None = None
    font_body: str | None = None
    updated_at: str | None = None


def _to_response(row: dict | None) -> BrandKitResponse:
    if not row:
        return BrandKitResponse()
    return BrandKitResponse(
        logo_url=row.get("logo_url"),
        color_primary=row.get("color_primary"),
        color_secondary=row.get("color_secondary"),
        font_heading=row.get("font_heading"),
        font_body=row.get("font_body"),
        updated_at=str(row.get("updated_at") or "") or None,
    )


@router.get("", response_model=BrandKitResponse)
async def get_brand_kit(
    oid = Depends(owner_id),
    supabase = Depends(_supabase_dep),
) -> BrandKitResponse:
    import app.db as db

    return _to_response(await db.get_brand_kit(supabase, oid))


@router.put("", response_model=BrandKitResponse)
async def upsert_brand_kit(
    req: BrandKitRequest,
    request: Request,
    oid = Depends(owner_id),
    supabase = Depends(_supabase_dep),
) -> BrandKitResponse:
    import app.db as db

    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    row = await db.upsert_brand_kit(supabase, oid, **fields)
    return _to_response(row)

