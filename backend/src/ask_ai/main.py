from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

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
from ask_ai.core.security_keys import derive_application_key
from ask_ai.database.engine import create_database_engine
from ask_ai.infrastructure.redis import create_redis_client
from ask_ai.modules.auth.oauth import create_oauth_registry
from ask_ai.modules.llm.catalog import ModelCatalog
from ask_ai.modules.llm.registry import ProviderRegistry, create_provider_registry
from ask_ai.modules.llm.service import LLMService


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Create and deterministically dispose shared infrastructure clients."""
    settings: Settings = application.state.settings
    engine = create_database_engine(settings)
    redis_client = None
    provider_registry: ProviderRegistry | None = None
    try:
        redis_client = create_redis_client(settings)
        provider_registry = await create_provider_registry(settings)
        application.state.db_engine = engine
        application.state.db_session_factory = async_sessionmaker(
            bind=engine,
            expire_on_commit=False,
            autoflush=False,
        )
        application.state.redis = redis_client
        application.state.llm_providers = provider_registry
        application.state.llm_service = LLMService(
            catalog=application.state.llm_catalog,
            registry=provider_registry,
        )
        yield
    finally:
        try:
            if provider_registry is not None:
                await provider_registry.close()
        finally:
            try:
                if redis_client is not None:
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
    application.state.llm_catalog = ModelCatalog(
        providers=runtime_settings.llm_providers,
        models=runtime_settings.llm_models,
    )
    oauth_registry = create_oauth_registry(runtime_settings)
    application.state.oauth_registry = oauth_registry
    application.state.oauth_clients = {
        provider: oauth_registry.create_client(provider)
        for provider in ("google", "apple")
        if (
            provider == "google"
            and runtime_settings.google_client_id
            and runtime_settings.google_client_secret
        )
        or (
            provider == "apple"
            and runtime_settings.apple_client_id
            and runtime_settings.apple_client_secret
        )
    }

    application.add_exception_handler(ApplicationError, application_error_handler)
    application.add_exception_handler(RequestValidationError, validation_error_handler)
    application.add_exception_handler(StarletteHTTPException, http_error_handler)
    application.add_exception_handler(Exception, unhandled_error_handler)

    apple_oidc_enabled = bool(
        runtime_settings.apple_client_id and runtime_settings.apple_client_secret
    )
    # OAuth state must survive the identity provider's cross-site redirect.
    # Google returns by top-level GET (Lax); Apple requires form_post (None + Secure).
    oauth_session_same_site = "none" if apple_oidc_enabled else "lax"
    oauth_session_secure = runtime_settings.auth_cookie_secure or apple_oidc_enabled
    application.add_middleware(
        SessionMiddleware,
        secret_key=derive_application_key(runtime_settings, "oauth-session").hex(),
        session_cookie=runtime_settings.auth_session_cookie_name,
        max_age=runtime_settings.auth_oauth_session_ttl_seconds,
        same_site=oauth_session_same_site,
        https_only=oauth_session_secure,
        path=f"{runtime_settings.api_v1_prefix}/auth",
    )

    if runtime_settings.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=runtime_settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "Idempotency-Key",
                "X-Request-ID",
                "X-CSRF-Token",
            ],
            expose_headers=["X-Request-ID"],
        )

    application.add_middleware(RequestContextMiddleware)
    application.include_router(api_router, prefix=runtime_settings.api_v1_prefix)
    return application


app = create_app()
