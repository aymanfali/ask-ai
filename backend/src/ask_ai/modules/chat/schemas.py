from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ask_ai.modules.conversations.constants import MAX_MESSAGE_CONTENT_LENGTH


class GenerationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CONTENT_LENGTH)
    model_id: str = Field(min_length=1, max_length=128)
    max_output_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    stop_sequences: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        value = value.strip()
        if not value or "\x00" in value:
            raise ValueError("Message content must be non-empty text")
        return value

    @field_validator("model_id")
    @classmethod
    def normalize_model_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Model id cannot be blank")
        return value

    @field_validator("stop_sequences")
    @classmethod
    def normalize_stop_sequences(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            item = value.strip()
            if not item or len(item) > 200:
                raise ValueError("Stop sequences must contain 1 to 200 characters")
            if item not in result:
                result.append(item)
        return result


class GenerationUsageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cached_input_tokens: int | None
    usage_source: Literal["provider_reported", "estimated", "unavailable"]
    estimated_cost: Decimal | None
    currency: str | None
    pricing_version: str | None


class GenerationStatusResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    provider_id: str
    model_id: str
    status: Literal[
        "pending", "streaming", "completed", "failed", "cancelled", "interrupted"
    ]
    error_code: str | None
    finish_reason: str | None
    provider_request_id: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    usage: GenerationUsageResponse | None = None


class GenerationCancelResponse(BaseModel):
    generation_id: UUID
    status: Literal["pending", "streaming", "completed", "failed", "cancelled", "interrupted"]
    cancellation_requested: bool
