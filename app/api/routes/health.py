"""Health and system status endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.config import Settings, get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str
    provider: str


@router.get("/health", response_model=HealthResponse)
async def health(
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    """Liveness check. Returns service metadata.

    The ``provider`` field always reports the public name ``Slide AI``;
    the underlying provider implementation is never exposed.
    """
    return HealthResponse(
        status="ok",
        service=settings.project_name,
        version=settings.api_version,
        environment=settings.app_env,
        provider=settings.displayed_provider_name,
    )
