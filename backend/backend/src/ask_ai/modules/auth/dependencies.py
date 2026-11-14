from __future__ import annotations

import hmac
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ask_ai.core.config import Settings
from ask_ai.core.errors import ApplicationError
from ask_ai.database.session import get_db_session
from ask_ai.modules.auth.models import RefreshSession, User
from ask_ai.modules.auth.security import decode_access_token, verify_csrf_token

bearer_scheme = HTTPBearer(auto_error=False, scheme_name="AccessToken")


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> User:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise ApplicationError(
            code="authentication_required",
            message="A valid access token is required.",
            status_code=401,
        )
    settings: Settings = request.app.state.settings
    try:
        user_id, family_id = decode_access_token(credentials.credentials, settings)
    except (jwt.InvalidTokenError, ValueError, KeyError, TypeError) as exc:
        raise ApplicationError(
            code="invalid_access_token",
            message="The access token is invalid or has expired.",
            status_code=401,
        ) from exc

    now = datetime.now(UTC)
    user = await session.scalar(
        select(User)
        .join(RefreshSession, RefreshSession.user_id == User.id)
        .where(
            User.id == user_id,
            User.is_active.is_(True),
            RefreshSession.family_id == family_id,
            RefreshSession.rotated_at.is_(None),
            RefreshSession.revoked_at.is_(None),
            RefreshSession.expires_at > now,
            RefreshSession.family_expires_at > now,
        )
    )
    if user is None:
        raise ApplicationError(
            code="account_unavailable",
            message="This account is unavailable.",
            status_code=401,
        )
    return user


async def require_csrf(request: Request) -> None:
    settings: Settings = request.app.state.settings
    cookie_value = request.cookies.get(settings.auth_csrf_cookie_name)
    header_value = request.headers.get("X-CSRF-Token")
    refresh_token = request.cookies.get(settings.auth_refresh_cookie_name)
    try:
        values_match = bool(
            cookie_value
            and header_value
            and hmac.compare_digest(cookie_value, header_value)
        )
    except TypeError:
        values_match = False
    if (
        not values_match
        or not verify_csrf_token(cookie_value or "", settings, refresh_token)
    ):
        raise ApplicationError(
            code="csrf_validation_failed",
            message="The CSRF token is missing or invalid.",
            status_code=403,
        )


def user_response_values(user: User) -> dict[str, object]:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "email_verified": user.email_verified_at is not None,
        "created_at": user.created_at,
    }
