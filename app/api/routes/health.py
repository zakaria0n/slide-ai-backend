"""Health and system status endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.core.config import Settings, get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str
    provider: str


class ReadyResponse(BaseModel):
    status: str
    database: str


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


@router.get("/health/ready", response_model=ReadyResponse)
async def readiness(request: Request) -> ReadyResponse:
    """Readiness check. Verifies database connectivity."""
    try:
        db = request.app.state.db
        async with db.engine.connect() as conn:
            from sqlalchemy import text
            await conn.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "unavailable"
    return ReadyResponse(status="ok" if db_status == "ok" else "degraded", database=db_status)
