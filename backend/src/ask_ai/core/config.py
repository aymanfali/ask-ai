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

    # Reserved for the authentication milestone. It is not used by Milestone 1.
    secret_key: SecretStr | None = None

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
        if self.app_env == "production":
            if self.app_debug:
                raise ValueError("APP_DEBUG must be false in production")
            if "ask_ai_local_only" in database_url:
                raise ValueError("DATABASE_URL must not use the local-development credentials")
            if not redis_url.startswith("rediss://"):
                raise ValueError("Production REDIS_URL must use TLS (rediss://)")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide immutable-by-convention settings object."""
    return Settings()
