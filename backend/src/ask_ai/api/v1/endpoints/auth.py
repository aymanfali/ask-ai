from __future__ import annotations

import hashlib
from typing import Annotated, Any
from urllib.parse import quote

import structlog
from authlib.integrations.base_client.errors import OAuthError
from joserfc.errors import JoseError
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from httpx2 import HTTPError as HTTPX2Error
from sqlalchemy.ext.asyncio import AsyncSession

from ask_ai.core.config import Settings
from ask_ai.core.errors import ApplicationError
from ask_ai.database.session import get_db_session
from ask_ai.modules.auth.dependencies import (
    get_current_user,
    require_csrf,
    user_response_values,
)
from ask_ai.modules.auth.models import User
from ask_ai.modules.auth.rate_limit import client_ip, enforce_rate_limit
from ask_ai.modules.auth.schemas import (
    AuthProvidersResponse,
    CsrfTokenResponse,
    LoginRequest,
    OAuthExchangeRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from ask_ai.modules.auth.service import AuthService, IssuedTokens

router = APIRouter(prefix="/auth", tags=["authentication"])
logger = structlog.get_logger(__name__)


def _service(request: Request, session: AsyncSession) -> AuthService:
    return AuthService(session, request.app.state.settings, request.app.state.redis)


def _set_csrf_cookie(response: Response, settings: Settings, csrf_token: str) -> None:
    max_age = settings.refresh_token_ttl_days * 24 * 60 * 60
    response.set_cookie(
        key=settings.auth_csrf_cookie_name,
        value=csrf_token,
        max_age=max_age,
        httponly=False,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
    )


def _set_auth_cookies(response: Response, settings: Settings, tokens: IssuedTokens) -> str:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    cookie_path = f"{settings.api_v1_prefix}/auth"
    max_age = settings.refresh_token_ttl_days * 24 * 60 * 60
    response.set_cookie(
        key=settings.auth_refresh_cookie_name,
        value=tokens.refresh_token,
        max_age=max_age,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path=cookie_path,
    )
    # Double-submit CSRF cookie: readable by the SPA, mirrored in X-CSRF-Token.
    from ask_ai.modules.auth.security import generate_csrf_token

    csrf_token = generate_csrf_token(settings, tokens.refresh_token)
    _set_csrf_cookie(response, settings, csrf_token)
    return csrf_token


def _clear_auth_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.auth_refresh_cookie_name,
        path=f"{settings.api_v1_prefix}/auth",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
    )
    response.delete_cookie(
        key=settings.auth_csrf_cookie_name,
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=False,
        samesite=settings.auth_cookie_samesite,
    )


def _token_response(user: User, tokens: IssuedTokens, csrf_token: str) -> TokenResponse:
    return TokenResponse(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        csrf_token=csrf_token,
        user=UserResponse(**user_response_values(user)),
    )


async def _apply_login_limits(request: Request, email: str, *, registration: bool) -> None:
    ip = client_ip(request)
    namespace = "register" if registration else "login"
    ip_limit = 5 if registration else 10
    email_limit = 3 if registration else 8
    await enforce_rate_limit(
        request,
        bucket=f"{namespace}:ip:{ip}",
        limit=ip_limit,
        window_seconds=600,
    )
    email_hash = hashlib.sha256(email.casefold().encode("utf-8")).hexdigest()
    await enforce_rate_limit(
        request,
        bucket=f"{namespace}:email:{email_hash}",
        limit=email_limit,
        window_seconds=600,
    )


@router.get("/providers", response_model=AuthProvidersResponse)
async def list_auth_providers(request: Request) -> AuthProvidersResponse:
    oauth_clients: dict[str, Any] = request.app.state.oauth_clients
    return AuthProvidersResponse(providers=sorted(oauth_clients.keys()))


