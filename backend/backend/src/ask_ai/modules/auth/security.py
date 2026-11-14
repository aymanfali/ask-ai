from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from uuid import UUID

import jwt
from pwdlib import PasswordHash
from starlette.concurrency import run_in_threadpool

from ask_ai.core.config import Settings
from ask_ai.core.security_keys import derive_application_key


@lru_cache(maxsize=1)
def get_password_hasher() -> PasswordHash:
    # pwdlib's recommended hasher selects Argon2id when the argon2 extra is installed.
    return PasswordHash.recommended()


@lru_cache(maxsize=1)
def get_dummy_password_hash() -> str:
    # Used for unknown accounts so login still performs a password hash verification.
    return get_password_hasher().hash("not-a-real-user-password-for-timing-equalization")


async def hash_password(password: str) -> str:
    return await run_in_threadpool(get_password_hasher().hash, password)


async def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        has_stored_hash = bool(password_hash)
        candidate_hash = (
            password_hash
            if has_stored_hash
            else await run_in_threadpool(get_dummy_password_hash)
        )
        valid = await run_in_threadpool(get_password_hasher().verify, password, candidate_hash)
    except Exception:
        return False
    return bool(valid and has_stored_hash)


def create_access_token(*, user_id: UUID, family_id: UUID, settings: Settings) -> str:
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.access_token_ttl_minutes)
    payload = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": str(user_id),
        "sid": str(family_id),
        "jti": secrets.token_urlsafe(16),
        "token_type": "access",
        "iat": now,
        "nbf": now,
        "exp": expires_at,
    }
    return jwt.encode(
        payload,
        derive_application_key(settings, "access-jwt"),
        algorithm="HS256",
    )


def decode_access_token(token: str, settings: Settings) -> tuple[UUID, UUID]:
    payload = jwt.decode(
        token,
        derive_application_key(settings, "access-jwt"),
        algorithms=["HS256"],
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        options={"require": ["exp", "iat", "nbf", "iss", "aud", "sub", "jti", "sid"]},
        leeway=30,
    )
    if payload.get("token_type") != "access":
        raise jwt.InvalidTokenError("Wrong token type")
    return UUID(payload["sub"]), UUID(payload["sid"])


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_csrf_token(settings: Settings, refresh_token: str) -> str:
    nonce = secrets.token_urlsafe(32)
    session_binding = hash_refresh_token(refresh_token)
    signature = hmac.new(
        derive_application_key(settings, "csrf"),
        f"{session_binding}.{nonce}".encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{nonce}.{signature}"


def verify_csrf_token(token: str, settings: Settings, refresh_token: str | None) -> bool:
    if not refresh_token:
        return False
    try:
        nonce, supplied_signature = token.rsplit(".", 1)
        if not nonce or len(supplied_signature) != 64:
            return False
        session_binding = hash_refresh_token(refresh_token)
        expected_signature = hmac.new(
            derive_application_key(settings, "csrf"),
            f"{session_binding}.{nonce}".encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
    except (ValueError, UnicodeEncodeError):
        return False
    return hmac.compare_digest(supplied_signature, expected_signature)


def hash_oauth_exchange_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()
