"""Asset search routes.

- ``GET /assets/search?q=&kind=&limit=``
"""
from __future__ import annotations

from enum import Enum

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.assets.provider import AssetKind, AssetRef, build_asset_registry

router = APIRouter(prefix="/assets", tags=["assets"])


class AssetKindParam(str, Enum):
    image = "image"
    icon = "icon"
    svg = "svg"


class AssetResponse(BaseModel):
    id: str
    kind: str
    url: str
    thumbnail: str | None = None
    attribution: str | None = None
    provider: str = ""

    @classmethod
    def from_ref(cls, ref: AssetRef) -> "AssetResponse":
        return cls(
            id=ref.id,
            kind=ref.kind.value,
            url=ref.url,
            thumbnail=ref.thumbnail,
            attribution=ref.attribution,
            provider=ref.provider,
        )


class AssetSearchResponse(BaseModel):
    items: list[AssetResponse]
    total: int


@router.get("/search", response_model=AssetSearchResponse)
async def search_assets(
    q: str = Query("", description="Search query"),
    kind: AssetKindParam = Query(AssetKindParam.image, description="Asset kind"),
    limit: int = Query(12, ge=1, le=50),
) -> AssetSearchResponse:
    """Search for assets across registered providers."""
    registry = build_asset_registry()
    kind_enum = AssetKind(kind.value)
    results = await registry.search(q, kind_enum, limit)
    return AssetSearchResponse(
        items=[AssetResponse.from_ref(r) for r in results],
        total=len(results),
    )
