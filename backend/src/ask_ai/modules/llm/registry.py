from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ask_ai.modules.llm.adapters.anthropic import AnthropicAdapter
from ask_ai.modules.llm.adapters.openai_compatible import OpenAICompatibleAdapter
from ask_ai.modules.llm.errors import ProviderUnavailableError
from ask_ai.modules.llm.protocols import LLMProvider

if TYPE_CHECKING:
    from ask_ai.core.config import Settings


class ProviderRegistry:
    """Own provider adapters and their async SDK clients for one app lifespan."""

    def __init__(self, providers: list[LLMProvider] | None = None) -> None:
        self._providers: dict[str, LLMProvider] = {}
        for provider in providers or []:
            self.register(provider)

    def register(self, provider: LLMProvider) -> None:
        if provider.provider_id in self._providers:
            raise ValueError(f"Duplicate LLM provider id: {provider.provider_id}")
        self._providers[provider.provider_id] = provider

    def get(self, provider_id: str) -> LLMProvider:
        provider = self._providers.get(provider_id)
        if provider is None:
            raise ProviderUnavailableError(provider_id)
        return provider

    def list_provider_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))

    async def close(self) -> None:
        results = await asyncio.gather(
            *(provider.close() for provider in self._providers.values()),
            return_exceptions=True,
        )
        failures = sum(isinstance(result, BaseException) for result in results)
        if failures:
            # Avoid logging exception messages; SDK exceptions can include sensitive data.
            import structlog

            structlog.get_logger(__name__).error(
                "llm_provider_shutdown_failed",
                failed_provider_count=failures,
            )


async def create_provider_registry(settings: Settings) -> ProviderRegistry:
    providers: list[LLMProvider] = []
    try:
        for config in settings.llm_providers:
            if not config.enabled:
                continue
            if config.type == "openai_compatible":
                providers.append(OpenAICompatibleAdapter(config))
            elif config.type == "anthropic":
                providers.append(AnthropicAdapter(config))
            else:  # pragma: no cover - the discriminated settings union prevents this
                raise ValueError("Unsupported provider adapter type")
        return ProviderRegistry(providers)
    except Exception:
        await asyncio.gather(*(provider.close() for provider in providers), return_exceptions=True)
        raise
