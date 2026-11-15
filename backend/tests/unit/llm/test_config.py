from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ask_ai.core.config import Settings
from ask_ai.modules.llm.config import LLMModelConfig, PricingVersionConfig


def _provider(provider_id: str = "openai") -> dict[str, object]:
    return {
        "id": provider_id,
        "name": "Test Provider",
        "type": "openai_compatible",
        "api_key": "provider-secret-test-value",
        "base_url": "https://api.example.test/v1",
    }


def _model(model_id: str = "openai:test-model", provider_id: str = "openai") -> dict[str, object]:
    return {
        "id": model_id,
        "provider_id": provider_id,
        "provider_model_id": "upstream-test-model",
        "name": "Test Model",
        "context_window": 128_000,
        "max_output_tokens": 16_000,
        "capabilities": {"streaming": True},
        "pricing": [],
    }


def test_settings_accept_valid_provider_and_model() -> None:
    settings = Settings(
        app_env="test",
        llm_providers=[_provider()],
        llm_models=[_model()],
    )
    assert settings.llm_providers[0].id == "openai"
    assert settings.llm_models[0].provider_id == "openai"


def test_settings_reject_model_with_unconfigured_provider() -> None:
    with pytest.raises(ValidationError, match="unconfigured providers"):
        Settings(app_env="test", llm_models=[_model(provider_id="missing")])


def test_settings_reject_duplicate_provider_ids() -> None:
    with pytest.raises(ValidationError, match="provider ids must be unique"):
        Settings(app_env="test", llm_providers=[_provider(), _provider()])


def test_settings_reject_duplicate_model_ids() -> None:
    with pytest.raises(ValidationError, match="model ids must be unique"):
        Settings(
            app_env="test",
            llm_providers=[_provider()],
            llm_models=[_model(), _model()],
        )


def test_provider_base_url_rejects_credentials_and_query_string() -> None:
    with pytest.raises(ValidationError):
        Settings(
            app_env="test",
            llm_providers=[
                {
                    **_provider(),
                    "base_url": "https://user:password@api.example.test/v1?secret=1",
                }
            ],
        )


def test_pricing_requires_timezone_aware_effective_date() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        PricingVersionConfig(
            version="v1",
            effective_from=datetime(2026, 1, 1),
            input_per_million_tokens=Decimal("1"),
        )


def test_model_rejects_max_output_above_context_window() -> None:
    with pytest.raises(ValidationError, match="cannot exceed context_window"):
        LLMModelConfig(
            **{
                **_model(),
                "context_window": 100,
                "max_output_tokens": 101,
            }
        )


def test_pricing_rejects_negative_cost() -> None:
    with pytest.raises(ValidationError):
        PricingVersionConfig(
            version="v1",
            effective_from=datetime(2026, 1, 1, tzinfo=UTC),
            input_per_million_tokens=Decimal("-0.01"),
        )
