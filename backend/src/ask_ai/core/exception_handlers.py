from typing import Any

import structlog
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ask_ai.core.errors import ApplicationError

logger = structlog.get_logger(__name__)


def _request_id(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else None


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: Any | None = None,
) -> JSONResponse:
    request_id = _request_id(request)
    return JSONResponse(
        status_code=status_code,
        headers={"X-Request-ID": request_id} if request_id else None,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
                "request_id": request_id,
            }
        },
    )


async def application_error_handler(
    request: Request,
    exc: ApplicationError,
) -> JSONResponse:
    return _error_response(
        request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    # Never echo rejected input values: they may contain passwords or other secrets.
    details = [
        {
            "location": list(error.get("loc", ())),
            "message": str(error.get("msg", "Invalid value")),
            "type": str(error.get("type", "value_error")),
        }
        for error in exc.errors()
    ]
    return _error_response(
        request,
        status_code=422,
        code="validation_error",
        message="The request contains invalid data.",
        details=details,
    )


async def http_error_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    status_messages = {
        400: "The request could not be processed.",
        401: "Authentication is required.",
        403: "You are not allowed to perform this action.",
        404: "The requested resource was not found.",
        405: "The requested method is not allowed.",
        409: "The request conflicts with the current resource state.",
        413: "The request is too large.",
        415: "The request media type is not supported.",
        429: "Too many requests. Please try again later.",
    }
    message = status_messages.get(exc.status_code)
    if message is None:
        # Application-specific client messages should use ApplicationError instead.
        message = (
            "The server could not complete the request."
            if exc.status_code >= 500
            else "The request could not be processed."
        )
    return _error_response(
        request,
        status_code=exc.status_code,
        code="http_error",
        message=message,
        details=None,
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Log the exception class only. Exception messages can contain connection strings
    # or provider credentials; detailed diagnostics belong in a separately secured sink.
    logger.error(
        "unhandled_application_exception",
        request_id=_request_id(request),
        path=request.url.path,
        error_type=type(exc).__name__,
    )
    return _error_response(
        request,
        status_code=500,
        code="internal_server_error",
        message="An unexpected error occurred.",
    )
