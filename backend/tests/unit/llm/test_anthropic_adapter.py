from __future__ import annotations

from types import SimpleNamespace

import pytest

from ask_ai.modules.llm.adapters.anthropic import AnthropicAdapter
from ask_ai.modules.llm.errors import ProviderBadRequestError
from ask_ai.modules.llm.schemas import (
    ChatMessage,
    GenerationEventType,
    GenerationRequest,
    MessageRole,
)


class FakeAsyncStream:
    def __init__(self, events):
        self.events = events
        self.closed = False

    def __aiter__(self):
        self._iterator = iter(self.events)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration:
            raise StopAsyncIteration from None

    async def close(self):
        self.closed = True


class FakeMessages:
    def __init__(self, result=None, stream=None):
        self.result = result
        self.stream = stream
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return self.stream
        return self.result


@pytest.mark.asyncio
async def test_generate_maps_system_and_developer_messages(
    anthropic_provider_config, model_config
) -> None:
    model = model_config.model_copy(
        update={"provider_id": "anthropic", "provider_model_id": "claude-test"}
    )
    result = SimpleNamespace(
        id="msg_123",
        stop_reason="end_turn",
        content=[
            SimpleNamespace(type="text", text="Hello"),
            SimpleNamespace(type="tool_use", text=None),
        ],
        usage=SimpleNamespace(input_tokens=11, output_tokens=7, cache_read_input_tokens=3),
    )
    messages = FakeMessages(result=result)
    client = SimpleNamespace(messages=messages)
    adapter = AnthropicAdapter(anthropic_provider_config, client=client)
    request = GenerationRequest(
        model_id=model.id,
        messages=[
            ChatMessage(role=MessageRole.SYSTEM, content="System policy"),
            ChatMessage(role=MessageRole.DEVELOPER, content="Developer instruction"),
            ChatMessage(role=MessageRole.USER, content="First"),
            ChatMessage(role=MessageRole.USER, content="Second"),
        ],
    )

    response = await adapter.generate(model, request)

    assert response.content == "Hello"
    assert response.finish_reason == "end_turn"
    assert response.usage.input_tokens == 11
    assert response.usage.output_tokens == 7
    assert response.usage.cached_input_tokens == 3
    assert messages.calls[0]["system"] == "System policy\n\nDeveloper instruction"
    assert messages.calls[0]["messages"] == [
        {"role": "user", "content": "First\n\nSecond"}
    ]


@pytest.mark.asyncio
async def test_stream_emits_text_usage_and_completion(
    anthropic_provider_config, model_config
) -> None:
    model = model_config.model_copy(
        update={"provider_id": "anthropic", "provider_model_id": "claude-test"}
    )
    stream = FakeAsyncStream(
        [
            SimpleNamespace(
                type="message_start",
                message=SimpleNamespace(
                    id="msg_stream",
                    usage=SimpleNamespace(input_tokens=12, cache_read_input_tokens=4),
                ),
            ),
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="text_delta", text="Hello"),
            ),
            SimpleNamespace(
                type="message_delta",
                delta=SimpleNamespace(stop_reason="end_turn"),
                usage=SimpleNamespace(output_tokens=9),
            ),
            SimpleNamespace(type="message_stop"),
        ]
    )
    messages = FakeMessages(stream=stream)
    adapter = AnthropicAdapter(anthropic_provider_config, client=SimpleNamespace(messages=messages))
    request = GenerationRequest(
        model_id=model.id,
        messages=[ChatMessage(role=MessageRole.USER, content="Hi")],
    )

    events = [event async for event in adapter.stream(model, request)]

    assert [event.text for event in events if event.type == GenerationEventType.TEXT_DELTA] == [
        "Hello"
    ]
    assert events[-2].usage is not None
    assert events[-2].usage.total_tokens == 21
    assert events[-1].type == GenerationEventType.COMPLETED
    assert events[-1].provider_request_id == "msg_stream"
    assert stream.closed is True


@pytest.mark.asyncio
async def test_anthropic_rejects_temperature_and_top_p_together(
    anthropic_provider_config, model_config
) -> None:
    model = model_config.model_copy(update={"provider_id": "anthropic"})
    adapter = AnthropicAdapter(anthropic_provider_config, client=SimpleNamespace(messages=None))
    request = GenerationRequest(
        model_id=model.id,
        messages=[ChatMessage(role=MessageRole.USER, content="Hi")],
        temperature=0.2,
        top_p=0.9,
    )

    with pytest.raises(ProviderBadRequestError):
        await adapter.generate(model, request)


@pytest.mark.asyncio
async def test_stream_without_message_stop_is_not_marked_completed(
    anthropic_provider_config, model_config
) -> None:
    from ask_ai.modules.llm.errors import ProviderResponseError

    model = model_config.model_copy(
        update={"provider_id": "anthropic", "provider_model_id": "claude-test"}
    )
    stream = FakeAsyncStream(
        [
            SimpleNamespace(
                type="message_start",
                message=SimpleNamespace(
                    id="msg_incomplete",
                    usage=SimpleNamespace(input_tokens=12, cache_read_input_tokens=0),
                ),
            ),
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="text_delta", text="partial"),
            ),
        ]
    )
    messages = FakeMessages(stream=stream)
    adapter = AnthropicAdapter(anthropic_provider_config, client=SimpleNamespace(messages=messages))
    request = GenerationRequest(
        model_id=model.id,
        messages=[ChatMessage(role=MessageRole.USER, content="Hi")],
    )

    with pytest.raises(ProviderResponseError):
        _ = [event async for event in adapter.stream(model, request)]

    assert stream.closed is True
