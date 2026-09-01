"""User-saved custom themes.

A theme is a name + a JSON blob of renderer tokens (colors, fonts, ambient
motion) matching the frontend ThemeTokens shape. Stored verbatim so the
backend never has to chase frontend token evolution.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.deps import owner_id

router = APIRouter(prefix="/themes", tags=["themes"])

_NAME_MAX = 60


def _supabase_dep(request: Request):
    return request.app.state.supabase


class ThemeTokensPayload(BaseModel):
    """Free-form renderer tokens (validated client-side)."""

    model_config = {"extra": "allow"}

    bg: str | None = Field(default=None, max_length=2000)
    text: str | None = Field(default=None, max_length=2000)


class CreateUserThemeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=_NAME_MAX)
    # Full token set as camelCase JSON (bg, text, accent, gradient, fonts…).
    tokens: dict = Field(default_factory=dict)
    # Optional ambient motion spec ({kind, colors, opacity, speed}).
    ambient: dict | None = None


class UserThemeResponse(BaseModel):
    id: str
    name: str
    tokens: dict
    ambient: dict | None = None
    created_at: str | None = None


class UserThemeListResponse(BaseModel):
    themes: list[UserThemeResponse]


def _to_response(row: dict) -> UserThemeResponse:
    return UserThemeResponse(
        id=str(row["id"]),
        name=str(row.get("name") or ""),
        tokens=row.get("tokens") or {},
        ambient=row.get("ambient"),
        created_at=row.get("created_at"),
    )


@router.get("", response_model=UserThemeListResponse)
async def list_themes(
    oid=Depends(owner_id),
    supabase=Depends(_supabase_dep),
) -> UserThemeListResponse:
    import app.db as db

    rows = await db.list_user_themes(supabase, oid)
    return UserThemeListResponse(themes=[_to_response(r) for r in rows])


@router.post("", response_model=UserThemeResponse, status_code=201)
async def create_theme(
    req: CreateUserThemeRequest,
    oid=Depends(owner_id),
    supabase=Depends(_supabase_dep),
) -> UserThemeResponse:
    import app.db as db

    row = await db.create_user_theme(
        supabase,
        user_id=str(oid),
        name=req.name.strip()[:_NAME_MAX],
        tokens=req.tokens,
        ambient=req.ambient,
    )
    return _to_response(row)


@router.delete("/{theme_id}", status_code=204)
async def delete_theme(
    theme_id: UUID,
    oid=Depends(owner_id),
    supabase=Depends(_supabase_dep),
) -> None:
    import app.db as db

    await db.delete_user_theme(supabase, theme_id, oid)
