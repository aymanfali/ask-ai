from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ask_ai.core.errors import ApplicationError
from ask_ai.database.base import Base
from ask_ai.modules.auth.models import User
from ask_ai.modules.conversations.models import Conversation, Message
from ask_ai.modules.conversations.service import ConversationService


@pytest.fixture
async def conversation_context():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    first_user = User(email=f"owner-{uuid4().hex}@example.com", is_active=True)
    second_user = User(email=f"other-{uuid4().hex}@example.com", is_active=True)
    async with factory() as session:
        session.add_all([first_user, second_user])
        await session.commit()
        await session.refresh(first_user)
        await session.refresh(second_user)
    try:
        yield factory, first_user.id, second_user.id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_conversation_and_keyset_cursor_pages(conversation_context) -> None:
    factory, owner_id, _ = conversation_context
    async with factory() as session:
        service = ConversationService(session)
        created = [
            await service.create_conversation(user_id=owner_id, title=f"Conversation {index}")
            for index in range(5)
        ]
        first_page, cursor = await service.list_conversations(
            user_id=owner_id, limit=2, cursor=None
        )
        assert len(first_page) == 2
        assert cursor is not None

        second_page, second_cursor = await service.list_conversations(
            user_id=owner_id, limit=2, cursor=cursor
        )
        assert len(second_page) == 2
        assert second_cursor is not None

        third_page, third_cursor = await service.list_conversations(
            user_id=owner_id, limit=2, cursor=second_cursor
        )
        assert len(third_page) == 1
        assert third_cursor is None

        paged_ids = [item.id for item in first_page + second_page + third_page]
        assert len(paged_ids) == 5
        assert len(set(paged_ids)) == 5
        assert set(paged_ids) == {item.id for item in created}


@pytest.mark.asyncio
async def test_invalid_conversation_cursor_is_rejected(conversation_context) -> None:
    factory, owner_id, _ = conversation_context
    async with factory() as session:
        with pytest.raises(ApplicationError) as error:
            await ConversationService(session).list_conversations(
                user_id=owner_id, limit=10, cursor="not-a-valid-cursor"
            )
    assert error.value.code == "invalid_pagination_cursor"
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_other_users_cannot_read_or_append_to_conversation(conversation_context) -> None:
    factory, owner_id, other_id = conversation_context
    async with factory() as session:
        conversation = await ConversationService(session).create_conversation(user_id=owner_id)

    async with factory() as session:
        service = ConversationService(session)
        with pytest.raises(ApplicationError) as read_error:
            await service.get_conversation(user_id=other_id, conversation_id=conversation.id)
        assert read_error.value.status_code == 404

        with pytest.raises(ApplicationError) as append_error:
            await service.append_user_message(
                user_id=other_id,
                conversation_id=conversation.id,
                content="This must not be stored",
            )
        assert append_error.value.status_code == 404

        other_conversations, _ = await service.list_conversations(
            user_id=other_id, limit=10, cursor=None
        )
        assert other_conversations == []


@pytest.mark.asyncio
async def test_append_messages_allocates_sequences_and_derives_initial_title(
    conversation_context,
) -> None:
    factory, owner_id, _ = conversation_context
    async with factory() as session:
        service = ConversationService(session)
        conversation = await service.create_conversation(user_id=owner_id)
        first = await service.append_user_message(
            user_id=owner_id,
            conversation_id=conversation.id,
            content="  Explain event-driven architecture\nwith an example.  ",
        )
        second = await service.append_user_message(
            user_id=owner_id,
            conversation_id=conversation.id,
            content="What are the trade-offs?",
        )

        assert first.sequence == 1
        assert second.sequence == 2
        assert first.role == "user"
        assert first.status == "complete"

        stored = await session.get(Conversation, conversation.id)
        assert stored is not None
        assert stored.last_message_sequence == 2
        assert stored.title == "Explain event-driven architecture"

        persisted = list(
            (
                await session.scalars(
                    select(Message)
                    .where(Message.conversation_id == conversation.id)
                    .order_by(Message.sequence)
                )
            ).all()
        )
        assert [message.sequence for message in persisted] == [1, 2]


