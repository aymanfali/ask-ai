from datetime import UTC, datetime
from decimal import Decimal

import pytest

from ask_ai.modules.llm.config import (
    AnthropicProviderConfig,
    LLMModelConfig,
    ModelCapabilitiesConfig,
    OpenAICompatibleProviderConfig,
    PricingVersionConfig,
)


@pytest.fixture
def openai_provider_config() -> OpenAICompatibleProviderConfig:
    return OpenAICompatibleProviderConfig(
        id="openai",
        name="OpenAI Compatible Test",
        type="openai_compatible",
        api_key="test-provider-secret-key",
        base_url="https://api.example.test/v1",
        max_output_tokens_parameter="max_completion_tokens",
    )


@pytest.fixture
def anthropic_provider_config() -> AnthropicProviderConfig:
    return AnthropicProviderConfig(
        id="anthropic",
        name="Anthropic Test",
        type="anthropic",
        api_key="test-anthropic-secret-key",
    )


@pytest.fixture
def model_config() -> LLMModelConfig:
    return LLMModelConfig(
        id="openai:test-model",
        provider_id="openai",
        provider_model_id="provider-model-2026",
        name="Test Model",
        context_window=128_000,
        max_output_tokens=16_000,
        capabilities=ModelCapabilitiesConfig(streaming=True),
        pricing=(
            PricingVersionConfig(
                version="test-v1",
                effective_from=datetime(2026, 1, 1, tzinfo=UTC),
                currency="USD",
                input_per_million_tokens=Decimal("1.25"),
                output_per_million_tokens=Decimal("5.00"),
            ),
        ),
    )
