from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from email_validator import EmailNotValidError, validate_email
from redis.exceptions import RedisError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ask_ai.core.config import Settings
from ask_ai.core.errors import ApplicationError
from ask_ai.modules.auth.models import AuthIdentity, RefreshSession, User
from ask_ai.modules.auth.security import (
    create_access_token,
    generate_refresh_token,
    hash_oauth_exchange_code,
    hash_password,
    hash_refresh_token,
    verify_password,
)


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings, redis: Any) -> None:
        self.session = session
        self.settings = settings
        self.redis = redis

    @staticmethod
    def normalize_email(email: str) -> str:
        try:
            normalized = validate_email(email, check_deliverability=False).normalized
        except EmailNotValidError as exc:
            raise ApplicationError(
                code="invalid_email", message="Enter a valid email address.", status_code=422
            ) from exc
        # Ask AI treats email identifiers case-insensitively for login and uniqueness.
        return normalized.casefold()

    @staticmethod
    def _validate_registration_password(password: str) -> None:
        if (
            len(password) < 12
            or len(password) > 128
            or len(password.encode("utf-8")) > 1024
            or "\x00" in password
        ):
            raise ApplicationError(
                code="invalid_password",
                message=(
                    "Password must contain 12 to 128 characters, must not exceed "
                    "1024 UTF-8 bytes, and must not contain a null character."
                ),
                status_code=422,
            )

    async def register(
        self,
        *,
        email: str,
        password: str,
        display_name: str | None,
    ) -> tuple[User, IssuedTokens]:
        if not self.settings.auth_allow_registration:
            raise ApplicationError(
                code="registration_disabled",
                message="New account registration is currently unavailable.",
                status_code=403,
            )
        self._validate_registration_password(password)
        normalized_email = self.normalize_email(email)
        existing = await self.session.scalar(select(User.id).where(User.email == normalized_email))
        if existing is not None:
            raise ApplicationError(
                code="email_unavailable",
                message="An account with this email address cannot be created.",
                status_code=409,
            )

        password_hash = await hash_password(password)
        user = User(
            email=normalized_email,
            password_hash=password_hash,
            display_name=display_name.strip() if display_name else None,
            is_active=True,
        )
        self.session.add(user)
        try:
            await self.session.flush()
            # Registration is a complete sign-in operation: create the first
            # refresh-token family in the same transaction as the user row.
            tokens = await self._create_session(user)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ApplicationError(
                code="email_unavailable",
                message="An account with this email address cannot be created.",
                status_code=409,
            ) from exc
        except Exception:
            await self.session.rollback()
            raise
        return user, tokens

    async def has_active_refresh_session(self, raw_token: str) -> bool:
        """Return whether the supplied refresh cookie identifies an active session."""
        current = await self.session.scalar(
            select(RefreshSession)
            .join(User, User.id == RefreshSession.user_id)
            .where(
                RefreshSession.token_hash == hash_refresh_token(raw_token),
                RefreshSession.rotated_at.is_(None),
                RefreshSession.revoked_at.is_(None),
                User.is_active.is_(True),
            )
        )
        if current is None:
            return False
        now = datetime.now(UTC)
        expires_at = current.expires_at
        family_expires_at = current.family_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if family_expires_at.tzinfo is None:
            family_expires_at = family_expires_at.replace(tzinfo=UTC)
        return expires_at > now and family_expires_at > now

    async def login(self, *, email: str, password: str) -> tuple[User, IssuedTokens]:
        normalized_email = self.normalize_email(email)
        user = await self.session.scalar(select(User).where(User.email == normalized_email))
        valid_password = await verify_password(password, user.password_hash if user else None)
        if user is None or not valid_password or not user.is_active:
            await self.session.rollback()
            raise ApplicationError(
                code="invalid_credentials",
                message="The email address or password is incorrect.",
                status_code=401,
            )

        try:
            tokens = await self._create_session(user)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return user, tokens

    async def refresh(self, raw_token: str) -> tuple[User, IssuedTokens]:
        token_hash = hash_refresh_token(raw_token)
        result = await self.session.execute(
            select(RefreshSession)
            .where(RefreshSession.token_hash == token_hash)
            .with_for_update()
        )
        current = result.scalar_one_or_none()
        if current is None:
            await self.session.rollback()
            raise self._invalid_refresh()

        now = datetime.now(UTC)
        if current.rotated_at is not None:
            # Reuse of a consumed token is treated as compromise: revoke the whole family.
            await self.session.execute(
                update(RefreshSession)
                .where(
                    RefreshSession.family_id == current.family_id,
                    RefreshSession.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            await self.session.commit()
            raise self._invalid_refresh()

        expires_at = current.expires_at
        family_expires_at = current.family_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if family_expires_at.tzinfo is None:
            family_expires_at = family_expires_at.replace(tzinfo=UTC)
        if current.revoked_at is not None or expires_at <= now or family_expires_at <= now:
            if current.revoked_at is None:
                current.revoked_at = now
                await self.session.commit()
            else:
                await self.session.rollback()
            raise self._invalid_refresh()

        user = await self.session.get(User, current.user_id)
        if user is None or not user.is_active:
            await self.session.execute(
                update(RefreshSession)
                .where(
                    RefreshSession.family_id == current.family_id,
                    RefreshSession.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            await self.session.commit()
            raise self._invalid_refresh()

        refresh_token = generate_refresh_token()
        replacement = RefreshSession(
            user_id=current.user_id,
            family_id=current.family_id,
            token_hash=hash_refresh_token(refresh_token),
            expires_at=min(
                now + timedelta(days=self.settings.refresh_token_ttl_days),
                family_expires_at,
            ),
            family_expires_at=family_expires_at,
        )
        self.session.add(replacement)
        await self.session.flush()
        current.rotated_at = now
        current.replaced_by_id = replacement.id
        access_token = create_access_token(
            user_id=user.id,
            family_id=current.family_id,
            settings=self.settings,
        )
        await self.session.commit()
        return user, IssuedTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self.settings.access_token_ttl_minutes * 60,
        )

    async def logout(self, raw_token: str | None) -> None:
        if not raw_token:
            await self.session.rollback()
            return
        current = await self.session.scalar(
            select(RefreshSession)
            .where(RefreshSession.token_hash == hash_refresh_token(raw_token))
            .with_for_update()
        )
        if current is None:
            await self.session.rollback()
            return
        now = datetime.now(UTC)
        await self.session.execute(
            update(RefreshSession)
            .where(
                RefreshSession.family_id == current.family_id,
                RefreshSession.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        await self.session.commit()

    async def create_oauth_exchange_code(self, user: User) -> str:
        code = secrets.token_urlsafe(48)
        key = f"auth:oauth:exchange:{hash_oauth_exchange_code(code)}"
        try:
            stored = await self.redis.set(
                key,
                str(user.id),
                ex=self.settings.oauth_exchange_code_ttl_seconds,
                nx=True,
            )
        except RedisError as exc:
            raise ApplicationError(
                code="oauth_exchange_unavailable",
                message="Authentication is temporarily unavailable. Please try again.",
                status_code=503,
            ) from exc
        if not stored:
            raise ApplicationError(
                code="oauth_exchange_unavailable",
                message="Authentication could not be completed. Please try again.",
                status_code=503,
            )
        return code

    async def exchange_oauth_code(self, code: str) -> tuple[User, IssuedTokens]:
        key = f"auth:oauth:exchange:{hash_oauth_exchange_code(code)}"
        try:
            user_id_value = await self.redis.getdel(key)
        except RedisError as exc:
            raise ApplicationError(
                code="oauth_exchange_unavailable",
                message="Authentication is temporarily unavailable. Please try again.",
                status_code=503,
            ) from exc
        if not user_id_value:
            raise ApplicationError(
                code="invalid_oauth_code",
                message="The sign-in code is invalid or has expired.",
                status_code=401,
            )
        try:
            user_id = UUID(user_id_value)
        except (ValueError, TypeError) as exc:
            raise ApplicationError(
                code="invalid_oauth_code",
                message="The sign-in code is invalid or has expired.",
                status_code=401,
            ) from exc
        user = await self.session.get(User, user_id)
        if user is None or not user.is_active:
            await self.session.rollback()
            raise ApplicationError(
                code="invalid_oauth_code",
                message="The sign-in code is invalid or has expired.",
                status_code=401,
            )
        tokens = await self._create_session(user)
        await self.session.commit()
        return user, tokens

    async def login_with_oidc_claims(
        self,
        *,
        provider: str,
        claims: dict[str, Any],
    ) -> User:
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject or len(subject) > 255:
            raise ApplicationError(
                code="invalid_provider_identity",
                message="The identity provider returned an invalid account identifier.",
                status_code=401,
            )

        identity = await self.session.scalar(
            select(AuthIdentity).where(
                AuthIdentity.provider == provider,
                AuthIdentity.provider_subject == subject,
            )
        )
        if identity is not None:
            user = await self.session.get(User, identity.user_id)
            if user is None or not user.is_active:
                await self.session.rollback()
                raise ApplicationError(
                    code="account_unavailable",
                    message="This account is unavailable.",
                    status_code=403,
                )
            await self.session.commit()
            return user

        email_claim = claims.get("email")
        verified_claim = claims.get("email_verified")
        email_verified = verified_claim is True or (
            isinstance(verified_claim, str) and verified_claim.casefold() == "true"
        )
        if not isinstance(email_claim, str) or not email_claim or not email_verified:
            await self.session.rollback()
            raise ApplicationError(
                code="verified_email_required",
                message=(
                    "The identity provider must supply a verified email address "
                    "for first-time sign-in."
                ),
                status_code=403,
            )

        normalized_email = self.normalize_email(email_claim)
        user = await self.session.scalar(select(User).where(User.email == normalized_email))
        if user is not None and not user.is_active:
            await self.session.rollback()
            raise ApplicationError(
                code="account_unavailable",
                message="This account is unavailable.",
                status_code=403,
            )
        if user is not None and user.email_verified_at is None:
            # Do not auto-link a verified IdP identity to an unverified local
            # account. Otherwise an attacker could pre-register another person's
            # email and retain password access after that person signs in with OIDC.
            await self.session.rollback()
            raise ApplicationError(
                code="account_link_required",
                message=(
                    "An account already exists with this email. Sign in using the "
                    "existing account; automatic linking is not permitted."
                ),
                status_code=409,
            )
        if user is None:
            display_name_claim = claims.get("name") or claims.get("given_name")
            display_name = (
                display_name_claim.strip()[:120]
                if isinstance(display_name_claim, str) and display_name_claim.strip()
                else None
            )
            user = User(
                email=normalized_email,
                password_hash=None,
                display_name=display_name,
                is_active=True,
                email_verified_at=datetime.now(UTC),
            )
            self.session.add(user)
            await self.session.flush()

        identity = AuthIdentity(
            user_id=user.id,
            provider=provider,
            provider_subject=subject,
            email_at_provider=normalized_email,
        )
        self.session.add(identity)
        try:
            await self.session.flush()
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ApplicationError(
                code="identity_already_linked",
                message=(
                    "This identity is already linked to another account. "
                    "Sign in using its existing method."
                ),
                status_code=409,
            ) from exc
        except Exception:
            await self.session.rollback()
            raise
        return user

    async def _create_session(self, user: User) -> IssuedTokens:
        now = datetime.now(UTC)
        family_id = uuid4()
        refresh_token = generate_refresh_token()
        family_expires_at = now + timedelta(days=self.settings.refresh_session_absolute_ttl_days)
        refresh_session = RefreshSession(
            user_id=user.id,
            family_id=family_id,
            token_hash=hash_refresh_token(refresh_token),
            expires_at=min(
                now + timedelta(days=self.settings.refresh_token_ttl_days), family_expires_at
            ),
            family_expires_at=family_expires_at,
        )
        self.session.add(refresh_session)
        return IssuedTokens(
            access_token=create_access_token(
                user_id=user.id,
                family_id=family_id,
                settings=self.settings,
            ),
            refresh_token=refresh_token,
            expires_in=self.settings.access_token_ttl_minutes * 60,
        )

    @staticmethod
    def _invalid_refresh() -> ApplicationError:
        return ApplicationError(
            code="invalid_refresh_token",
            message="The session is invalid or has expired. Please sign in again.",
            status_code=401,
        )
