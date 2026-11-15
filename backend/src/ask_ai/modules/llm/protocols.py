from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from ask_ai.modules.llm.config import LLMModelConfig
from ask_ai.modules.llm.schemas import GenerationEvent, GenerationRequest, GenerationResult


class LLMProvider(Protocol):
    provider_id: str
    provider_name: str
    provider_type: str

    async def generate(
        self,
        model: LLMModelConfig,
        request: GenerationRequest,
    ) -> GenerationResult: ...

    def stream(
        self,
        model: LLMModelConfig,
        request: GenerationRequest,
    ) -> AsyncIterator[GenerationEvent]: ...

    async def close(self) -> None: ...
