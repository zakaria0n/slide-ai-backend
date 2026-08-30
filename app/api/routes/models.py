"""Model catalog endpoint — lets users pick the model Slide AI uses.

The concrete model ids come from the provider catalog; the provider itself
is still surfaced only as "Slide AI".
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.api.deps import owner_id
from app.core.config import Settings
from app.core.model_catalog import list_models

router = APIRouter(tags=["models"])


class ModelInfo(BaseModel):
    id: str
    owned_by: str = "opencode"


class ModelsResponse(BaseModel):
    provider: str
    default: str
    models: list[ModelInfo]


@router.get("/models", response_model=ModelsResponse)
async def get_models(
    request: Request,
    oid: str = Depends(owner_id),
) -> ModelsResponse:
    """List the models the caller may select (settings page, AI panel)."""
    settings: Settings = request.app.state.settings
    models = await list_models(settings)
    return ModelsResponse(
        provider=settings.displayed_provider_name,
        default=settings.ai_provider_default_model,
        models=[ModelInfo(id=m["id"], owned_by=m["owned_by"]) for m in models],
    )
