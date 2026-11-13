from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine


def make_engine(url: str, pool_size: int, max_overflow: int) -> AsyncEngine:
    """One engine (and connection pool) per process.

    Opening a Postgres connection takes a TCP handshake, auth and a backend process,
    so the pool keeps `pool_size` connections open and reuses them, allowing up to
    `max_overflow` extra connections during spikes. pool_pre_ping drops connections
    that died (e.g. Postgres restarted) before handing them out.
    """
    if url.startswith("sqlite"):
        return create_async_engine(url)  # tests only; SQLite has no real pool
    return create_async_engine(
        url, pool_size=pool_size, max_overflow=max_overflow, pool_pre_ping=True
    )


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, closed when the request ends."""
    async with request.app.state.sessionmaker() as session:
        yield session
