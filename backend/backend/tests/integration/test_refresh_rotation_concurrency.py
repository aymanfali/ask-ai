from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ask_ai.core.config import Settings
from ask_ai.database.base import Base
from ask_ai.modules.auth.models import RefreshSession
from ask_ai.modules.auth.service import AuthService


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_refresh_reuse_revokes_the_session_family() -> None:
    database_url = os.getenv("AUTH_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set AUTH_TEST_DATABASE_URL to a disposable PostgreSQL database")

    if not database_url.startswith("postgresql+asyncpg://"):
        pytest.fail("AUTH_TEST_DATABASE_URL must use postgresql+asyncpg")

    # Never create/drop test tables in the database's shared public schema.
    # A unique schema confines the destructive create_all/drop to this test run.
    schema_name = f"ask_ai_auth_test_{uuid4().hex}"
    admin_engine = create_async_engine(database_url)
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))

    engine = None

    class RedisStub:
        async def set(self, *args, **kwargs):
            return True

        async def getdel(self, *args, **kwargs):
            return None

    settings = Settings(app_env="test")
    redis = RedisStub()
    try:
        engine = create_async_engine(
            database_url,
            pool_size=5,
            max_overflow=5,
            connect_args={"server_settings": {"search_path": schema_name}},
        )
        factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with factory() as seed_session:
            user, tokens = await AuthService(seed_session, settings, redis).register(
                email=f"refresh-race-{uuid4().hex}@example.com",
                password="concurrency-test-password-123",
                display_name=None,
            )

        async def attempt_refresh():
            async with factory() as session:
                try:
                    return await AuthService(session, settings, redis).refresh(tokens.refresh_token)
                except Exception:
                    return None

        results = await asyncio.gather(attempt_refresh(), attempt_refresh())
        # One request may rotate successfully, but the competing reuse must revoke the family.
        assert sum(result is not None for result in results) == 1
        async with factory() as verify_session:
            from sqlalchemy import select

            rows = (
                await verify_session.scalars(
                    select(RefreshSession).where(RefreshSession.user_id == user.id)
                )
            ).all()
            assert rows
            assert all(row.revoked_at is not None for row in rows)
    finally:
        if engine is not None:
            await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        await admin_engine.dispose()
