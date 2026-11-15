from __future__ import annotations

from types import SimpleNamespace

import pytest

from ask_ai.modules.llm.adapters.openai_compatible import OpenAICompatibleAdapter
from ask_ai.modules.llm.errors import ProviderRateLimitError
from ask_ai.modules.llm.schemas import (
    ChatMessage,
    GenerationEventType,
    GenerationRequest,
    MessageRole,
)


class FakeAsyncStream:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    def __aiter__(self):
        self._iterator = iter(self.chunks)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration:
            raise StopAsyncIteration from None

    async def close(self):
        self.closed = True


class FakeCompletions:
    def __init__(self, result=None, stream=None, error=None):
        self.result = result
        self.stream = stream
        self.error = error
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        if kwargs.get("stream"):
            return self.stream
        return self.result


@pytest.mark.asyncio
async def test_generate_normalizes_chat_completion(
    openai_provider_config, model_config
) -> None:
    completion = SimpleNamespace(
        id="req_123",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="Hello from the model"),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=12,
            completion_tokens=5,
            total_tokens=17,
            prompt_tokens_details=SimpleNamespace(cached_tokens=2),
        ),
    )
    completions = FakeCompletions(result=completion)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    adapter = OpenAICompatibleAdapter(openai_provider_config, client=client)
    request = GenerationRequest(
        model_id=model_config.id,
        messages=[ChatMessage(role=MessageRole.USER, content="Hi")],
        max_output_tokens=100,
        temperature=0.3,
    )

    result = await adapter.generate(model_config, request)

    assert result.content == "Hello from the model"
    assert result.provider_id == "openai"
    assert result.provider_request_id == "req_123"
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 5
    assert result.usage.total_tokens == 17
    assert completions.calls[0]["max_completion_tokens"] == 100
    assert completions.calls[0]["temperature"] == 0.3
    assert completions.calls[0]["stream"] is False


@pytest.mark.asyncio
async def test_stream_emits_deltas_usage_and_completion(
    openai_provider_config, model_config
) -> None:
    stream = FakeAsyncStream(
        [
            SimpleNamespace(
                id="req_stream",
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="Hello"),
                        finish_reason=None,
                    )
                ],
                usage=None,
            ),
            SimpleNamespace(
                id="req_stream",
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content=" world"),
                        finish_reason="stop",
                    )
                ],
                usage=None,
            ),
            SimpleNamespace(
                id="req_stream",
                choices=[],
                usage=SimpleNamespace(
                    prompt_tokens=10,
                    completion_tokens=2,
                    total_tokens=12,
                    prompt_tokens_details=None,
                ),
            ),
        ]
    )
    completions = FakeCompletions(stream=stream)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    adapter = OpenAICompatibleAdapter(openai_provider_config, client=client)
    request = GenerationRequest(
        model_id=model_config.id,
        messages=[ChatMessage(role=MessageRole.USER, content="Hi")],
    )

    events = [event async for event in adapter.stream(model_config, request)]

    assert [event.text for event in events if event.type == GenerationEventType.TEXT_DELTA] == [
        "Hello",
        " world",
    ]
    assert events[-2].type == GenerationEventType.USAGE
    assert events[-1].type == GenerationEventType.COMPLETED
    assert events[-1].finish_reason == "stop"
    assert stream.closed is True
    assert completions.calls[0]["stream_options"] == {"include_usage": True}


@pytest.mark.asyncio
async def test_rate_limit_is_normalized_without_raw_provider_message(
    openai_provider_config, model_config
) -> None:
    class RateLimitError(Exception):
        status_code = 429
        response = SimpleNamespace(headers={"retry-after": "2"})

    completions = FakeCompletions(error=RateLimitError("secret provider response details"))
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    adapter = OpenAICompatibleAdapter(openai_provider_config, client=client)
    request = GenerationRequest(
        model_id=model_config.id,
        messages=[ChatMessage(role=MessageRole.USER, content="Hi")],
    )

    with pytest.raises(ProviderRateLimitError) as captured:
        await adapter.generate(model_config, request)

    assert captured.value.retry_after_seconds == 2
    assert "secret provider response details" not in str(captured.value)


@pytest.mark.asyncio
async def test_close_does_not_close_injected_client(openai_provider_config):
    class Client:
        closed = False

        async def close(self):
            self.closed = True

    client = Client()
    adapter = OpenAICompatibleAdapter(openai_provider_config, client=client)
    await adapter.close()
    assert client.closed is False


@pytest.mark.asyncio
async def test_stream_without_finish_reason_is_not_marked_completed(
    openai_provider_config, model_config
) -> None:
    from ask_ai.modules.llm.errors import ProviderResponseError

    stream = FakeAsyncStream(
        [
            SimpleNamespace(
                id="req_incomplete",
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="partial"),
                        finish_reason=None,
                    )
                ],
                usage=None,
            )
        ]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions(stream=stream))
    )
    adapter = OpenAICompatibleAdapter(openai_provider_config, client=client)
    request = GenerationRequest(
        model_id=model_config.id,
        messages=[ChatMessage(role=MessageRole.USER, content="Hi")],
    )

    with pytest.raises(ProviderResponseError):
        _ = [event async for event in adapter.stream(model_config, request)]

    assert stream.closed is True
