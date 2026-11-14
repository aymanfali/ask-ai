import asyncio
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.integration
def test_alembic_upgrade_head_on_fresh_database(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    monkeypatch.setenv("MIGRATION_DATABASE_URL", database_url)
    config_path = Path(__file__).parents[2] / "alembic.ini"
    config = Config(str(config_path))

    command.upgrade(config, "head")

    # The CI database is disposable and starts empty for each workflow run.
    async def read_revision() -> str:
        engine = create_async_engine(database_url)
        try:
            async with engine.connect() as connection:
                result = await connection.execute(
                    text("SELECT version_num FROM alembic_version")
                )
                return str(result.scalar_one())
        finally:
            await engine.dispose()

    revision = asyncio.run(read_revision())
    assert revision == "20261114_0001"
