from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.integration
def test_alembic_upgrade_head_on_fresh_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    if not database_url.startswith("postgresql+asyncpg://"):
        pytest.fail("TEST_DATABASE_URL must use postgresql+asyncpg")

    schema_name = f"ask_ai_migration_test_{uuid4().hex}"
    admin_engine = create_async_engine(database_url)

    async def create_schema() -> None:
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))

    async def read_revision_and_tables() -> tuple[str, set[str]]:
        engine = create_async_engine(
            database_url,
            connect_args={"server_settings": {"search_path": schema_name}},
        )
        try:
            async with engine.connect() as connection:
                revision_result = await connection.execute(
                    text("SELECT version_num FROM alembic_version")
                )
                revision = str(revision_result.scalar_one())
                table_result = await connection.execute(
                    text(
                        "SELECT tablename FROM pg_tables "
                        "WHERE schemaname = current_schema() "
                        "AND tablename IN ('users', 'auth_identities', 'refresh_sessions', "
                        "'conversations', 'messages', 'generation_requests', 'usage_ledger')"
                    )
                )
                return revision, set(table_result.scalars().all())
        finally:
            await engine.dispose()

    async def drop_schema() -> None:
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))

    asyncio.run(create_schema())
    monkeypatch.setenv("MIGRATION_DATABASE_URL", database_url)
    monkeypatch.setenv("MIGRATION_SCHEMA", schema_name)
    config_path = Path(__file__).parents[2] / "alembic.ini"
    config = Config(str(config_path))
    try:
        command.upgrade(config, "head")
        revision, tables = asyncio.run(read_revision_and_tables())
        assert revision == "20261115_0004"
        assert tables == {
            "users",
            "auth_identities",
            "refresh_sessions",
            "conversations",
            "messages",
            "generation_requests",
            "usage_ledger",
        }
    finally:
        asyncio.run(drop_schema())
        asyncio.run(admin_engine.dispose())
