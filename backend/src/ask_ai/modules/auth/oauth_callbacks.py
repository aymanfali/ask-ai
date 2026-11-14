from __future__ import annotations

from urllib.parse import parse_qs, urlencode

from fastapi import Request
from starlette.requests import Request as StarletteRequest

from ask_ai.core.errors import ApplicationError

_MAX_CALLBACK_BODY_BYTES = 16_384
_ALLOWED_CALLBACK_PARAMETERS = {
    "code",
    "state",
    "error",
    "error_description",
    "iss",
}
_MAXIMUM_PARAMETER_LENGTHS = {
    "code": 8192,
    "state": 1024,
    "error": 128,
    "error_description": 2048,
    "iss": 2048,
}


async def build_oauth_callback_request(
    provider: str,
    request: Request,
) -> StarletteRequest:
    """Normalize OIDC callback parameters for Authlib's Starlette adapter.

    Authlib's Starlette client reads callback values from query_params. Apple
    requires response_mode=form_post when requesting email/name scopes, so its
    bounded URL-encoded form is copied into a synthetic GET request while
    preserving the original ASGI scope, including signed session state.
    """
    if provider == "apple":
        if request.method != "POST":
            raise _invalid_callback()
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/x-www-form-urlencoded":
            raise _invalid_callback()

        content_length = request.headers.get("content-length")
        if content_length is not None:
            if not content_length.isdigit():
                raise _invalid_callback()
            if int(content_length) > _MAX_CALLBACK_BODY_BYTES:
                raise _invalid_callback(status_code=413)

        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > _MAX_CALLBACK_BODY_BYTES:
                raise _invalid_callback(status_code=413)
        try:
            decoded_body = body.decode("utf-8")
            parsed_form = parse_qs(
                decoded_body,
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=10,
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise _invalid_callback() from exc
        source = [(name, value) for name, values in parsed_form.items() for value in values]
    else:
        if provider != "google" or request.method != "GET":
            raise _invalid_callback()
        raw_query = request.scope.get("query_string", b"")
        if len(raw_query) > _MAX_CALLBACK_BODY_BYTES:
            raise _invalid_callback(status_code=413)
        source = request.query_params.multi_items()

    parameters: dict[str, str] = {}
    for name, raw_value in source:
        if name not in _ALLOWED_CALLBACK_PARAMETERS:
            continue
        if name in parameters or not isinstance(raw_value, str):
            raise _invalid_callback()
        if len(raw_value) > _MAXIMUM_PARAMETER_LENGTHS[name]:
            raise _invalid_callback(status_code=413)
        parameters[name] = raw_value

    has_code = bool(parameters.get("code"))
    has_error = bool(parameters.get("error"))
    if not parameters.get("state") or has_code == has_error:
        raise _invalid_callback()

    callback_scope = dict(request.scope)
    callback_scope["method"] = "GET"
    callback_scope["query_string"] = urlencode(parameters).encode("ascii")
    callback_scope["headers"] = [
        (name, value)
        for name, value in request.scope.get("headers", [])
        if name.lower() not in {b"content-length", b"content-type"}
    ]
    return StarletteRequest(callback_scope)


def _invalid_callback(*, status_code: int = 400) -> ApplicationError:
    return ApplicationError(
        code="invalid_oauth_callback",
        message="The identity provider returned an invalid callback.",
        status_code=status_code,
    )
