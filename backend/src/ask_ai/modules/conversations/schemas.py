from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ask_ai.modules.conversations.constants import (
    MAX_CONVERSATION_TITLE_LENGTH,
    MAX_MESSAGE_CONTENT_LENGTH,
)


class ConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=MAX_CONVERSATION_TITLE_LENGTH)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized or "\x00" in normalized:
            raise ValueError("Title cannot be empty or contain a null character")
        return normalized


class ConversationUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=MAX_CONVERSATION_TITLE_LENGTH)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or "\x00" in normalized:
            raise ValueError("Title cannot be empty or contain a null character")
        return normalized


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    last_message_sequence: int
    created_at: datetime
    updated_at: datetime


class ConversationPageResponse(BaseModel):
    items: list[ConversationResponse]
    next_cursor: str | None


class MessageCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CONTENT_LENGTH)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or "\x00" in normalized:
            raise ValueError("Message content cannot be empty or contain a null character")
        return normalized


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    role: Literal["user", "assistant"]
    content: str
    status: Literal[
        "complete", "pending", "streaming", "failed", "cancelled", "interrupted"
    ]
    sequence: int
    created_at: datetime


class MessagePageResponse(BaseModel):
    items: list[MessageResponse]
    next_before_sequence: int | None
