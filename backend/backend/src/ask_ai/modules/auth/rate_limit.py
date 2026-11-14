from __future__ import annotations

from typing import Any

from fastapi import Request

from ask_ai.core.errors import ApplicationError

_RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""


async def enforce_rate_limit(
    request: Request,
    *,
    bucket: str,
    limit: int,
    window_seconds: int,
) -> None:
    redis_client: Any = getattr(request.app.state, "redis", None)
    if redis_client is None:
        raise ApplicationError(
            code="rate_limiter_unavailable",
            message="Authentication is temporarily unavailable. Please try again.",
            status_code=503,
        )
    try:
        count, ttl = await redis_client.eval(
            _RATE_LIMIT_SCRIPT,
            1,
            f"auth:rate-limit:{bucket}",
            window_seconds,
        )
    except Exception as exc:
        raise ApplicationError(
            code="rate_limiter_unavailable",
            message="Authentication is temporarily unavailable. Please try again.",
            status_code=503,
        ) from exc
    if int(count) > limit:
        raise ApplicationError(
            code="rate_limit_exceeded",
            message="Too many authentication attempts. Please try again later.",
            status_code=429,
            details={"retry_after_seconds": max(int(ttl), 1)},
        )


def client_ip(request: Request) -> str:
    # Do not trust X-Forwarded-For until a trusted-proxy configuration is added.
    return request.client.host if request.client else "unknown"
