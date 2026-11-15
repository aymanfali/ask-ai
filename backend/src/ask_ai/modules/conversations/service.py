from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ask_ai.core.errors import ApplicationError
from ask_ai.modules.conversations.constants import (
    AUTO_TITLE_MAX_LENGTH,
    DEFAULT_CONVERSATION_TITLE,
    MAX_CONVERSATION_TITLE_LENGTH,
    MAX_MESSAGE_CONTENT_LENGTH,
)
from ask_ai.modules.conversations.models import Conversation, Message


class ConversationService:
    """Own conversation/message business rules and transaction boundaries."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_conversation(
        self, *, user_id: UUID, title: str | None = None
    ) -> Conversation:
        normalized_title = title.strip() if title is not None else DEFAULT_CONVERSATION_TITLE
        if (
            not normalized_title
            or len(normalized_title) > MAX_CONVERSATION_TITLE_LENGTH
            or "\x00" in normalized_title
        ):
            raise ApplicationError(
                code="invalid_conversation_title",
                message="Conversation title must contain 1 to 200 characters.",
                status_code=422,
            )
        conversation = Conversation(
            user_id=user_id,
            title=normalized_title,
            last_message_sequence=0,
        )
        self.session.add(conversation)
        try:
            await self.session.commit()
            await self.session.refresh(conversation)
        except Exception:
            await self.session.rollback()
            raise
        return conversation

    async def list_conversations(
        self, *, user_id: UUID, limit: int, cursor: str | None
    ) -> tuple[list[Conversation], str | None]:
        statement = select(Conversation).where(
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
        )
        if cursor:
            cursor_updated_at, cursor_id = self._decode_conversation_cursor(cursor)
            statement = statement.where(
                or_(
                    Conversation.updated_at < cursor_updated_at,
                    and_(
                        Conversation.updated_at == cursor_updated_at,
                        Conversation.id < cursor_id,
                    ),
                )
            )

        result = await self.session.scalars(
            statement.order_by(Conversation.updated_at.desc(), Conversation.id.desc()).limit(
                limit + 1
            )
        )
        rows = list(result.all())
        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = self._encode_conversation_cursor(items[-1]) if has_more and items else None
        return items, next_cursor

    async def get_conversation(self, *, user_id: UUID, conversation_id: UUID) -> Conversation:
        conversation = await self.session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
        )
        if conversation is None:
            raise self._not_found()
        return conversation

    async def update_conversation_title(
        self, *, user_id: UUID, conversation_id: UUID, title: str
    ) -> Conversation:
        normalized_title = title.strip()
        if (
            not normalized_title
            or len(normalized_title) > MAX_CONVERSATION_TITLE_LENGTH
            or "\x00" in normalized_title
        ):
            raise ApplicationError(
                code="invalid_conversation_title",
                message="Conversation title must contain 1 to 200 characters.",
                status_code=422,
            )
        conversation = await self._lock_conversation(user_id, conversation_id)
        conversation.title = normalized_title
        conversation.updated_at = datetime.now(UTC)
        try:
            await self.session.commit()
            await self.session.refresh(conversation)
        except Exception:
            await self.session.rollback()
            raise
        return conversation

    async def soft_delete_conversation(self, *, user_id: UUID, conversation_id: UUID) -> None:
        conversation = await self._lock_conversation(user_id, conversation_id)
        now = datetime.now(UTC)
        conversation.deleted_at = now
        conversation.updated_at = now
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    async def append_user_message(
        self, *, user_id: UUID, conversation_id: UUID, content: str
    ) -> Message:
        """Append a user message while serializing writers on the conversation row.

        PostgreSQL's SELECT FOR UPDATE makes sequence allocation safe for concurrent
        requests. The unique (conversation_id, sequence) constraint is the final
        integrity guard. SQLite does not implement row-level FOR UPDATE and is used
        only for non-concurrency unit tests.
        """
        normalized_content = content.strip()
        if (
            not normalized_content
            or len(normalized_content) > MAX_MESSAGE_CONTENT_LENGTH
            or "\x00" in normalized_content
        ):
            raise ApplicationError(
                code="invalid_message_content",
                message="Message content must contain 1 to 32000 characters.",
                status_code=422,
            )
        conversation = await self._lock_conversation(user_id, conversation_id)
        sequence = conversation.last_message_sequence + 1
        message = Message(
            conversation_id=conversation.id,
            role="user",
            content=normalized_content,
            status="complete",
            sequence=sequence,
        )
        conversation.last_message_sequence = sequence
        conversation.updated_at = datetime.now(UTC)
        if sequence == 1 and conversation.title == DEFAULT_CONVERSATION_TITLE:
            conversation.title = self._derive_title(normalized_content)
        self.session.add(message)

        try:
            await self.session.flush()
            await self.session.commit()
            await self.session.refresh(message)
        except IntegrityError as exc:
            await self.session.rollback()
            raise ApplicationError(
                code="message_write_conflict",
                message=(
                    "The message could not be appended because the conversation changed. "
                    "Retry the request."
                ),
                status_code=409,
            ) from exc
        except Exception:
            await self.session.rollback()
            raise
        return message

    async def list_messages(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        limit: int,
        before_sequence: int | None,
    ) -> tuple[list[Message], int | None]:
        await self.get_conversation(user_id=user_id, conversation_id=conversation_id)
        # Internal policy messages are persisted only for trusted backend workflows.
        # They must never be exposed through the user-facing conversation history API.
        statement = select(Message).where(
            Message.conversation_id == conversation_id,
            Message.role.in_(("user", "assistant")),
        )
        if before_sequence is not None:
            statement = statement.where(Message.sequence < before_sequence)
        result = await self.session.scalars(
            statement.order_by(Message.sequence.desc()).limit(limit + 1)
        )
        rows = list(result.all())
        has_more = len(rows) > limit
        page_desc = rows[:limit]
        # The API returns chronological order, even though the query loads newest first.
        items = list(reversed(page_desc))
        next_before_sequence = items[0].sequence if has_more and items else None
        return items, next_before_sequence

    async def _lock_conversation(self, user_id: UUID, conversation_id: UUID) -> Conversation:
        conversation = await self.session.scalar(
            select(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if conversation is None:
            raise self._not_found()
        return conversation

    @staticmethod
    def _derive_title(content: str) -> str:
        first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
        if len(first_line) <= AUTO_TITLE_MAX_LENGTH:
            return first_line or DEFAULT_CONVERSATION_TITLE
        return first_line[: AUTO_TITLE_MAX_LENGTH - 1].rstrip() + "…"

    @staticmethod
    def _encode_conversation_cursor(conversation: Conversation) -> str:
        updated_at = conversation.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        payload = f"{updated_at.isoformat()}|{conversation.id}"
        return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_conversation_cursor(cursor: str) -> tuple[datetime, UUID]:
        try:
            padded = cursor + ("=" * (-len(cursor) % 4))
            decoded = base64.b64decode(padded, altchars=b"-_", validate=True).decode("utf-8")
            timestamp_text, identifier_text = decoded.split("|", maxsplit=1)
            updated_at = datetime.fromisoformat(timestamp_text)
            if updated_at.tzinfo is None:
                raise ValueError("Cursor timestamp must include timezone")
            return updated_at.astimezone(UTC), UUID(identifier_text)
        except (ValueError, TypeError, UnicodeDecodeError, binascii.Error) as exc:
            raise ApplicationError(
                code="invalid_pagination_cursor",
                message="The pagination cursor is invalid.",
                status_code=422,
            ) from exc

    @staticmethod
    def _not_found() -> ApplicationError:
        # Use the same response for missing, deleted, and other users' records.
        return ApplicationError(
            code="conversation_not_found",
            message="The conversation was not found.",
            status_code=404,
        )
