"""FastAPI application factory and lifespan management."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.handlers import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.api.routes.health import router as health_router
from app.api.routes.auth import router as auth_router
from app.presentations.routes import router as presentations_router
from app.files.routes import router as files_router
from app.assets.routes import router as assets_router
from app.templates.routes import router as templates_router
from app.sharing.routes import router as sharing_router
from app.workspaces.routes import router as workspaces_router
from app.chat.routes import router as chat_router
from app.api.routes.models import router as models_router
from app.api.routes.brand_kit import router as brand_kit_router
from app.api.routes.slide_library import router as slide_library_router
from app.api.routes.oauth import router as oauth_router
from app.api.routes.skill import router as skill_router
from app.mcp.routes import router as mcp_router


logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown resources.

    Startup: configure logging, create the Supabase AsyncClient.
    Shutdown: nothing to dispose (AsyncClient is stateless).
    """
    settings: Settings = app.state.settings
    setup_logging(settings)
    logger.info(
        "Starting %s (env=%s, version=%s)",
        settings.project_name,
        settings.app_env,
        settings.api_version,
    )

    # Create the Supabase client used by all data-access.
    from supabase import AsyncClient, AsyncClientOptions, create_async_client

    use_supabase = bool(settings.supabase_url and settings.supabase_service_role_key)
    if use_supabase:
        try:
            supabase_client: AsyncClient = await create_async_client(
                settings.supabase_url,
                settings.supabase_service_role_key,
                options=AsyncClientOptions(auto_refresh_token=False, persist_session=False),
            )
            app.state.supabase = supabase_client

            # Auth provider. Uses a SEPARATE client so that signup/signin
            # (which store the end-user's JWT as the session) never switch the
            # shared data client into the user role. The data client keeps the
            # service-role key and therefore bypasses RLS; otherwise queries
            # run as the user and hit broken policies (e.g. the infinite
            # recursion between workspaces and workspace_members).
            auth_client: AsyncClient = await create_async_client(
                settings.supabase_url,
                settings.supabase_service_role_key,
                options=AsyncClientOptions(auto_refresh_token=False, persist_session=False),
            )
            from app.auth.providers.supabase import SupabaseAuthProvider
            app.state.auth_provider = SupabaseAuthProvider(auth_client)
            logger.info("Auth provider: Supabase")

            # Storage gateway.
            from app.files.storage import SupabaseStorageGateway
            app.state.storage = SupabaseStorageGateway(supabase_client)
            logger.info("Storage: Supabase")
        except Exception as exc:
            logger.warning("Supabase init failed, falling back to fake: %s", exc)
            use_supabase = False

    if not use_supabase:
        from app.auth.providers.fake import FakeAuthProvider
        from app.files.storage import InMemoryStorageGateway

        _secret = settings.supabase_jwt_secret or "dev-insecure-secret"
        app.state.auth_provider = FakeAuthProvider(_secret)
        app.state.storage = InMemoryStorageGateway()
        logger.info("Auth provider: in-memory fake")
        logger.info("Storage: in-memory")

        # For local dev without Supabase, create a minimal fake client.
        # The app won't persist data but will start without errors.
        from unittest.mock import AsyncMock
        app.state.supabase = AsyncMock()

    logger.info("Startup complete.")
    yield
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

    from app.auth.jwt_verifier import JWTVerifier
    from app.auth.providers.fake import FakeAuthProvider

    if not settings.supabase_jwt_secret and settings.app_env != "development":
        raise RuntimeError(
            "SUPABASE_JWT_SECRET is required in non-development environments. "
            "Refusing to start with an insecure fallback."
        )
    _secret = settings.supabase_jwt_secret or "dev-insecure-secret"
    app.state.auth_provider = FakeAuthProvider(_secret)
    app.state.jwt_verifier = JWTVerifier(
        _secret, supabase_url=settings.supabase_url or ""
    )

    # CORS: restrict to configured origins in production.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    # Routers — each sub-router defines its own prefix (e.g. "/presentations").
    # Mount all under /api/v1 directly on the app.
    v1 = settings.api_v1_prefix
    app.include_router(health_router, prefix=v1)
    app.include_router(auth_router, prefix=v1)
    app.include_router(presentations_router, prefix=v1)
    app.include_router(files_router, prefix=v1)
    app.include_router(assets_router, prefix=v1)
    app.include_router(templates_router, prefix=v1)
    app.include_router(sharing_router, prefix=v1)
    app.include_router(workspaces_router, prefix=v1)
    app.include_router(chat_router, prefix=v1)
    app.include_router(models_router, prefix=v1)
    app.include_router(brand_kit_router, prefix=v1)
    app.include_router(slide_library_router, prefix=v1)
    app.include_router(oauth_router, prefix=v1)
    app.include_router(skill_router, prefix=v1)
    app.include_router(mcp_router, prefix=v1)

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