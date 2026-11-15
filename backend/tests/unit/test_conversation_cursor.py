from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ask_ai.core.errors import ApplicationError
from ask_ai.modules.conversations.service import ConversationService


def test_conversation_cursor_round_trip() -> None:
    conversation = SimpleNamespace(
        updated_at=datetime(2026, 11, 14, 12, 30, 45, 123456, tzinfo=UTC),
        id=uuid4(),
    )
    cursor = ConversationService._encode_conversation_cursor(conversation)
    updated_at, conversation_id = ConversationService._decode_conversation_cursor(cursor)
    assert updated_at == conversation.updated_at
    assert conversation_id == conversation.id


@pytest.mark.parametrize("cursor", ["invalid", "", "%%%%", "bm90LWEtdGltZXN0YW1w"])
def test_invalid_conversation_cursors_raise_safe_error(cursor: str) -> None:
    with pytest.raises(ApplicationError) as error:
        ConversationService._decode_conversation_cursor(cursor)
    assert error.value.code == "invalid_pagination_cursor"
    assert error.value.status_code == 422
