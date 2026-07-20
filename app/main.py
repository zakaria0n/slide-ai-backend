"""FastAPI application factory and lifespan management."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from sqlalchemy import text
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.handlers import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.db.dependencies import Database
from app.providers.container import Container
from app.api.routes.health import router as health_router


logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown resources.

    Startup: configure logging, build the DB engine, verify connectivity.
    Shutdown: dispose the engine and release connections.
    """
    settings: Settings = app.state.settings
    setup_logging(settings)
    logger.info(
        "Starting %s (env=%s, version=%s)",
        settings.project_name,
        settings.app_env,
        settings.api_version,
    )

    # Composition root: the DI container owns the engine and factory.
    container = Container(config=settings)
    engine = container.engine()
    factory = container.session_factory()
    app.state.db = Database(engine=engine, factory=factory)

    # Verify the database accepts connections before serving traffic.
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - depends on live DB
        logger.warning("Database connectivity check failed at startup: %s", exc)

    logger.info("Startup complete.")
    yield

    await app.state.db.dispose()
    logger.info("Shutdown complete.")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = settings or get_settings()

    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        description=(
            "Slide AI backend API. The AI provider is exposed only as "
            "'Slide AI'."
        ),
        lifespan=lifespan,
        debug=settings.app_debug,
    )
    app.state.settings = settings

    # CORS: restrict to configured origins in production.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    # Routers
    api_prefix = settings.api_v1_prefix
    app.include_router(health_router, prefix=api_prefix)

    @app.get("/", tags=["meta"])
    async def root() -> dict[str, str]:
        return {
            "service": settings.project_name,
            "version": settings.api_version,
            "docs": "/docs",
        }

    return app


# Application entrypoint instance (used by uvicorn via "app.main:app").
app = create_app()
