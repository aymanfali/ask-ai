from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from ask_ai.modules.llm.config import LLMModelConfig, OpenAICompatibleProviderConfig
from ask_ai.modules.llm.errors import (
    ProviderBadRequestError,
    ProviderError,
    ProviderResponseError,
    normalize_provider_exception,
)
from ask_ai.modules.llm.schemas import (
    GenerationEvent,
    GenerationEventType,
    GenerationRequest,
    GenerationResult,
    TokenUsage,
)


class OpenAICompatibleAdapter:
    """Adapter for OpenAI Chat Completions-compatible HTTP APIs.

    SDK retries are disabled. Retry policy belongs to the orchestration layer so
    it can account for idempotency and whether output has already reached a user.
    """

    provider_type = "openai_compatible"

    def __init__(
        self,
        config: OpenAICompatibleProviderConfig,
        *,
        client: Any | None = None,
    ) -> None:
        self.provider_id = config.id
        self.provider_name = config.name
        self.config = config
        self._owns_client = client is None
        if client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:  # pragma: no cover - environment-specific install error
                raise RuntimeError("Install the 'openai' package to enable this provider") from exc
            client = AsyncOpenAI(
                api_key=config.api_key.get_secret_value(),
                base_url=config.base_url,
                timeout=config.timeout_seconds,
                max_retries=0,
            )
        self._client = client

    def _build_payload(self, model: LLMModelConfig, request: GenerationRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model.provider_model_id,
            "messages": [
                {"role": message.role.value, "content": message.content}
                for message in request.messages
            ],
        }
        if request.max_output_tokens is not None:
            payload[self.config.max_output_tokens_parameter] = min(
                request.max_output_tokens, model.max_output_tokens
            )
        else:
            payload[self.config.max_output_tokens_parameter] = model.max_output_tokens
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.stop_sequences:
            payload["stop"] = request.stop_sequences
        return payload

    @staticmethod
    def _usage(raw_usage: Any | None) -> TokenUsage:
        if raw_usage is None:
            return TokenUsage()
        input_tokens = _as_nonnegative_int(getattr(raw_usage, "prompt_tokens", None))
        output_tokens = _as_nonnegative_int(getattr(raw_usage, "completion_tokens", None))
        total_tokens = _as_nonnegative_int(getattr(raw_usage, "total_tokens", None))
        if total_tokens is None and input_tokens is not None and output_tokens is not None:
            total_tokens = input_tokens + output_tokens
        prompt_details = getattr(raw_usage, "prompt_tokens_details", None)
        cached_tokens = _as_nonnegative_int(getattr(prompt_details, "cached_tokens", None))
        return TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_input_tokens=cached_tokens,
        )

    async def generate(
        self,
        model: LLMModelConfig,
        request: GenerationRequest,
    ) -> GenerationResult:
        try:
            response = await self._client.chat.completions.create(
                **self._build_payload(model, request),
                stream=False,
            )
            choices = getattr(response, "choices", None) or []
            if not choices:
                raise ValueError("Provider returned no completion choices")
            message = getattr(choices[0], "message", None)
            content = _text_content(getattr(message, "content", None))
            if content is None:
                raise ValueError("Provider returned no text content")
            return GenerationResult(
                model_id=model.id,
                provider_id=self.provider_id,
                content=content,
                finish_reason=_optional_string(getattr(choices[0], "finish_reason", None)),
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
        usage = TokenUsage()
        finish_reason: str | None = None
        request_id: str | None = None
        try:
            payload = self._build_payload(model, request)
            stream_options: dict[str, bool] | None = None
            if self.config.include_usage_in_stream:
                stream_options = {"include_usage": True}
            stream = await self._client.chat.completions.create(
                **payload,
                stream=True,
                **({"stream_options": stream_options} if stream_options else {}),
            )
            async for chunk in stream:
                request_id = _optional_string(getattr(chunk, "id", None)) or request_id
                raw_usage = getattr(chunk, "usage", None)
                if raw_usage is not None:
                    usage = self._usage(raw_usage)
                for choice in getattr(chunk, "choices", None) or []:
                    delta = getattr(choice, "delta", None)
                    text = _text_content(getattr(delta, "content", None))
                    if text:
                        yield GenerationEvent(type=GenerationEventType.TEXT_DELTA, text=text)
                    current_finish = _optional_string(getattr(choice, "finish_reason", None))
                    if current_finish:
                        finish_reason = current_finish
            if finish_reason is None:
                raise ProviderResponseError(self.provider_id)
            if usage.input_tokens is not None or usage.output_tokens is not None:
                yield GenerationEvent(type=GenerationEventType.USAGE, usage=usage)
            yield GenerationEvent(
                type=GenerationEventType.COMPLETED,
                usage=usage,
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
                        # Closing a failed upstream stream must not mask its original error.
                        pass

    async def close(self) -> None:
        if self._owns_client:
            close = getattr(self._client, "close", None)
            if callable(close):
                await close()


def _as_nonnegative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _text_content(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [
            getattr(item, "text", None)
            for item in value
            if getattr(item, "type", None) == "text"
            and isinstance(getattr(item, "text", None), str)
        ]
        return "".join(parts) if parts else None
    return None
