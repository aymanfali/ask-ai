import time
import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = structlog.get_logger(__name__)


def _request_id_from_headers(headers: list[tuple[bytes, bytes]]) -> str:
    for name, value in headers:
        if name.lower() == b"x-request-id":
            try:
                candidate = value.decode("ascii").strip()
            except UnicodeDecodeError:
                break
            # Restrict accepted client IDs to UUIDs to prevent log/header injection.
            try:
                return str(uuid.UUID(candidate))
            except (ValueError, AttributeError):
                break
    return str(uuid.uuid4())


class RequestContextMiddleware:
    """Pure ASGI middleware for correlation IDs and request metrics.

    Query strings and request/response bodies are deliberately not logged.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id_from_headers(scope.get("headers", []))
        scope.setdefault("state", {})["request_id"] = request_id
        context_token = structlog.contextvars.bind_contextvars(request_id=request_id)
        started_at = time.perf_counter()
        status_code = 500

        async def send_with_context(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_context)
        except Exception as exc:
            # Avoid logging exception text or request bodies; either can contain credentials.
            logger.error(
                "http_request_unhandled_exception",
                method=scope.get("method"),
                path=scope.get("path"),
                error_type=type(exc).__name__,
            )
            raise
        finally:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            logger.info(
                "http_request",
                method=scope.get("method"),
                path=scope.get("path"),
                status_code=status_code,
                duration_ms=duration_ms,
            )
            structlog.contextvars.reset_contextvars(**context_token)
