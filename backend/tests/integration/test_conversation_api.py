from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ask_ai.core.config import Settings
from ask_ai.database.base import Base
from ask_ai.database.session import get_db_session
from ask_ai.main import create_app
from ask_ai.modules.auth.dependencies import get_current_user
from ask_ai.modules.auth.models import User


@pytest.fixture
async def conversation_api_client() -> AsyncIterator[tuple[AsyncClient, User]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    async with factory() as session:
        user = User(email=f"api-owner-{uuid4().hex}@example.com", is_active=True)
        session.add(user)
        await session.commit()
        await session.refresh(user)

    settings = Settings(
        app_env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        secret_key="conversation-api-test-secret-that-is-at-least-32-bytes",
    )
    app = create_app(settings)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    async def override_user() -> User:
        return user

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield client, user
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()


@pytest.mark.asyncio
async def test_conversation_and_message_http_lifecycle(conversation_api_client) -> None:
    client, _ = conversation_api_client

    created = await client.post("/api/v1/conversations", json={})
    assert created.status_code == 201
    conversation = created.json()
    conversation_id = conversation["id"]
    assert conversation["title"] == "New conversation"

    appended = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "  Explain database transactions  "},
    )
    assert appended.status_code == 201
    message = appended.json()
    assert message["role"] == "user"
    assert message["content"] == "Explain database transactions"
    assert message["sequence"] == 1

    history = await client.get(f"/api/v1/conversations/{conversation_id}/messages")
    assert history.status_code == 200
    assert [item["id"] for item in history.json()["items"]] == [message["id"]]

    renamed = await client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"title": "Transactions"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Transactions"

    listing = await client.get("/api/v1/conversations")
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()["items"]] == [conversation_id]

    deleted = await client.delete(f"/api/v1/conversations/{conversation_id}")
    assert deleted.status_code == 204
    missing = await client.get(f"/api/v1/conversations/{conversation_id}")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_conversation_api_validation_and_missing_ids(conversation_api_client) -> None:
    client, _ = conversation_api_client

    invalid = await client.post("/api/v1/conversations", json={"title": "   "})
    assert invalid.status_code == 422

    missing = await client.get(f"/api/v1/conversations/{uuid4()}")
    assert missing.status_code == 404
