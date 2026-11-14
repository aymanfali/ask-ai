from __future__ import annotations

from urllib.parse import urlencode

import pytest
from fastapi import Request

from ask_ai.core.errors import ApplicationError
from ask_ai.modules.auth.oauth_callbacks import build_oauth_callback_request


def make_request(
    *,
    method: str,
    body: bytes = b"",
    query_string: bytes = b"",
    content_type: str | None = None,
    session: dict[str, str] | None = None,
) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if content_type:
        headers.append((b"content-type", content_type.encode("ascii")))
    if method == "POST":
        headers.append((b"content-length", str(len(body)).encode("ascii")))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": "/api/v1/auth/apple/callback",
        "raw_path": b"/api/v1/auth/apple/callback",
        "query_string": query_string,
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("localhost", 443),
        "session": session if session is not None else {"state": "preserved"},
    }
    sent = False

    async def receive() -> dict[str, object]:
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


@pytest.mark.asyncio
async def test_apple_form_post_is_normalized_without_losing_oauth_session() -> None:
    session = {"authlib.state": "test-state"}
    body = urlencode({"code": "provider-code", "state": "test-state"}).encode()
    request = make_request(
        method="POST",
        body=body,
        content_type="application/x-www-form-urlencoded",
        session=session,
    )

    callback = await build_oauth_callback_request("apple", request)

    assert callback.method == "GET"
    assert callback.query_params["code"] == "provider-code"
    assert callback.query_params["state"] == "test-state"
    assert callback.scope["session"] is session
    assert callback.headers.get("content-type") is None


@pytest.mark.asyncio
async def test_apple_form_post_rejects_duplicate_state() -> None:
    body = b"code=provider-code&state=one&state=two"
    request = make_request(
        method="POST",
        body=body,
        content_type="application/x-www-form-urlencoded",
    )

    with pytest.raises(ApplicationError) as error:
        await build_oauth_callback_request("apple", request)

    assert error.value.code == "invalid_oauth_callback"


@pytest.mark.asyncio
async def test_apple_form_post_rejects_wrong_content_type() -> None:
    request = make_request(
        method="POST",
        body=b"code=x&state=y",
        content_type="application/json",
    )

    with pytest.raises(ApplicationError):
        await build_oauth_callback_request("apple", request)


@pytest.mark.asyncio
async def test_apple_form_post_rejects_get_callback() -> None:
    request = make_request(method="GET")

    with pytest.raises(ApplicationError):
        await build_oauth_callback_request("apple", request)


@pytest.mark.asyncio
async def test_google_query_callback_remains_get_based() -> None:
    query = urlencode({"code": "google-code", "state": "google-state"}).encode()
    request = make_request(method="GET", query_string=query)

    callback = await build_oauth_callback_request("google", request)

    assert callback.query_params["code"] == "google-code"
    assert callback.query_params["state"] == "google-state"


@pytest.mark.asyncio
async def test_callback_rejects_missing_state_and_code_or_error() -> None:
    request = make_request(method="GET", query_string=b"code=provider-code")

    with pytest.raises(ApplicationError):
        await build_oauth_callback_request("google", request)


@pytest.mark.asyncio
async def test_callback_rejects_code_and_error_together() -> None:
    query = b"code=provider-code&state=state-value&error=access_denied"
    request = make_request(method="GET", query_string=query)

    with pytest.raises(ApplicationError):
        await build_oauth_callback_request("google", request)