@pytest.mark.asyncio
async def test_message_history_returns_chronological_pages(conversation_context) -> None:
    factory, owner_id, _ = conversation_context
    async with factory() as session:
        service = ConversationService(session)
        conversation = await service.create_conversation(user_id=owner_id)
        for index in range(5):
            await service.append_user_message(
                user_id=owner_id,
                conversation_id=conversation.id,
                content=f"Message {index + 1}",
            )

        newest, before = await service.list_messages(
            user_id=owner_id,
            conversation_id=conversation.id,
            limit=2,
            before_sequence=None,
        )
        assert [item.sequence for item in newest] == [4, 5]
        assert before == 4

        older, older_before = await service.list_messages(
            user_id=owner_id,
            conversation_id=conversation.id,
            limit=2,
            before_sequence=before,
        )
        assert [item.sequence for item in older] == [2, 3]
        assert older_before == 2

        oldest, oldest_before = await service.list_messages(
            user_id=owner_id,
            conversation_id=conversation.id,
            limit=2,
            before_sequence=older_before,
        )
        assert [item.sequence for item in oldest] == [1]
        assert oldest_before is None


@pytest.mark.asyncio
async def test_public_message_history_never_exposes_internal_policy_roles(
    conversation_context,
) -> None:
    factory, owner_id, _ = conversation_context
    async with factory() as session:
        service = ConversationService(session)
        conversation = await service.create_conversation(user_id=owner_id)
        user_message = await service.append_user_message(
            user_id=owner_id,
            conversation_id=conversation.id,
            content="Hello",
        )
        session.add_all(
            [
                Message(
                    conversation_id=conversation.id,
                    role="system",
                    content="Internal system policy",
                    status="complete",
                    sequence=2,
                ),
                Message(
                    conversation_id=conversation.id,
                    role="developer",
                    content="Internal developer policy",
                    status="complete",
                    sequence=3,
                ),
                Message(
                    conversation_id=conversation.id,
                    role="assistant",
                    content="Hello there",
                    status="complete",
                    sequence=4,
                ),
            ]
        )
        conversation.last_message_sequence = 4
        await session.commit()

        messages, before = await service.list_messages(
            user_id=owner_id,
            conversation_id=conversation.id,
            limit=10,
            before_sequence=None,
        )
        assert [(message.sequence, message.role) for message in messages] == [
            (user_message.sequence, "user"),
            (4, "assistant"),
        ]
        assert before is None


@pytest.mark.asyncio
async def test_soft_delete_hides_conversation_and_message_history(conversation_context) -> None:
    factory, owner_id, _ = conversation_context
    async with factory() as session:
        service = ConversationService(session)
        conversation = await service.create_conversation(user_id=owner_id)
        await service.append_user_message(
            user_id=owner_id, conversation_id=conversation.id, content="Retained message"
        )
        await service.soft_delete_conversation(
            user_id=owner_id, conversation_id=conversation.id
        )

        page, _ = await service.list_conversations(user_id=owner_id, limit=20, cursor=None)
        assert all(item.id != conversation.id for item in page)

        with pytest.raises(ApplicationError) as get_error:
            await service.get_conversation(user_id=owner_id, conversation_id=conversation.id)
        assert get_error.value.status_code == 404

        with pytest.raises(ApplicationError) as messages_error:
            await service.list_messages(
                user_id=owner_id,
                conversation_id=conversation.id,
                limit=20,
                before_sequence=None,
            )
        assert messages_error.value.status_code == 404

        # Soft deletion preserves messages for a future retention/purge policy.
        retained = await session.scalar(
            select(Message).where(Message.conversation_id == conversation.id)
        )
        assert retained is not None


@pytest.mark.asyncio
async def test_title_update_is_scoped_and_soft_delete_is_idempotently_hidden(
    conversation_context,
) -> None:
    factory, owner_id, other_id = conversation_context
    async with factory() as session:
        service = ConversationService(session)
        conversation = await service.create_conversation(user_id=owner_id, title="Initial")
        renamed = await service.update_conversation_title(
            user_id=owner_id,
            conversation_id=conversation.id,
            title="Renamed",
        )
        assert renamed.title == "Renamed"

        with pytest.raises(ApplicationError):
            await service.update_conversation_title(
                user_id=other_id,
                conversation_id=conversation.id,
                title="Unauthorized rename",
            )

        await service.soft_delete_conversation(user_id=owner_id, conversation_id=conversation.id)
        with pytest.raises(ApplicationError):
            await service.soft_delete_conversation(
                user_id=owner_id, conversation_id=conversation.id
            )
