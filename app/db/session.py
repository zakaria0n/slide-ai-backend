"""Async SQLAlchemy engine and session management.

The backend talks to the Supabase PostgreSQL database through an async
engine (``asyncpg``). A single engine is created per process and shared
across requests via ``AsyncSessionFactory``.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings

if TYPE_CHECKING:  # pragma: no cover
    pass


def build_engine(settings: Settings) -> AsyncEngine:
    """Create the async engine from application settings."""
    connect_args: dict[str, object] = {}
    return create_async_engine(
        settings.sqlalchemy_database_uri,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create the async session factory bound to an engine."""
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Provide a transactional async session scope.

    Commits on success, rolls back on error, and always closes the
    session. Business code should not manage transactions manually.
    """
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def is_sync_session(obj: object) -> bool:  # pragma: no cover - helper
    """Type guard: returns True for a synchronous SQLAlchemy session."""
    return isinstance(obj, Session)