@router.get("/csrf", response_model=CsrfTokenResponse)
async def get_csrf_token(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CsrfTokenResponse:
    """Rehydrate an in-memory SPA CSRF token after a page reload.

    The endpoint requires a still-active HttpOnly refresh cookie. CORS must be
    restricted to trusted frontend origins; the response is never cacheable.
    """
    settings: Settings = request.app.state.settings
    raw_refresh = request.cookies.get(settings.auth_refresh_cookie_name)
    has_active_session = (
        await _service(request, session).has_active_refresh_session(raw_refresh)
        if raw_refresh
        else False
    )
    if not has_active_session:
        raise ApplicationError(
            code="invalid_refresh_token",
            message="The session is invalid or has expired. Please sign in again.",
            status_code=401,
        )

    from ask_ai.modules.auth.security import generate_csrf_token

    csrf_token = generate_csrf_token(settings, raw_refresh)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    _set_csrf_cookie(response, settings, csrf_token)
    return CsrfTokenResponse(csrf_token=csrf_token)


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TokenResponse:
    await _apply_login_limits(request, str(payload.email), registration=True)
    settings: Settings = request.app.state.settings
    user, tokens = await _service(request, session).register(
        email=str(payload.email),
        password=payload.password.get_secret_value(),
        display_name=payload.display_name,
    )
    csrf_token = _set_auth_cookies(response, settings, tokens)
    return _token_response(user, tokens, csrf_token)


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TokenResponse:
    await _apply_login_limits(request, str(payload.email), registration=False)
    settings: Settings = request.app.state.settings
    user, tokens = await _service(request, session).login(
        email=str(payload.email),
        password=payload.password.get_secret_value(),
    )
    csrf_token = _set_auth_cookies(response, settings, tokens)
    return _token_response(user, tokens, csrf_token)


@router.post("/refresh", response_model=TokenResponse, dependencies=[Depends(require_csrf)])
async def refresh(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TokenResponse:
    settings: Settings = request.app.state.settings
    raw_token = request.cookies.get(settings.auth_refresh_cookie_name)
    if not raw_token:
        raise ApplicationError(
            code="invalid_refresh_token",
            message="The session is invalid or has expired. Please sign in again.",
            status_code=401,
        )
    user, tokens = await _service(request, session).refresh(raw_token)
    csrf_token = _set_auth_cookies(response, settings, tokens)
    return _token_response(user, tokens, csrf_token)


@router.post("/logout", status_code=204, dependencies=[Depends(require_csrf)])
async def logout(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    settings: Settings = request.app.state.settings
    await _service(request, session).logout(
        request.cookies.get(settings.auth_refresh_cookie_name)
    )
    _clear_auth_cookies(response, settings)
    response.status_code = 204
    return response


@router.get("/me", response_model=UserResponse)
async def me(user: Annotated[User, Depends(get_current_user)]) -> UserResponse:
    return UserResponse(**user_response_values(user))


@router.get("/{provider}/login")
async def oauth_login(provider: str, request: Request) -> RedirectResponse:
    oauth_clients: dict[str, Any] = request.app.state.oauth_clients
    client = oauth_clients.get(provider)
    if client is None:
        raise ApplicationError(
            code="oauth_provider_unavailable",
            message="This sign-in provider is not configured.",
            status_code=503,
        )
    settings: Settings = request.app.state.settings
    redirect_uri = {
        "google": settings.google_redirect_uri,
        "apple": settings.apple_redirect_uri,
    }[provider]
    await enforce_rate_limit(
        request,
        bucket=f"oauth:start:{provider}:{client_ip(request)}",
        limit=10,
        window_seconds=600,
    )
    if provider == "apple":
        return await client.authorize_redirect(
            request,
            redirect_uri,
            response_mode="form_post",
        )
    return await client.authorize_redirect(request, redirect_uri)


async def _complete_oauth_callback(
    provider: str,
    request: Request,
    session: AsyncSession,
) -> RedirectResponse:
    settings: Settings = request.app.state.settings
    frontend_callback = settings.frontend_auth_callback_url
    failure_url = f"{frontend_callback}#error=oauth_failed"
    oauth_clients: dict[str, Any] = request.app.state.oauth_clients
    client = oauth_clients.get(provider)
    if client is None:
        raise ApplicationError(
            code="oauth_provider_unavailable",
            message="This sign-in provider is not configured.",
            status_code=503,
        )

    try:
        callback_request = await build_oauth_callback_request(provider, request)
        if callback_request.query_params.get("error"):
            raise ApplicationError(
                code="oauth_provider_rejected",
                message="The identity provider could not complete sign-in.",
                status_code=401,
            )
        token = await client.authorize_access_token(callback_request)
        userinfo = token.get("userinfo")
        if userinfo is None:
            raise ApplicationError(
                code="invalid_provider_identity",
                message="The identity provider did not return a validated identity.",
                status_code=401,
            )
        claims = dict(userinfo)
        user = await _service(request, session).login_with_oidc_claims(
            provider=provider,
            claims=claims,
        )
        code = await _service(request, session).create_oauth_exchange_code(user)
    except ApplicationError as exc:
        logger.warning("oidc_callback_rejected", provider=provider, error_code=exc.code)
        return RedirectResponse(
            failure_url,
            status_code=303,
            headers={
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "Referrer-Policy": "no-referrer",
            },
        )
    except (OAuthError, JoseError, HTTPX2Error, KeyError, ValueError, TypeError) as exc:
        logger.warning("oidc_callback_rejected", provider=provider, error_type=type(exc).__name__)
        return RedirectResponse(
            failure_url,
            status_code=303,
            headers={
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "Referrer-Policy": "no-referrer",
            },
        )

    # The short-lived one-time code is carried in the URL fragment, not the query string.
    # Fragments are not sent to the web server in HTTP requests or Referer headers.
    success_url = f"{frontend_callback}#code={quote(code, safe='')}"
    return RedirectResponse(
        success_url,
        status_code=303,
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer",
        },
    )


@router.get("/google/callback", include_in_schema=True)
async def google_oauth_callback(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RedirectResponse:
    return await _complete_oauth_callback("google", request, session)


@router.post("/apple/callback", include_in_schema=True)
async def apple_oauth_callback(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RedirectResponse:
    return await _complete_oauth_callback("apple", request, session)


@router.post("/oauth/exchange", response_model=TokenResponse)
async def exchange_oauth_code(
    payload: OAuthExchangeRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TokenResponse:
    settings: Settings = request.app.state.settings
    user, tokens = await _service(request, session).exchange_oauth_code(payload.code)
    csrf_token = _set_auth_cookies(response, settings, tokens)
    return _token_response(user, tokens, csrf_token)
