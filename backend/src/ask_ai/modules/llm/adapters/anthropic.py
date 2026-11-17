from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from ask_ai.modules.llm.config import AnthropicProviderConfig, LLMModelConfig
from ask_ai.modules.llm.errors import (
    ProviderAuthenticationError,
    ProviderBadRequestError,
    ProviderError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderUnavailableError,
    normalize_provider_exception,
)
from ask_ai.modules.llm.schemas import (
    GenerationEvent,
    GenerationEventType,
    GenerationRequest,
    GenerationResult,
    MessageRole,
    TokenUsage,
)


class AnthropicAdapter:
    """Native Anthropic Messages API adapter."""

    provider_type = "anthropic"

    def __init__(
        self, config: AnthropicProviderConfig, *, client: Any | None = None
    ) -> None:
        self.provider_id = config.id
        self.provider_name = config.name
        self.config = config
        self._owns_client = client is None
        if client is None:
            try:
                from anthropic import AsyncAnthropic
            except (
                ImportError
            ) as exc:  # pragma: no cover - environment-specific install error
                raise RuntimeError(
                    "Install the 'anthropic' package to enable this provider"
                ) from exc
            client_kwargs: dict[str, Any] = {
                "api_key": config.api_key.get_secret_value(),
                "timeout": config.timeout_seconds,
                "max_retries": 0,
            }
            if config.base_url:
                client_kwargs["base_url"] = config.base_url
            client = AsyncAnthropic(**client_kwargs)
        self._client = client

    def _build_payload(
        self, model: LLMModelConfig, request: GenerationRequest
    ) -> dict[str, Any]:
        if request.temperature is not None and request.top_p is not None:
            raise ProviderBadRequestError(self.provider_id, 400)
        if request.temperature is not None and request.temperature > 1:
            raise ProviderBadRequestError(self.provider_id, 400)

        system_parts: list[str] = []
        messages: list[dict[str, str]] = []
        conversation_started = False
        for item in request.messages:
            if item.role in {MessageRole.SYSTEM, MessageRole.DEVELOPER}:
                if conversation_started:
                    raise ProviderBadRequestError(self.provider_id, 400)
                system_parts.append(item.content)
                continue
            conversation_started = True
            role = item.role.value
            if role not in {"user", "assistant"}:
                raise ProviderBadRequestError(self.provider_id, 400)
            if messages and messages[-1]["role"] == role:
                messages[-1]["content"] += "\n\n" + item.content
            else:
                messages.append({"role": role, "content": item.content})

        if not messages:
            raise ProviderBadRequestError(self.provider_id, 400)

        payload: dict[str, Any] = {
            "model": model.provider_model_id,
            "max_tokens": min(
                request.max_output_tokens or model.max_output_tokens,
                model.max_output_tokens,
            ),
            "messages": messages,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.stop_sequences:
            payload["stop_sequences"] = request.stop_sequences
        return payload

    @staticmethod
    def _usage(raw_usage: Any | None) -> TokenUsage:
        if raw_usage is None:
            return TokenUsage()
        input_tokens = _as_nonnegative_int(getattr(raw_usage, "input_tokens", None))
        output_tokens = _as_nonnegative_int(getattr(raw_usage, "output_tokens", None))
        cached_tokens = _as_nonnegative_int(
            getattr(raw_usage, "cache_read_input_tokens", None)
        )
        total_tokens = (
            input_tokens + output_tokens
            if input_tokens is not None and output_tokens is not None
            else None
        )
        return TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_input_tokens=cached_tokens,
        )

    def validate_request(
        self, model: LLMModelConfig, request: GenerationRequest
    ) -> None:
        """Validate Anthropic-specific request constraints without network I/O."""
        self._build_payload(model, request)

    async def generate(
        self,
        model: LLMModelConfig,
        request: GenerationRequest,
    ) -> GenerationResult:
        payload = self._build_payload(model, request)
        try:
            response = await self._client.messages.create(**payload)
            text_parts = [
                block.text
                for block in (getattr(response, "content", None) or [])
                if getattr(block, "type", None) == "text"
                and isinstance(getattr(block, "text", None), str)
            ]
            if not text_parts:
                raise ValueError("Provider returned no text content")
            return GenerationResult(
                model_id=model.id,
                provider_id=self.provider_id,
                content="".join(text_parts),
                finish_reason=_optional_string(getattr(response, "stop_reason", None)),
                usage=self._usage(getattr(response, "usage", None)),
                provider_request_id=_optional_string(getattr(response, "id", None)),
            )
        except ProviderError:
            raise
        except Exception as exc:
            raise normalize_provider_exception(self.provider_id, exc) from exc

    async def stream(
        self,
        model: LLMModelConfig,
        request: GenerationRequest,
    ) -> AsyncIterator[GenerationEvent]:
        if not model.capabilities.streaming:
            raise ProviderBadRequestError(self.provider_id, 400)

        stream: Any | None = None
        input_tokens: int | None = None
        output_tokens: int | None = None
        cached_tokens: int | None = None
        finish_reason: str | None = None
        request_id: str | None = None
        message_stopped = False
        try:
            stream = await self._client.messages.create(
                **self._build_payload(model, request),
                stream=True,
            )
            async for event in stream:
                event_type = getattr(event, "type", None)
                if event_type == "message_start":
                    message = getattr(event, "message", None)
                    request_id = (
                        _optional_string(getattr(message, "id", None)) or request_id
                    )
                    usage = getattr(message, "usage", None)
                    input_tokens = _as_nonnegative_int(
                        getattr(usage, "input_tokens", None)
                    )
                    cached_tokens = _as_nonnegative_int(
                        getattr(usage, "cache_read_input_tokens", None)
                    )
                elif event_type == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    if getattr(delta, "type", None) == "text_delta":
                        text = getattr(delta, "text", None)
                        if isinstance(text, str) and text:
                            yield GenerationEvent(
                                type=GenerationEventType.TEXT_DELTA, text=text
                            )
                elif event_type == "message_delta":
                    delta = getattr(event, "delta", None)
                    usage = getattr(event, "usage", None)
                    finish_reason = (
                        _optional_string(getattr(delta, "stop_reason", None))
                        or finish_reason
                    )
                    output_tokens = _as_nonnegative_int(
                        getattr(usage, "output_tokens", None)
                    )
                elif event_type == "message_stop":
                    message_stopped = True
                elif event_type == "error":
                    error_data = getattr(event, "error", None)
                    error_type = str(getattr(error_data, "type", "")).casefold()
                    if "rate_limit" in error_type:
                        raise ProviderRateLimitError(self.provider_id)
                    if "auth" in error_type:
                        raise ProviderAuthenticationError(self.provider_id)
                    if "invalid_request" in error_type:
                        raise ProviderBadRequestError(self.provider_id, 400)
                    raise ProviderUnavailableError(self.provider_id, 529)
            if not message_stopped:
                raise ProviderResponseError(self.provider_id)
            usage_result = self._usage(
                _UsageSnapshot(input_tokens, output_tokens, cached_tokens)
            )
            if input_tokens is not None or output_tokens is not None:
                yield GenerationEvent(
                    type=GenerationEventType.USAGE, usage=usage_result
                )
            yield GenerationEvent(
                type=GenerationEventType.COMPLETED,
                usage=usage_result,
                finish_reason=finish_reason,
                provider_request_id=request_id,
            )
        except ProviderError:
            raise
        except Exception as exc:
            raise normalize_provider_exception(self.provider_id, exc) from exc
        finally:
            if stream is not None:
                close = getattr(stream, "close", None)
                if callable(close):
                    try:
                        await close()
                    except Exception:
                        pass

    async def close(self) -> None:
        if self._owns_client:
            close = getattr(self._client, "close", None)
            if callable(close):
                await close()


class _UsageSnapshot:
    def __init__(
        self,
        input_tokens: int | None,
        output_tokens: int | None,
        cache_read_input_tokens: int | None,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = cache_read_input_tokens


def _as_nonnegative_int(value: Any) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else None
    )


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
