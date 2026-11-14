from collections.abc import AsyncIterator
from typing import cast

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped session; transaction boundaries stay in services."""
    session_factory = getattr(request.app.state, "db_session_factory", None)
    if session_factory is None:
        raise RuntimeError("Database session factory has not been initialized")

    factory = cast(async_sessionmaker[AsyncSession], session_factory)
    async with factory() as session:
        yield session
