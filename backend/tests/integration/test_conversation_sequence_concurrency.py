from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ask_ai.database.base import Base
from ask_ai.modules.auth.models import User
from ask_ai.modules.conversations.models import Conversation, Message
from ask_ai.modules.conversations.service import ConversationService


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_message_appends_allocate_unique_monotonic_sequences() -> None:
    database_url = os.getenv("CONVERSATION_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set CONVERSATION_TEST_DATABASE_URL to a disposable PostgreSQL database")
    if not database_url.startswith("postgresql+asyncpg://"):
        pytest.fail("CONVERSATION_TEST_DATABASE_URL must use postgresql+asyncpg")

    schema_name = f"ask_ai_conversation_test_{uuid4().hex}"
    admin_engine = create_async_engine(database_url)
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))

    engine = None
    try:
        engine = create_async_engine(
            database_url,
            pool_size=12,
            max_overflow=4,
            connect_args={"server_settings": {"search_path": schema_name}},
        )
        factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with factory() as session:
            user = User(email=f"sequence-{uuid4().hex}@example.com", is_active=True)
            session.add(user)
            await session.flush()
            conversation = Conversation(user_id=user.id, title="Concurrent writes")
            session.add(conversation)
            await session.commit()
            user_id, conversation_id = user.id, conversation.id

        async def append(index: int) -> int:
            async with factory() as session:
                message = await ConversationService(session).append_user_message(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    content=f"Concurrent message {index}",
                )
                return message.sequence

        sequences = await asyncio.gather(*(append(index) for index in range(12)))
        assert sorted(sequences) == list(range(1, 13))

        async with factory() as session:
            stored_conversation = await session.get(Conversation, conversation_id)
            messages = list(
                (
                    await session.scalars(
                        select(Message)
                        .where(Message.conversation_id == conversation_id)
                        .order_by(Message.sequence)
                    )
                ).all()
            )
            assert stored_conversation is not None
            assert stored_conversation.last_message_sequence == 12
            assert [message.sequence for message in messages] == list(range(1, 13))
    finally:
        if engine is not None:
            await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        await admin_engine.dispose()
