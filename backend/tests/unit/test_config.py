import pytest
from pydantic import ValidationError

from ask_ai.core.config import Settings


def test_settings_accept_valid_local_configuration() -> None:
    settings = Settings(
        app_env="test",
        cors_origins=["http://localhost:5173", "https://app.example.test"],
    )
    assert settings.app_env == "test"
    assert settings.cors_origins == [
        "http://localhost:5173",
        "https://app.example.test",
    ]


@pytest.mark.parametrize(
    "origins",
    [
        ["*"],
        ["ftp://example.test"],
        ["https://example.test/path"],
        ["https://user:password@example.test"],
    ],
)
def test_settings_reject_unsafe_cors_origins(origins: list[str]) -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="test", cors_origins=origins)


def test_production_disallows_debug_mode() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="production", app_debug=True)


def test_database_url_must_use_supported_async_driver() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="test", database_url="postgresql://localhost/db")


def test_sqlite_is_restricted_to_test_environment() -> None:
    with pytest.raises(ValidationError):
        Settings(
            app_env="local",
            database_url="sqlite+aiosqlite:///:memory:",
        )


def test_production_requires_tls_redis() -> None:
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            app_debug=False,
            database_url="postgresql+asyncpg://user:strong-password@db.example.test/ask_ai",
            redis_url="redis://cache.example.test:6379/0",
        )


def test_production_rejects_insecure_llm_provider_endpoint() -> None:
    from pydantic import ValidationError

    provider = {
        "id": "gateway",
        "name": "Private Gateway",
        "type": "openai_compatible",
        "api_key": "provider-test-secret",
        "base_url": "http://gateway.internal/v1",
    }
    with pytest.raises(ValidationError, match="provider endpoints must use HTTPS"):
        Settings(
            app_env="production",
            secret_key="unique-production-secret-value-0123456789",
            auth_cookie_secure=True,
            frontend_auth_callback_url="https://app.example.com/auth/callback",
            cors_origins=["https://app.example.com"],
            database_url="postgresql+asyncpg://ask_ai:strong-password@db.example.com/ask_ai",
            redis_url="rediss://redis.example.com:6379/0",
            llm_providers=[provider],
        )
