import logging
import logging.config
import re
from collections.abc import Mapping
from typing import Any, cast

import structlog

_SENSITIVE_KEY_PARTS = (
    "password",
    "secret",
    "api_key",
    "authorization",
    "cookie",
)
_SENSITIVE_EXACT_KEYS = {"token", "database_url", "redis_url", "dsn"}
_REDACTED = "[REDACTED]"


def _is_sensitive_key(key: object) -> bool:
    raw_key = re.sub(r"(?<!^)(?=[A-Z])", "_", str(key))
    normalized = re.sub(r"[^a-z0-9_]", "_", raw_key.lower())
    return (
        normalized in _SENSITIVE_EXACT_KEYS
        or normalized.endswith("_token")
        or any(part in normalized for part in _SENSITIVE_KEY_PARTS)
    )


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _REDACTED if _is_sensitive_key(key) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value


def redact_sensitive_data(
    _: Any,
    __: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Redact credential-like fields, including nested mappings."""
    return cast(dict[str, Any], _redact(event_dict))


def configure_logging(level: str, environment: str) -> None:
    """Configure standard-library and structlog loggers consistently."""
    renderer: Any = structlog.processors.JSONRenderer()
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        redact_sensitive_data,
    ]

    if environment == "local":
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"structured": {"()": lambda: formatter}},
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "formatter": "structured",
                    "stream": "ext://sys.stdout",
                }
            },
            "root": {"handlers": ["default"], "level": level},
            "loggers": {
                "uvicorn": {"handlers": ["default"], "level": level, "propagate": False},
                "uvicorn.error": {"handlers": ["default"], "level": level, "propagate": False},
                "uvicorn.access": {"handlers": ["default"], "level": level, "propagate": False},
            },
        }
    )

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
