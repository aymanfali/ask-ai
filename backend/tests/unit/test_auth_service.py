from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ask_ai.core.config import Settings
from ask_ai.core.errors import ApplicationError
from ask_ai.database.base import Base
from ask_ai.modules.auth.models import AuthIdentity, RefreshSession, User
from ask_ai.modules.auth.security import (
    decode_access_token,
    get_password_hasher,
    hash_refresh_token,
)
from ask_ai.modules.auth.service import AuthService


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expires: dict[str, int] = {}
        self.counters: dict[str, int] = defaultdict(int)

    async def set(self, key: str, value: str, *, ex: int, nx: bool = False) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.expires[key] = ex
        return True

    async def getdel(self, key: str) -> str | None:
        return self.values.pop(key, None)

    async def eval(self, _script: str, _numkeys: int, key: str, _window: int) -> list[int]:
        self.counters[key] += 1
        return [self.counters[key], 60]


@pytest.fixture
async def auth_context():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    redis = FakeRedis()
    settings = Settings(
        app_env="test",
        secret_key="unit-test-secret-with-at-least-thirty-two-bytes-long",
        access_token_ttl_minutes=10,
        refresh_token_ttl_days=30,
        refresh_session_absolute_ttl_days=90,
    )
    try:
        yield factory, redis, settings
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_register_hashes_password_and_only_persists_refresh_token_hash(auth_context) -> None:
    factory, redis, settings = auth_context
    async with factory() as session:
        service = AuthService(session, settings, redis)
        user, tokens = await service.register(
            email="Ayman.Example@example.com",
            password="a-very-long-password-for-tests",
            display_name="  Ayman Fahd  ",
        )

        assert user.email == "ayman.example@example.com"
        assert user.display_name == "Ayman Fahd"
        assert user.password_hash is not None
        assert get_password_hasher().verify("a-very-long-password-for-tests", user.password_hash)
        assert tokens.refresh_token not in user.password_hash

        stored = await session.scalar(
            select(RefreshSession).where(RefreshSession.user_id == user.id)
        )
        assert stored is not None
        assert stored.token_hash == hash_refresh_token(tokens.refresh_token)
        assert stored.token_hash != tokens.refresh_token
        assert stored.rotated_at is None


@pytest.mark.asyncio
async def test_login_uses_generic_error_for_unknown_or_wrong_password(auth_context) -> None:
    factory, redis, settings = auth_context
    async with factory() as session:
        service = AuthService(session, settings, redis)
        with pytest.raises(ApplicationError) as unknown:
            await service.login(email="unknown@example.com", password="wrong-password")
        assert unknown.value.code == "invalid_credentials"

        await service.register(
            email="known@example.com",
            password="correct-password-123",
            display_name=None,
        )
        with pytest.raises(ApplicationError) as wrong:
            await service.login(email="known@example.com", password="wrong-password")
        assert wrong.value.code == "invalid_credentials"


@pytest.mark.asyncio
async def test_refresh_rotates_token_and_reuse_revokes_family(auth_context) -> None:
    factory, redis, settings = auth_context
    async with factory() as session:
        service = AuthService(session, settings, redis)
        user, original = await service.register(
            email="rotate@example.com",
            password="correct-password-123",
            display_name=None,
        )
        _, rotated = await service.refresh(original.refresh_token)
        assert rotated.refresh_token != original.refresh_token
        decoded_user_id, family_id = decode_access_token(rotated.access_token, settings)
        assert decoded_user_id == user.id

        with pytest.raises(ApplicationError) as reused:
            await service.refresh(original.refresh_token)
        assert reused.value.code == "invalid_refresh_token"

        active_count = await session.scalar(
            select(func.count(RefreshSession.id)).where(
                RefreshSession.family_id == family_id,
                RefreshSession.rotated_at.is_(None),
                RefreshSession.revoked_at.is_(None),
            )
        )
        assert active_count == 0


@pytest.mark.asyncio
async def test_logout_revokes_current_device_family(auth_context) -> None:
    factory, redis, settings = auth_context
    async with factory() as session:
        service = AuthService(session, settings, redis)
        _, tokens = await service.register(
            email="logout@example.com",
            password="correct-password-123",
            display_name=None,
        )
        await service.logout(tokens.refresh_token)
        result = await session.scalar(
            select(RefreshSession).where(
                RefreshSession.token_hash == hash_refresh_token(tokens.refresh_token)
            )
        )
        assert result is not None
        assert result.revoked_at is not None
        with pytest.raises(ApplicationError):
            await service.refresh(tokens.refresh_token)


@pytest.mark.asyncio
async def test_oauth_requires_verified_email_for_first_login(auth_context) -> None:
    factory, redis, settings = auth_context
    async with factory() as session:
        service = AuthService(session, settings, redis)
        with pytest.raises(ApplicationError) as error:
            await service.login_with_oidc_claims(
                provider="google",
                claims={
                    "sub": "google-subject-1",
                    "email": "person@example.com",
                    "email_verified": False,
                },
            )
        assert error.value.code == "verified_email_required"


