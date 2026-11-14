import pytest

from ask_ai.core.config import Settings


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        app_env="test",
        app_debug=False,
        secret_key="test-only-secret-that-is-long-enough-for-unit-tests",
        cors_origins=["http://localhost:5173"],
    )
