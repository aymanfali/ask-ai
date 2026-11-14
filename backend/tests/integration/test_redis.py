import os

import pytest
from redis.asyncio import Redis


@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_ping_and_round_trip() -> None:
    redis_url = os.getenv("TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("TEST_REDIS_URL is not configured")

    client = Redis.from_url(redis_url, decode_responses=True)
    key = "ask-ai:test:milestone-1"
    try:
        assert await client.ping()
        await client.set(key, "ok", ex=30)
        assert await client.get(key) == "ok"
    finally:
        await client.delete(key)
        await client.aclose()
