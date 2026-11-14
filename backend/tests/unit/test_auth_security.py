from uuid import uuid4

import jwt
import pytest
from pydantic import ValidationError

from ask_ai.core.config import Settings
from ask_ai.modules.auth.schemas import RegisterRequest
from ask_ai.modules.auth.security import (
    create_access_token,
    decode_access_token,
    generate_csrf_token,
    verify_csrf_token,
)


def test_access_token_has_expected_subject_and_family() -> None:
    settings = Settings(
        app_env="test",
        secret_key="unit-test-secret-with-at-least-thirty-two-bytes-long",
    )
    user_id = uuid4()
    family_id = uuid4()
    token = create_access_token(user_id=user_id, family_id=family_id, settings=settings)
    assert decode_access_token(token, settings) == (user_id, family_id)


def test_access_token_rejects_wrong_signing_key() -> None:
    settings = Settings(
        app_env="test",
        secret_key="unit-test-secret-with-at-least-thirty-two-bytes-long",
    )
    other_settings = Settings(
        app_env="test",
        secret_key="different-test-secret-with-at-least-thirty-two-bytes",
    )
    token = create_access_token(user_id=uuid4(), family_id=uuid4(), settings=settings)
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, other_settings)


def test_csrf_token_is_signed_and_tamper_evident() -> None:
    settings = Settings(
        app_env="test",
        secret_key="unit-test-secret-with-at-least-thirty-two-bytes-long",
    )
    refresh_token = "test-refresh-token-which-is-long-and-random"
    token = generate_csrf_token(settings, refresh_token)
    assert verify_csrf_token(token, settings, refresh_token)
    assert not verify_csrf_token(token + "x", settings, refresh_token)
    assert not verify_csrf_token(token, settings, "another-session-refresh-token")
    other_settings = Settings(
        app_env="test",
        secret_key="different-test-secret-with-at-least-thirty-two-bytes",
    )
    assert not verify_csrf_token(token, other_settings, refresh_token)


@pytest.mark.parametrize("password", ["short", "", "null\x00character", "a" * 129])
def test_registration_rejects_weak_or_oversized_passwords(password: str) -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(email="person@example.com", password=password)


def test_registration_accepts_long_passphrase() -> None:
    payload = RegisterRequest(
        email="Person@Example.com",
        password="this is a valid long passphrase 123",
    )
    assert payload.email == "Person@example.com"
