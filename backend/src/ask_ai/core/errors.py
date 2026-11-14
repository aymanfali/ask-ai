from typing import Any


class ApplicationError(Exception):
    """An expected application error safe to expose through the public API."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
