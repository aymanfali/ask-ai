from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any


class ProviderError(Exception):
    """Safe, provider-neutral error; never includes raw response bodies or secrets."""

    def __init__(
        self,
        *,
        provider_id: str,
        code: str,
        retryable: bool,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(f"Provider {provider_id} failed ({code})")
        self.provider_id = provider_id
        self.code = code
        self.retryable = retryable
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


class ProviderConfigurationError(ProviderError):
    def __init__(self, provider_id: str) -> None:
        super().__init__(
            provider_id=provider_id,
            code="provider_configuration_error",
            retryable=False,
        )


class ProviderAuthenticationError(ProviderError):
    def __init__(self, provider_id: str, status_code: int = 401) -> None:
        super().__init__(
            provider_id=provider_id,
            code="provider_authentication_failed",
            retryable=False,
            status_code=status_code,
        )


class ProviderRateLimitError(ProviderError):
    def __init__(self, provider_id: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(
            provider_id=provider_id,
            code="provider_rate_limited",
            retryable=True,
            status_code=429,
            retry_after_seconds=retry_after_seconds,
        )


class ProviderTimeoutError(ProviderError):
    def __init__(self, provider_id: str) -> None:
        super().__init__(
            provider_id=provider_id,
            code="provider_timeout",
            retryable=True,
        )


class ProviderUnavailableError(ProviderError):
    def __init__(self, provider_id: str, status_code: int | None = None) -> None:
        super().__init__(
            provider_id=provider_id,
            code="provider_unavailable",
            retryable=True,
            status_code=status_code,
        )


class ProviderBadRequestError(ProviderError):
    def __init__(self, provider_id: str, status_code: int | None = None) -> None:
        super().__init__(
            provider_id=provider_id,
            code="provider_rejected_request",
            retryable=False,
            status_code=status_code,
        )


class ProviderResponseError(ProviderError):
    def __init__(self, provider_id: str) -> None:
        super().__init__(
            provider_id=provider_id,
            code="invalid_provider_response",
            retryable=False,
        )


def _retry_after_seconds(error: Exception) -> float | None:
    response: Any = getattr(error, "response", None)
    headers: Any = getattr(response, "headers", None)
    if headers is None:
        return None
    raw = headers.get("retry-after") or headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return max(0.0, min(float(raw), 300.0))
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(str(raw))
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            return max(0.0, min((retry_at - datetime.now(UTC)).total_seconds(), 300.0))
        except (TypeError, ValueError, OverflowError):
            return None


def normalize_provider_exception(provider_id: str, error: Exception) -> ProviderError:
    """Map SDK/HTTP failures to stable safe error categories without leaking details."""
    if isinstance(error, ProviderError):
        return error

    type_name = type(error).__name__.casefold()
    status_code_value = getattr(error, "status_code", None)
    status_code = status_code_value if isinstance(status_code_value, int) else None

    if (
        "timeout" in type_name
        or status_code in {408, 504}
        or isinstance(error, TimeoutError)
    ):
        return ProviderTimeoutError(provider_id)
    if status_code in {401, 403} or "authentication" in type_name:
        return ProviderAuthenticationError(provider_id, status_code or 401)
    if status_code == 429 or "ratelimit" in type_name or "rate_limit" in type_name:
        return ProviderRateLimitError(provider_id, _retry_after_seconds(error))
    if status_code in {400, 404, 413, 422}:
        return ProviderBadRequestError(provider_id, status_code)
    if status_code is not None and status_code >= 500:
        return ProviderUnavailableError(provider_id, status_code)
    if (
        "connection" in type_name
        or "connect" in type_name
        or "transport" in type_name
        or isinstance(error, OSError)
    ):
        return ProviderUnavailableError(provider_id, status_code)
    return ProviderResponseError(provider_id)