@pytest.mark.asyncio
async def test_oauth_identity_creates_verified_user_and_existing_subject_needs_no_email(
    auth_context,
) -> None:
    factory, redis, settings = auth_context
    async with factory() as session:
        service = AuthService(session, settings, redis)
        user = await service.login_with_oidc_claims(
            provider="google",
            claims={
                "sub": "google-subject-1",
                "email": "Person@Example.com",
                "email_verified": True,
                "name": "Example Person",
            },
        )
        assert user.email == "person@example.com"
        assert user.email_verified_at is not None

        identity = await session.scalar(
            select(AuthIdentity).where(
                AuthIdentity.provider == "google",
                AuthIdentity.provider_subject == "google-subject-1",
            )
        )
        assert identity is not None
        assert identity.user_id == user.id

        same_user = await service.login_with_oidc_claims(
            provider="google",
            claims={"sub": "google-subject-1"},
        )
        assert same_user.id == user.id


@pytest.mark.asyncio
async def test_oauth_exchange_code_is_single_use(auth_context) -> None:
    factory, redis, settings = auth_context
    async with factory() as session:
        service = AuthService(session, settings, redis)
        user = User(email="oauth-exchange@example.com", is_active=True)
        session.add(user)
        await session.commit()

        code = await service.create_oauth_exchange_code(user)
        exchanged_user, tokens = await service.exchange_oauth_code(code)
        assert exchanged_user.id == user.id
        assert tokens.refresh_token

        with pytest.raises(ApplicationError) as replay:
            await service.exchange_oauth_code(code)
        assert replay.value.code == "invalid_oauth_code"


@pytest.mark.asyncio
async def test_verified_oidc_email_does_not_auto_link_unverified_local_account(
    auth_context,
) -> None:
    factory, redis, settings = auth_context
    async with factory() as session:
        local_user = User(
            email="claimed@example.com",
            password_hash="existing-local-password-hash",
            is_active=True,
        )
        session.add(local_user)
        await session.commit()
        local_user_id = local_user.id
        service = AuthService(session, settings, redis)

        with pytest.raises(ApplicationError) as error:
            await service.login_with_oidc_claims(
                provider="google",
                claims={
                    "sub": "google-subject-claimed",
                    "email": "claimed@example.com",
                    "email_verified": True,
                },
            )

        assert error.value.code == "account_link_required"
        identity = await session.scalar(
            select(AuthIdentity).where(
                AuthIdentity.provider == "google",
                AuthIdentity.provider_subject == "google-subject-claimed",
            )
        )
        assert identity is None
        persisted_user = await session.get(User, local_user_id)
        assert persisted_user is not None

@pytest.mark.asyncio
async def test_csrf_bootstrap_requires_active_refresh_session(auth_context) -> None:
    factory, redis, settings = auth_context
    async with factory() as session:
        service = AuthService(session, settings, redis)
        _, tokens = await service.register(
            email="csrf-bootstrap@example.com",
            password="correct-password-123",
            display_name=None,
        )
        assert await service.has_active_refresh_session(tokens.refresh_token)
        await service.logout(tokens.refresh_token)
        assert not await service.has_active_refresh_session(tokens.refresh_token)


@pytest.mark.asyncio
async def test_oauth_identity_links_an_already_verified_local_account(auth_context) -> None:
    factory, redis, settings = auth_context
    async with factory() as session:
        local_user = User(
            email="verified-local@example.com",
            password_hash="existing-local-password-hash",
            is_active=True,
            email_verified_at=datetime.now(UTC),
        )
        session.add(local_user)
        await session.commit()

        service = AuthService(session, settings, redis)
        linked_user = await service.login_with_oidc_claims(
            provider="google",
            claims={
                "sub": "google-subject-verified-link",
                "email": "verified-local@example.com",
                "email_verified": True,
            },
        )

        assert linked_user.id == local_user.id
        identity = await session.scalar(
            select(AuthIdentity).where(
                AuthIdentity.provider == "google",
                AuthIdentity.provider_subject == "google-subject-verified-link",
            )
        )
        assert identity is not None
        assert identity.user_id == local_user.id


@pytest.mark.asyncio
async def test_refresh_rejects_expired_refresh_session(auth_context) -> None:
    factory, redis, settings = auth_context
    async with factory() as session:
        service = AuthService(session, settings, redis)
        _, tokens = await service.register(
            email="expired-refresh@example.com",
            password="correct-password-123",
            display_name=None,
        )
        refresh_session = await session.scalar(
            select(RefreshSession).where(
                RefreshSession.token_hash == hash_refresh_token(tokens.refresh_token)
            )
        )
        assert refresh_session is not None
        refresh_session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

        with pytest.raises(ApplicationError) as error:
            await service.refresh(tokens.refresh_token)
        assert error.value.code == "invalid_refresh_token"
        assert refresh_session.revoked_at is not None


@pytest.mark.asyncio
async def test_registration_can_be_disabled(auth_context) -> None:
    factory, redis, settings = auth_context
    disabled_settings = settings.model_copy(update={"auth_allow_registration": False})
    async with factory() as session:
        service = AuthService(session, disabled_settings, redis)
        with pytest.raises(ApplicationError) as error:
            await service.register(
                email="registration-disabled@example.com",
                password="correct-password-123",
                display_name=None,
            )
        assert error.value.code == "registration_disabled"


def test_registration_service_enforces_password_policy_without_http_schema() -> None:
    AuthService._validate_registration_password("a-valid-passphrase-with-123")

    for invalid_password in (
        "short",
        "x" * 129,
        "null\x00byte-password",
        "é" * 600,
    ):
        with pytest.raises(ApplicationError) as error:
            AuthService._validate_registration_password(invalid_password)
        assert error.value.code == "invalid_password"
