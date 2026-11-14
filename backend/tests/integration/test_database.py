import os

import pytest
from sqlalchemy import text

from ask_ai.core.config import Settings
from ask_ai.database.engine import create_database_engine


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_connection_and_query() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    settings = Settings(app_env="test", database_url=database_url)
    engine = create_database_engine(settings)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            assert result.scalar_one() == 1
    finally:
        await engine.dispose()
