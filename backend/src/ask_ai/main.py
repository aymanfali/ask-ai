from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from ask_ai.api.v1.router import api_router
from ask_ai.core.config import Settings, get_settings
from ask_ai.core.errors import ApplicationError
from ask_ai.core.exception_handlers import (
    application_error_handler,
    http_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from ask_ai.core.logging import configure_logging
from ask_ai.core.middleware import RequestContextMiddleware
from ask_ai.database.engine import create_database_engine
from ask_ai.infrastructure.redis import create_redis_client


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Create and deterministically dispose shared infrastructure clients."""
    settings: Settings = application.state.settings
    engine = create_database_engine(settings)
    try:
        redis_client = create_redis_client(settings)
    except Exception:
        await engine.dispose()
        raise

    try:
        application.state.db_engine = engine
        application.state.db_session_factory = async_sessionmaker(
            bind=engine,
            expire_on_commit=False,
            autoflush=False,
        )
        application.state.redis = redis_client
        yield
    finally:
        try:
            await redis_client.aclose()
        finally:
            await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or get_settings()
    configure_logging(runtime_settings.log_level, runtime_settings.app_env)

    application = FastAPI(
        title=runtime_settings.app_name,
        version="0.1.0",
        debug=runtime_settings.app_debug,
        lifespan=lifespan,
        docs_url="/docs" if runtime_settings.app_env != "production" else None,
        redoc_url="/redoc" if runtime_settings.app_env != "production" else None,
    )
    application.state.settings = runtime_settings

    application.add_exception_handler(ApplicationError, application_error_handler)
    application.add_exception_handler(RequestValidationError, validation_error_handler)
    application.add_exception_handler(StarletteHTTPException, http_error_handler)
    application.add_exception_handler(Exception, unhandled_error_handler)

    if runtime_settings.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=runtime_settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
            expose_headers=["X-Request-ID"],
        )

    application.add_middleware(RequestContextMiddleware)
    application.include_router(api_router, prefix=runtime_settings.api_v1_prefix)
    return application


app = create_app()
