from __future__ import annotations

from datetime import UTC, datetime

from ask_ai.modules.llm.config import LLMModelConfig, LLMProviderConfig
from ask_ai.modules.llm.schemas import (
    ModelCapabilitiesResponse,
    ModelResponse,
    PricingResponse,
    ProviderResponse,
)


class ModelCatalog:
    """Immutable in-memory catalog built from validated operator configuration."""

    def __init__(
        self,
        *,
        providers: list[LLMProviderConfig],
        models: list[LLMModelConfig],
    ) -> None:
        self._providers = {provider.id: provider for provider in providers}
        self._models = {model.id: model for model in models}

    def get_model(self, model_id: str) -> LLMModelConfig | None:
        model = self._models.get(model_id)
        if model is None or not model.enabled:
            return None
        provider = self._providers.get(model.provider_id)
        if provider is None or not provider.enabled:
            return None
        return model

    def list_models(self, *, provider_id: str | None = None) -> list[ModelResponse]:
        now = datetime.now(UTC)
        responses: list[ModelResponse] = []
        for model in self._models.values():
            if not model.enabled or (provider_id and model.provider_id != provider_id):
                continue
            provider = self._providers.get(model.provider_id)
            if provider is None or not provider.enabled:
                continue
            effective_prices = [price for price in model.pricing if price.effective_from <= now]
            current_price = max(
                effective_prices,
                key=lambda price: price.effective_from,
                default=None,
            )
            responses.append(
                ModelResponse(
                    id=model.id,
                    provider_id=provider.id,
                    provider_name=provider.name,
                    name=model.name,
                    provider_model_id=model.provider_model_id,
                    description=model.description,
                    context_window=model.context_window,
                    max_output_tokens=model.max_output_tokens,
                    capabilities=ModelCapabilitiesResponse(**model.capabilities.model_dump()),
                    current_pricing=(
                        PricingResponse(**current_price.model_dump()) if current_price else None
                    ),
                )
            )
        return sorted(
            responses,
            key=lambda item: (item.provider_name.casefold(), item.name.casefold()),
        )

    def list_providers(self) -> list[ProviderResponse]:
        responses: list[ProviderResponse] = []
        for provider in self._providers.values():
            if not provider.enabled:
                continue
            model_count = sum(
                1
                for model in self._models.values()
                if model.enabled and model.provider_id == provider.id
            )
            responses.append(
                ProviderResponse(
                    id=provider.id,
                    name=provider.name,
                    type=provider.type,
                    enabled=provider.enabled,
                    model_count=model_count,
                )
            )
        return sorted(responses, key=lambda item: item.name.casefold())

    @property
    def model_count(self) -> int:
        return len(self.list_models())

    @property
    def provider_count(self) -> int:
        return len(self.list_providers())
