from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from ask_ai.core.config import Settings
from ask_ai.modules.chat.schemas import GenerationCreateRequest
from ask_ai.modules.chat.service import GenerationService, PreparedGeneration
from ask_ai.modules.llm.catalog import ModelCatalog
from ask_ai.modules.llm.config import (
    LLMModelConfig,
    OpenAICompatibleProviderConfig,
    PricingVersionConfig,
)
from ask_ai.modules.llm.schemas import ChatMessage, GenerationRequest, MessageRole, TokenUsage


def _model() -> LLMModelConfig:
    return LLMModelConfig(
        id="openai:test-model",
        provider_id="openai",
        provider_model_id="provider-model",
        name="Test model",
        context_window=16_000,
        max_output_tokens=2_000,
        pricing=(
            PricingVersionConfig(
                version="test-v1",
                effective_from=datetime(2026, 1, 1, tzinfo=UTC),
                currency="USD",
                input_per_million_tokens=Decimal("1.25"),
                output_per_million_tokens=Decimal("5.00"),
                cached_input_per_million_tokens=Decimal("0.50"),
            ),
        ),
    )


def _service() -> GenerationService:
    provider = OpenAICompatibleProviderConfig(
        id="openai",
        name="OpenAI-compatible",
        type="openai_compatible",
        api_key="test-secret-key-value",
        base_url="https://api.example.test/v1",
    )
    catalog = ModelCatalog(providers=[provider], models=[_model()])
    return GenerationService(
        session=None,  # type: ignore[arg-type]
        session_factory=None,  # type: ignore[arg-type]
        llm_service=None,  # type: ignore[arg-type]
        catalog=catalog,
        redis=None,
        settings=Settings(
            app_env="test",
            secret_key="test-generation-secret-that-is-at-least-32-bytes",
        ),
    )


def test_generation_payload_normalizes_content_and_rejects_extra_fields() -> None:
    payload = GenerationCreateRequest(
        content="  hello  ",
        model_id=" openai:test-model ",
    )
    assert payload.content == "hello"
    assert payload.model_id == "openai:test-model"

    with pytest.raises(ValueError):
        GenerationCreateRequest(content="hi", model_id="model", unexpected=True)


def test_generation_request_hash_is_stable_and_parameter_sensitive() -> None:
    service = _service()
    first = GenerationCreateRequest(content="question", model_id="openai:test-model")
    same = GenerationCreateRequest(content="question", model_id="openai:test-model")
    different = GenerationCreateRequest(
        content="question", model_id="openai:test-model", temperature=0.2
    )
    different_output = GenerationCreateRequest(
        content="question", model_id="openai:test-model", max_output_tokens=1200
    )
    conversation_id = uuid4()

    first_hash = service._request_hash(conversation_id, first)
    assert first_hash == service._request_hash(conversation_id, same)
    assert first_hash != service._request_hash(conversation_id, different)
    assert first_hash != service._request_hash(conversation_id, different_output)


def test_usage_uses_provider_reported_tokens_and_decimal_cost() -> None:
    service = _service()
    model = _model()
    prepared = PreparedGeneration(
        generation_id=uuid4(),
        conversation_id=uuid4(),
        user_message_id=uuid4(),
        assistant_message_id=uuid4(),
        assistant_sequence=2,
        request=GenerationRequest(
            model_id=model.id,
            messages=[ChatMessage(role=MessageRole.USER, content="prompt")],
        ),
        model=model,
        estimated_input_tokens=900,
    )

    usage, source, cost, currency, version = service._resolve_usage(
        prepared,
        TokenUsage(input_tokens=1000, output_tokens=500, total_tokens=1500),
        "hello",
    )

    assert source == "provider_reported"
    assert usage.input_tokens == 1000
    assert usage.output_tokens == 500
    assert cost == Decimal("0.0037500000")
    assert currency == "USD"
    assert version == "test-v1"


def test_usage_marks_fallback_estimates_and_applies_cached_pricing() -> None:
    service = _service()
    model = _model()
    prepared = PreparedGeneration(
        generation_id=uuid4(),
        conversation_id=uuid4(),
        user_message_id=uuid4(),
        assistant_message_id=uuid4(),
        assistant_sequence=2,
        request=None,
        model=model,
        estimated_input_tokens=1000,
    )

    usage, source, cost, currency, version = service._resolve_usage(
        prepared,
        TokenUsage(input_tokens=1000, cached_input_tokens=400),
        "hello world",
    )

    assert source == "estimated"
    assert usage.input_tokens == 1000
    assert usage.output_tokens is not None and usage.output_tokens > 0
    assert cost is not None and cost > 0
    assert currency == "USD"
    assert version == "test-v1"


@pytest.mark.asyncio
async def test_idempotency_key_rejects_non_ascii_characters_before_database_access() -> None:
    from ask_ai.core.errors import ApplicationError

    service = _service()
    payload = GenerationCreateRequest(content="question", model_id="openai:test-model")
    with pytest.raises(ApplicationError) as captured:
        await service.prepare_generation(
            user_id=uuid4(),
            conversation_id=uuid4(),
            payload=payload,
            idempotency_key="request-ö-0001",
        )

    assert captured.value.code == "invalid_idempotency_key"
