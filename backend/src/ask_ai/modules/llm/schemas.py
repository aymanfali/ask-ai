from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ask_ai.modules.llm.config import ModelCapabilitiesConfig, PricingVersionConfig


class MessageRole(StrEnum):
    SYSTEM = "system"
    DEVELOPER = "developer"
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: MessageRole
    content: str = Field(min_length=1, max_length=256_000)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or "\x00" in normalized:
            raise ValueError("Message content must be non-empty text")
        return normalized


class GenerationRequest(BaseModel):
    """Normalized text-generation input accepted by all provider adapters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str = Field(min_length=1, max_length=128)
    messages: Annotated[list[ChatMessage], Field(min_length=1, max_length=256)]
    max_output_tokens: int | None = Field(default=None, gt=0, le=1_000_000)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    stop_sequences: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("model_id")
    @classmethod
    def validate_model_id(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_total_input_size(self) -> GenerationRequest:
        total_characters = sum(len(message.content) for message in self.messages)
        if total_characters > 1_000_000:
            raise ValueError("Combined message content cannot exceed 1,000,000 characters")
        return self

    @field_validator("stop_sequences")
    @classmethod
    def validate_stop_sequences(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            item = value.strip()
            if not item or len(item) > 200:
                raise ValueError("Stop sequences must contain 1 to 200 characters")
            if item not in normalized:
                normalized.append(item)
        return normalized


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_total(self) -> TokenUsage:
        if (
            self.total_tokens is not None
            and self.input_tokens is not None
            and self.output_tokens is not None
            and self.total_tokens != self.input_tokens + self.output_tokens
        ):
            raise ValueError("total_tokens must equal input_tokens + output_tokens")
        return self


class GenerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str
    provider_id: str
    content: str
    finish_reason: str | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    provider_request_id: str | None = None


class GenerationEventType(StrEnum):
    TEXT_DELTA = "text_delta"
    USAGE = "usage"
    COMPLETED = "completed"


class GenerationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: GenerationEventType
    text: str | None = None
    usage: TokenUsage | None = None
    finish_reason: str | None = None
    provider_request_id: str | None = None


class ModelCapabilitiesResponse(ModelCapabilitiesConfig):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PricingResponse(PricingVersionConfig):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    provider_id: str
    provider_name: str
    name: str
    provider_model_id: str
    description: str | None = None
    context_window: int
    max_output_tokens: int
    capabilities: ModelCapabilitiesResponse
    current_pricing: PricingResponse | None = None


class ProviderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    type: str
    enabled: bool
    model_count: int
