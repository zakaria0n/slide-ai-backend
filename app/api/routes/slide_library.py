"""Personal slide library — save and reuse slides across decks."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from supabase import AsyncClient

from app.api.deps import owner_id, supabase

router = APIRouter(prefix="/slide-library", tags=["slide-library"])

_TITLE_MAX = 200


class LibrarySlideRequest(BaseModel):
    title: str = Field(default="", max_length=_TITLE_MAX)
    slide: dict = Field(..., description="Serialized SlideSpec")


def _clean_slide(slide: dict) -> dict:
    """Strip identity fields — a library slide is a template, not a copy."""
    cleaned = dict(slide)
    for el in cleaned.get("elements", []) or []:
        if isinstance(el, dict):
            el.pop("id", None)
    return cleaned


@router.get("")
async def list_library_slides(
    oid: UUID = Depends(owner_id),
    supabase: AsyncClient = Depends(supabase),
) -> dict:
    resp = (
        await supabase.table("slide_library")
        .select("id,title,slide,created_at")
        .eq("user_id", str(oid))
        .order("created_at", desc=True)
        .limit(200)
        .execute()
    )
    return {"slides": resp.data}


@router.post("", status_code=201)
async def save_library_slide(
    req: LibrarySlideRequest,
    oid: UUID = Depends(owner_id),
    supabase: AsyncClient = Depends(supabase),
) -> dict:
    resp = (
        await supabase.table("slide_library")
        .insert({"user_id": str(oid), "title": req.title.strip()[:_TITLE_MAX], "slide": _clean_slide(req.slide)})
        .execute()
    )
    return resp.data[0]


@router.delete("/{slide_id}", status_code=204)
async def delete_library_slide(
    slide_id: UUID,
    oid: UUID = Depends(owner_id),
    supabase: AsyncClient = Depends(supabase),
) -> None:
    existing = (
        await supabase.table("slide_library")
        .select("id")
        .eq("id", str(slide_id))
        .eq("user_id", str(oid))
        .limit(1)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Library slide not found")
    await supabase.table("slide_library").delete().eq("id", str(slide_id)).execute()
