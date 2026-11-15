from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

_PROVIDER_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,47}$")
_MODEL_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$")


class ProviderConfigBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=2, max_length=48)
    name: str = Field(min_length=1, max_length=80)
    api_key: SecretStr
    enabled: bool = True
    timeout_seconds: float = Field(default=60.0, gt=0, le=300)

    @field_validator("id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _PROVIDER_ID_RE.fullmatch(normalized):
            raise ValueError("Provider id must be a lowercase slug")
        return normalized

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Provider name cannot be blank")
        return normalized

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("Provider API key cannot be blank")
        return value


class OpenAICompatibleProviderConfig(ProviderConfigBase):
    type: Literal["openai_compatible"]
    base_url: str = Field(min_length=8, max_length=500)
    max_output_tokens_parameter: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    include_usage_in_stream: bool = True

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "Provider base_url must be an absolute HTTP(S) URL without credentials"
            )
        return normalized


class AnthropicProviderConfig(ProviderConfigBase):
    type: Literal["anthropic"]
    base_url: str | None = None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "Provider base_url must be an absolute HTTP(S) URL without credentials"
            )
        return normalized


LLMProviderConfig = Annotated[
    OpenAICompatibleProviderConfig | AnthropicProviderConfig,
    Field(discriminator="type"),
]


class PricingVersionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1, max_length=40)
    effective_from: datetime
    currency: str = Field(default="USD", min_length=3, max_length=3)
    input_per_million_tokens: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=10
    )
    output_per_million_tokens: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=10
    )
    cached_input_per_million_tokens: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=10
    )

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        normalized = value.upper()
        if not re.fullmatch(r"[A-Z]{3}", normalized):
            raise ValueError("Currency must be a three-letter ISO-style code")
        return normalized

    @field_validator("effective_from")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Pricing effective_from must be timezone-aware")
        return value.astimezone(UTC)


class ModelCapabilitiesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    streaming: bool = True
    tools: bool = False
    structured_output: bool = False
    vision: bool = False
    reasoning: bool = False


class LLMModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=128)
    provider_id: str = Field(min_length=2, max_length=48)
    provider_model_id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    context_window: int = Field(gt=0, le=2_000_000)
    max_output_tokens: int = Field(gt=0, le=1_000_000)
    capabilities: ModelCapabilitiesConfig = Field(default_factory=ModelCapabilitiesConfig)
    pricing: tuple[PricingVersionConfig, ...] = ()
    enabled: bool = True

    @field_validator("id")
    @classmethod
    def validate_model_id(cls, value: str) -> str:
        normalized = value.strip()
        if not _MODEL_ID_RE.fullmatch(normalized):
            raise ValueError("Model id contains unsupported characters")
        return normalized

    @field_validator("provider_id")
    @classmethod
    def normalize_provider_id(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("provider_model_id", "name")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank")
        return normalized

    @model_validator(mode="after")
    def validate_model_definition(self) -> LLMModelConfig:
        if self.max_output_tokens > self.context_window:
            raise ValueError("max_output_tokens cannot exceed context_window")
        if self.capabilities.streaming is False:
            # Streaming is part of the intended MVP. Non-streaming-only models remain
            # catalogable, but the generation service can reject streaming requests.
            pass
        versions = [item.version for item in self.pricing]
        if len(versions) != len(set(versions)):
            raise ValueError("Pricing version identifiers must be unique per model")
        effective_dates = [item.effective_from for item in self.pricing]
        if len(effective_dates) != len(set(effective_dates)):
            raise ValueError("Pricing effective_from timestamps must be unique per model")
        return self


class ProviderSummaryConfig(BaseModel):
    """Non-secret provider metadata used by catalog/API responses."""

    id: str
    name: str
    type: Literal["openai_compatible", "anthropic"]
    enabled: bool
