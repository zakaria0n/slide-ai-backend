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
from app.api.routes.auth import router as auth_router
from app.presentations.routes import router as presentations_router
from app.files.routes import router as files_router
from app.assets.routes import router as assets_router
from app.templates.routes import router as templates_router


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

    # Wire the Supabase-backed auth provider when configured; otherwise
    # fall back to the in-memory fake so the app runs offline / in tests.
    from app.auth.providers.fake import FakeAuthProvider
    from app.auth.providers.supabase import SupabaseAuthProvider

    _secret = settings.supabase_jwt_secret or "dev-insecure-secret"
    if settings.supabase_url and settings.supabase_service_role_key:
        from supabase import AsyncClient, AsyncClientOptions, create_async_client

        supabase_client: AsyncClient = await create_async_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
            options=AsyncClientOptions(auto_refresh_token=False, persist_session=False),
        )
        app.state.auth_provider = SupabaseAuthProvider(supabase_client)
        logger.info("Auth provider: Supabase")
        from app.files.storage import SupabaseStorageGateway

        app.state.storage = SupabaseStorageGateway(supabase_client)
        logger.info("Storage: Supabase")
    else:
        app.state.auth_provider = FakeAuthProvider(_secret)
        logger.info("Auth provider: in-memory fake (Supabase not configured)")
        from app.files.storage import InMemoryStorageGateway

        app.state.storage = InMemoryStorageGateway()
        logger.info("Storage: in-memory (Supabase not configured)")

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
    # Shared, per-application auth provider (in-memory fake by default;
    # production wiring swaps this for the Supabase-backed provider).
    from app.auth.jwt_verifier import JWTVerifier
    from app.auth.providers.fake import FakeAuthProvider
    _secret = settings.supabase_jwt_secret or "dev-insecure-secret"
    app.state.auth_provider = FakeAuthProvider(_secret)
    app.state.jwt_verifier = JWTVerifier(_secret)

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
    app.include_router(auth_router, prefix=api_prefix)
    app.include_router(presentations_router, prefix=api_prefix)
    app.include_router(files_router, prefix=api_prefix)
    app.include_router(assets_router, prefix=api_prefix)
    app.include_router(templates_router, prefix=api_prefix)

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
