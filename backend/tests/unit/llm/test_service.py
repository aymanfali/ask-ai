from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from ask_ai.core.errors import ApplicationError
from ask_ai.modules.llm.catalog import ModelCatalog
from ask_ai.modules.llm.protocols import LLMProvider
from ask_ai.modules.llm.registry import ProviderRegistry
from ask_ai.modules.llm.schemas import (
    ChatMessage,
    GenerationEvent,
    GenerationEventType,
    GenerationRequest,
    GenerationResult,
    MessageRole,
)
from ask_ai.modules.llm.service import LLMService


class FakeProvider:
    provider_id = "openai"
    provider_name = "OpenAI fake"
    provider_type = "openai_compatible"

    async def generate(self, model, request):
        return GenerationResult(
            model_id=model.id,
            provider_id=self.provider_id,
            content=request.messages[-1].content,
        )

    async def stream(self, model, request) -> AsyncIterator[GenerationEvent]:
        yield GenerationEvent(type=GenerationEventType.TEXT_DELTA, text="chunk")
        yield GenerationEvent(type=GenerationEventType.COMPLETED, finish_reason="stop")

    async def close(self) -> None:
        return None


@pytest.fixture
def llm_service(openai_provider_config, model_config):
    provider: LLMProvider = FakeProvider()
    catalog = ModelCatalog(providers=[openai_provider_config], models=[model_config])
    return LLMService(catalog=catalog, registry=ProviderRegistry([provider])), model_config


@pytest.mark.asyncio
async def test_service_resolves_model_and_delegates_generation(llm_service) -> None:
    service, model = llm_service
    request = GenerationRequest(
        model_id=model.id,
        messages=[ChatMessage(role=MessageRole.USER, content="prompt")],
    )

    response = await service.generate(request)

    assert response.content == "prompt"
    assert response.provider_id == "openai"


@pytest.mark.asyncio
async def test_service_streams_normalized_events(llm_service) -> None:
    service, model = llm_service
    request = GenerationRequest(
        model_id=model.id,
        messages=[ChatMessage(role=MessageRole.USER, content="prompt")],
    )

    events = [event async for event in service.stream(request)]

    assert events[0].type == GenerationEventType.TEXT_DELTA
    assert events[1].type == GenerationEventType.COMPLETED


@pytest.mark.asyncio
async def test_service_returns_404_for_unknown_model(llm_service) -> None:
    service, _ = llm_service
    request = GenerationRequest(
        model_id="not-configured",
        messages=[ChatMessage(role=MessageRole.USER, content="prompt")],
    )

    with pytest.raises(ApplicationError) as captured:
        await service.generate(request)

    assert captured.value.status_code == 404
    assert captured.value.code == "model_not_found"


@pytest.mark.asyncio
async def test_service_rejects_output_limit_above_model_configuration(llm_service) -> None:
    service, model = llm_service
    request = GenerationRequest(
        model_id=model.id,
        messages=[ChatMessage(role=MessageRole.USER, content="prompt")],
        max_output_tokens=model.max_output_tokens + 1,
    )

    with pytest.raises(ApplicationError) as captured:
        await service.generate(request)

    assert captured.value.status_code == 422
    assert captured.value.code == "max_output_tokens_exceeded"
