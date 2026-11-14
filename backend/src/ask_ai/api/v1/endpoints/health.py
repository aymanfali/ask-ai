import asyncio
from collections.abc import Awaitable, Callable

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

router = APIRouter(tags=["health"])
logger = structlog.get_logger(__name__)


@router.get("/health/live", summary="Liveness probe")
async def liveness() -> dict[str, str]:
    """Return success while the API process can serve requests."""
    return {"status": "ok"}


async def _database_probe(engine: AsyncEngine | None) -> bool:
    if engine is None:
        return False
    async with engine.connect() as connection:
        result = await connection.execute(text("SELECT 1"))
        return result.scalar_one() == 1


async def _redis_probe(client: Redis | None) -> bool:
    if client is None:
        return False
    return bool(await client.ping())


async def _run_probe(
    name: str,
    operation: Callable[[], Awaitable[bool]],
    timeout: float,
) -> bool:
    try:
        return bool(await asyncio.wait_for(operation(), timeout=timeout))
    except Exception as exc:
        logger.warning(
            "dependency_health_check_failed",
            dependency=name,
            error_type=type(exc).__name__,
        )
        return False


@router.get("/health/ready", summary="Readiness probe")
async def readiness(request: Request) -> JSONResponse:
    """Check required dependencies without exposing connection details."""
    settings = request.app.state.settings
    engine = getattr(request.app.state, "db_engine", None)
    redis_client = getattr(request.app.state, "redis", None)

    database_ok, redis_ok = await asyncio.gather(
        _run_probe(
            "database",
            lambda: _database_probe(engine),
            settings.health_check_timeout_seconds,
        ),
        _run_probe(
            "redis",
            lambda: _redis_probe(redis_client),
            settings.health_check_timeout_seconds,
        ),
    )
    ready = database_ok and redis_ok
    payload = {
        "status": "ready" if ready else "not_ready",
        "checks": {
            "database": "ok" if database_ok else "unavailable",
            "redis": "ok" if redis_ok else "unavailable",
        },
    }
    return JSONResponse(status_code=200 if ready else 503, content=payload)
