from types import SimpleNamespace

from ask_ai.modules.llm.errors import (
    ProviderAuthenticationError,
    ProviderBadRequestError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    normalize_provider_exception,
)


def test_normalizes_authentication_error() -> None:
    class AuthenticationError(Exception):
        status_code = 401

    normalized = normalize_provider_exception("openai", AuthenticationError("bad credential"))
    assert isinstance(normalized, ProviderAuthenticationError)
    assert normalized.retryable is False


def test_normalizes_rate_limit_and_retry_after() -> None:
    class RateLimitError(Exception):
        status_code = 429
        response = SimpleNamespace(headers={"Retry-After": "3"})

    normalized = normalize_provider_exception("openai", RateLimitError("raw secret"))
    assert isinstance(normalized, ProviderRateLimitError)
    assert normalized.retryable is True
    assert normalized.retry_after_seconds == 3
    assert "raw secret" not in str(normalized)


def test_normalizes_timeout() -> None:
    normalized = normalize_provider_exception("anthropic", TimeoutError("socket timeout"))
    assert isinstance(normalized, ProviderTimeoutError)
    assert normalized.retryable is True


def test_normalizes_transport_and_upstream_server_errors() -> None:
    class ConnectError(Exception):
        pass

    class APIError(Exception):
        status_code = 503

    assert isinstance(
        normalize_provider_exception("openai", ConnectError("connection failed")),
        ProviderUnavailableError,
    )
    assert isinstance(
        normalize_provider_exception("openai", APIError("upstream error")),
        ProviderUnavailableError,
    )


def test_normalizes_invalid_request() -> None:
    class BadRequestError(Exception):
        status_code = 400

    normalized = normalize_provider_exception("openai", BadRequestError("bad request"))
    assert isinstance(normalized, ProviderBadRequestError)
    assert normalized.retryable is False
