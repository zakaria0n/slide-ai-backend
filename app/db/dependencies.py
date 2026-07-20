"""FastAPI database dependencies.

Exposes :func:`get_session` for routes and a lifespan-aware holder that
owns the engine. Keeping the engine lifecycle here (not in the DI
container singletons) makes startup/shutdown explicit and testable.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

if TYPE_CHECKING:  # pragma: no cover
    pass


class Database:
    """Owns the async engine and session factory for the process."""

    def __init__(self, engine: AsyncEngine, factory: async_sessionmaker[AsyncSession]) -> None:
        self._engine = engine
        self._factory = factory

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._factory

    async def dispose(self) -> None:
        await self._engine.dispose()


async def get_session(db: Database) -> AsyncIterator[AsyncSession]:
    """Yield an async session bound to the application engine.

    The session is closed automatically when the generator exits; it is the
    route's responsibility to commit (or the service layer's). Unit-of-work
    boundaries are owned by the calling service, not by this dependency.
    """
    session = db.session_factory()
    try:
        yield session
    finally:
        await session.close()
