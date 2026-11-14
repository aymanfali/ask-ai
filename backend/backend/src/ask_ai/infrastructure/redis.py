from redis.asyncio import Redis

from ask_ai.core.config import Settings


def create_redis_client(settings: Settings) -> Redis:
    """Construct a lazy Redis client; the first network operation occurs on use."""
    return Redis.from_url(
        settings.redis_url.get_secret_value(),
        encoding="utf-8",
        decode_responses=True,
        max_connections=settings.redis_max_connections,
        socket_connect_timeout=settings.redis_socket_connect_timeout_seconds,
        socket_timeout=settings.redis_socket_timeout_seconds,
        health_check_interval=30,
    )
