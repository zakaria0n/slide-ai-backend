"""Dependency injection container.

Uses ``dependency-injector`` to wire configuration, the database engine,
and the async session factory. The container is populated during the
application lifespan (the engine is created lazily so tests can override
it). FastAPI routes receive dependencies via ``Depends``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from dependency_injector import containers, providers

from app.core.config import Settings, get_settings
from app.db.session import (
    AsyncEngine,
    async_sessionmaker,
    build_engine,
    build_session_factory,
)

if TYPE_CHECKING:  # pragma: no cover
    pass


class Container(containers.DeclarativeContainer):
    """Application composition root."""

    config = providers.Singleton(get_settings)

    # Engine and session factory are provided as factories so the test
    # suite can replace them with an in-memory/overridden engine.
    engine = providers.Singleton(
        build_engine,
        settings=config,
    )

    session_factory = providers.Singleton(
        build_session_factory,
        engine=engine,
    )
