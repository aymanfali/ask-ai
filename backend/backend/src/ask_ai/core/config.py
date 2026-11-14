from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
AppEnvironment = Literal["local", "test", "staging", "production"]


class Settings(BaseSettings):
    """Validated runtime configuration.

    Environment variables are authoritative. The root .env file is convenient for
    local development only; production secrets must be injected by the deployment
    platform or secret manager.
    """

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        validate_default=True,
    )

    app_name: str = "Ask AI"
    app_env: AppEnvironment = "local"
    app_debug: bool = False
    api_v1_prefix: str = "/api/v1"
    log_level: LogLevel = "INFO"

    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)

    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://ask_ai:ask_ai_local_only@localhost:5432/ask_ai"
    )
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")

    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_max_overflow: int = Field(default=20, ge=0, le=200)
    db_pool_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    db_pool_recycle_seconds: int = Field(default=1800, ge=60, le=86400)
    db_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    redis_max_connections: int = Field(default=50, ge=1, le=1000)
    redis_socket_connect_timeout_seconds: float = Field(default=3.0, gt=0, le=60)
    redis_socket_timeout_seconds: float = Field(default=3.0, gt=0, le=60)

    health_check_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    cors_origins: list[str] = Field(default_factory=list)

    # Authentication and first-party token settings.
    secret_key: SecretStr = SecretStr("ask-ai-local-development-secret-change-me-please-123456789")
    jwt_issuer: str = "ask-ai"
    jwt_audience: str = "ask-ai-api"
    access_token_ttl_minutes: int = Field(default=15, ge=5, le=60)
    refresh_token_ttl_days: int = Field(default=30, ge=1, le=90)
    refresh_session_absolute_ttl_days: int = Field(default=90, ge=7, le=180)
    auth_allow_registration: bool = True

    auth_refresh_cookie_name: str = "ask_ai_refresh"
    auth_csrf_cookie_name: str = "ask_ai_csrf"
    auth_session_cookie_name: str = "ask_ai_oauth"
    auth_cookie_secure: bool = False
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    auth_oauth_session_ttl_seconds: int = Field(default=600, ge=60, le=1800)
    oauth_exchange_code_ttl_seconds: int = Field(default=60, ge=15, le=180)
    frontend_auth_callback_url: str = "http://localhost:5173/auth/callback"

    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    apple_client_id: str | None = None
    apple_client_secret: SecretStr | None = None
    apple_redirect_uri: str = "http://localhost:8000/api/v1/auth/apple/callback"

    @field_validator("google_client_id", "apple_client_id", mode="before")
    @classmethod
    def empty_client_id_to_none(cls, value: str | None) -> str | None:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("google_client_secret", "apple_client_secret", mode="before")
    @classmethod
    def empty_client_secret_to_none(cls, value: SecretStr | str | None) -> SecretStr | str | None:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("api_v1_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        if not value.startswith("/") or value == "/" or value.endswith("/"):
            raise ValueError("api_v1_prefix must start with '/' and must not end with '/'")
        if "?" in value or "#" in value:
            raise ValueError("api_v1_prefix cannot contain a query or fragment")
        return value

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw_value in values:
            value = raw_value.strip().rstrip("/")
            if value == "*":
                raise ValueError("CORS wildcard origins are not allowed with credentials")
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(f"Invalid CORS origin: {raw_value!r}")
            if value not in normalized:
                normalized.append(value)
        return normalized

    @model_validator(mode="after")
    def validate_environment_settings(self) -> "Settings":
        database_url = self.database_url.get_secret_value()
        if not database_url.startswith(("postgresql+asyncpg://", "sqlite+aiosqlite://")):
            raise ValueError("DATABASE_URL must use postgresql+asyncpg or sqlite+aiosqlite")
        if database_url.startswith("sqlite+") and self.app_env != "test":
            raise ValueError("SQLite is only supported in the test environment")
        redis_url = self.redis_url.get_secret_value()
        if not redis_url.startswith(("redis://", "rediss://")):
            raise ValueError("REDIS_URL must use redis:// or rediss://")
        secret = self.secret_key.get_secret_value()
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("SECRET_KEY must contain at least 32 bytes")
        if self.refresh_session_absolute_ttl_days < self.refresh_token_ttl_days:
            raise ValueError("Refresh session absolute lifetime must be >= refresh token lifetime")
        callback = urlsplit(self.frontend_auth_callback_url)
        if (
            callback.scheme not in {"http", "https"}
            or not callback.netloc
            or callback.username is not None
            or callback.password is not None
            or callback.query
            or callback.fragment
        ):
            raise ValueError(
                "FRONTEND_AUTH_CALLBACK_URL must be an absolute HTTP(S) URL "
                "without query or fragment"
            )
        provider_pairs = (
            (self.google_client_id, self.google_client_secret, "Google"),
            (self.apple_client_id, self.apple_client_secret, "Apple"),
        )
        for client_id, client_secret, provider_name in provider_pairs:
            if bool(client_id) != bool(client_secret):
                raise ValueError(
                    f"Both {provider_name} OAuth client ID and client secret must be configured"
                )
        provider_redirects = (
            (self.google_client_id, self.google_redirect_uri, "Google"),
            (self.apple_client_id, self.apple_redirect_uri, "Apple"),
        )
        for client_id, redirect_uri, provider_name in provider_redirects:
            parsed_redirect = urlsplit(redirect_uri)
            if (
                parsed_redirect.scheme not in {"http", "https"}
                or not parsed_redirect.netloc
                or parsed_redirect.username is not None
                or parsed_redirect.password is not None
                or parsed_redirect.fragment
            ):
                raise ValueError(f"{provider_name} redirect URI must be an absolute HTTP(S) URL")
        if self.auth_cookie_samesite == "none" and not self.auth_cookie_secure:
            raise ValueError("SameSite=None cookies require Secure")
        if self.app_env in {"staging", "production"}:
            if self.secret_key.get_secret_value().startswith("ask-ai-local-development-"):
                raise ValueError(
                    f"{self.app_env.title()} SECRET_KEY must be a unique random secret"
                )
            if not self.auth_cookie_secure:
                raise ValueError("AUTH_COOKIE_SECURE must be true outside local/test environments")
            if callback.scheme != "https":
                raise ValueError(
                    "FRONTEND_AUTH_CALLBACK_URL must use HTTPS outside local/test environments"
                )
            if any(
                urlsplit(uri).scheme != "https"
                for client_id, uri, _ in provider_redirects
                if client_id
            ):
                raise ValueError(
                    "Configured OAuth redirect URIs must use HTTPS outside local/test environments"
                )
            if any(not origin.startswith("https://") for origin in self.cors_origins):
                raise ValueError("CORS_ORIGINS must use HTTPS outside local/test environments")
            if "ask_ai_local_only" in database_url:
                raise ValueError("DATABASE_URL must not use the local-development credentials")
            if not redis_url.startswith("rediss://"):
                raise ValueError(
                    "REDIS_URL must use TLS (rediss://) outside local/test environments"
                )
            if self.app_debug:
                raise ValueError("APP_DEBUG must be false outside local/test environments")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide immutable-by-convention settings object."""
    return Settings()
