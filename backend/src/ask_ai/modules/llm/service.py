from __future__ import annotations

from collections.abc import AsyncIterator

from ask_ai.core.errors import ApplicationError
from ask_ai.modules.llm.catalog import ModelCatalog
from ask_ai.modules.llm.errors import ProviderError
from ask_ai.modules.llm.registry import ProviderRegistry
from ask_ai.modules.llm.schemas import GenerationEvent, GenerationRequest, GenerationResult


class LLMService:
    """Provider-independent orchestration facade consumed by later chat services."""

    def __init__(self, *, catalog: ModelCatalog, registry: ProviderRegistry) -> None:
        self.catalog = catalog
        self.registry = registry

    def _resolve(self, request: GenerationRequest):
        model = self.catalog.get_model(request.model_id)
        if model is None:
            raise ApplicationError(
                code="model_not_found",
                message="The requested model is not available.",
                status_code=404,
            )
        if (
            request.max_output_tokens is not None
            and request.max_output_tokens > model.max_output_tokens
        ):
            raise ApplicationError(
                code="max_output_tokens_exceeded",
                message="The requested output limit exceeds the selected model's configured limit.",
                status_code=422,
            )
        provider = self.registry.get(model.provider_id)
        return model, provider

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        model, provider = self._resolve(request)
        try:
            return await provider.generate(model, request)
        except ProviderError:
            raise

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationEvent]:
        model, provider = self._resolve(request)
        if not model.capabilities.streaming:
            raise ApplicationError(
                code="model_streaming_unsupported",
                message="The selected model does not support streaming.",
                status_code=422,
            )
        try:
            async for event in provider.stream(model, request):
                yield event
        except ProviderError:
            raise
