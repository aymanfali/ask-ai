import pytest
from pydantic import ValidationError

from ask_ai.modules.conversations.schemas import (
    ConversationCreateRequest,
    ConversationUpdateRequest,
    MessageCreateRequest,
)


def test_conversation_title_is_trimmed() -> None:
    assert ConversationCreateRequest(title="  Project discussion  ").title == "Project discussion"
    assert ConversationUpdateRequest(title="  Rename me  ").title == "Rename me"


@pytest.mark.parametrize("payload", [{"title": "   "}, {"title": "x" * 201}])
def test_invalid_conversation_title_is_rejected(payload: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        ConversationCreateRequest(**payload)


@pytest.mark.parametrize("content", ["", "   ", "x" * 32_001])
def test_invalid_message_content_is_rejected(content: str) -> None:
    with pytest.raises(ValidationError):
        MessageCreateRequest(content=content)


def test_message_content_is_trimmed() -> None:
    payload = MessageCreateRequest(content="  hello world  ")
    assert payload.content == "hello world"
