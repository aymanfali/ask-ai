from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ask_ai.core.config import Settings


def create_database_engine(settings: Settings) -> AsyncEngine:
    """Create the async engine without opening a network connection.

    The SQLite branch is intended for isolated tests. Runtime environments should
    use PostgreSQL through asyncpg.
    """
    database_url = settings.database_url.get_secret_value()
    options: dict[str, Any] = {
        "pool_pre_ping": True,
    }
    if database_url.startswith("postgresql+asyncpg://"):
        options.update(
            {
                "pool_size": settings.db_pool_size,
                "max_overflow": settings.db_max_overflow,
                "pool_timeout": settings.db_pool_timeout_seconds,
                "pool_recycle": settings.db_pool_recycle_seconds,
                "connect_args": {"timeout": settings.db_connect_timeout_seconds},
            }
        )
    return create_async_engine(database_url, **options)
