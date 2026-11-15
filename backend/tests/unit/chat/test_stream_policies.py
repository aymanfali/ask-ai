from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from ask_ai.core.config import Settings
from ask_ai.modules.chat.service import ExplicitGenerationCancellation, GenerationService
from ask_ai.modules.llm.errors import ProviderRateLimitError
from ask_ai.modules.llm.schemas import GenerationEvent, GenerationEventType


class FakeRedis:
    def __init__(self, value: str | None = None) -> None:
        self.value = value

    async def get(self, _key: str) -> str | None:
        return self.value


class FakeIterator:
    def __init__(self, events: list[GenerationEvent]) -> None:
        self.events = iter(events)

    def __aiter__(self) -> FakeIterator:
        return self

    async def __anext__(self) -> GenerationEvent:
        try:
            return next(self.events)
        except StopIteration:
            raise StopAsyncIteration from None


@pytest.fixture
def service() -> GenerationService:
    return GenerationService(
        session=None,  # type: ignore[arg-type]
        session_factory=None,  # type: ignore[arg-type]
        llm_service=None,  # type: ignore[arg-type]
        catalog=None,  # type: ignore[arg-type]
        redis=FakeRedis(),
        settings=Settings(
            app_env="test",
            secret_key="test-generation-policy-secret-that-is-long-enough",
            generation_retry_base_seconds=0.5,
        ),
    )


@pytest.mark.asyncio
async def test_cancel_signal_is_checked_while_provider_is_waiting(service) -> None:
    service.redis = FakeRedis("1")

    async def stalled() -> AsyncIterator[GenerationEvent]:
        await asyncio.sleep(10)
        yield GenerationEvent(type=GenerationEventType.TEXT_DELTA, text="late")

    with pytest.raises(ExplicitGenerationCancellation):
        async for _ in service._next_or_cancel(stalled().__aiter__(), uuid4()):
            pass


@pytest.mark.asyncio
async def test_next_or_cancel_emits_heartbeat_without_losing_pending_next(
    monkeypatch, service
) -> None:
    from ask_ai.modules.chat import service as service_module

    monkeypatch.setattr(service_module, "SSE_HEARTBEAT_INTERVAL_SECONDS", 0.1)

    async def delayed() -> AsyncIterator[GenerationEvent]:
        await asyncio.sleep(0.35)
        yield GenerationEvent(type=GenerationEventType.TEXT_DELTA, text="hello")

    events = [event async for event in service._next_or_cancel(delayed().__aiter__(), uuid4())]
    assert events[-1].text == "hello"
    assert service_module._HEARTBEAT in events


def test_provider_retry_delay_respects_bounded_retry_after(service) -> None:
    error = ProviderRateLimitError("openai", retry_after_seconds=900)
    assert service._retry_delay(error, 0) == 10.0

    no_header = ProviderRateLimitError("openai")
    assert service._retry_delay(no_header, 1) == 1.0


@pytest.mark.asyncio
async def test_preexisting_cancel_marker_does_not_start_provider_iteration(service) -> None:
    service.redis = FakeRedis("1")
    provider_started = False

    async def upstream() -> AsyncIterator[GenerationEvent]:
        nonlocal provider_started
        provider_started = True
        yield GenerationEvent(type=GenerationEventType.TEXT_DELTA, text="should not run")

    with pytest.raises(ExplicitGenerationCancellation):
        async for _ in service._next_or_cancel(upstream().__aiter__(), uuid4()):
            pass

    assert provider_started is False
