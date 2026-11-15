from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ask_ai.modules.llm.catalog import ModelCatalog
from ask_ai.modules.llm.config import (
    LLMModelConfig,
    PricingVersionConfig,
)


def test_catalog_selects_latest_effective_pricing(openai_provider_config, model_config) -> None:
    older = PricingVersionConfig(
        version="v1",
        effective_from=datetime.now(UTC) - timedelta(days=10),
        input_per_million_tokens=Decimal("1"),
        output_per_million_tokens=Decimal("2"),
    )
    newer = PricingVersionConfig(
        version="v2",
        effective_from=datetime.now(UTC) - timedelta(days=1),
        input_per_million_tokens=Decimal("3"),
        output_per_million_tokens=Decimal("4"),
    )
    future = PricingVersionConfig(
        version="v3",
        effective_from=datetime.now(UTC) + timedelta(days=1),
        input_per_million_tokens=Decimal("9"),
        output_per_million_tokens=Decimal("9"),
    )
    model = model_config.model_copy(update={"pricing": (older, newer, future)})
    catalog = ModelCatalog(providers=[openai_provider_config], models=[model])

    response = catalog.list_models()[0]

    assert response.current_pricing is not None
    assert response.current_pricing.version == "v2"
    assert response.current_pricing.input_per_million_tokens == Decimal("3")


def test_catalog_hides_models_for_disabled_provider(openai_provider_config, model_config) -> None:
    disabled = openai_provider_config.model_copy(update={"enabled": False})
    catalog = ModelCatalog(providers=[disabled], models=[model_config])

    assert catalog.list_models() == []
    assert catalog.get_model(model_config.id) is None
    assert catalog.list_providers() == []


def test_public_catalog_never_contains_provider_credentials(
    openai_provider_config, model_config
) -> None:
    catalog = ModelCatalog(providers=[openai_provider_config], models=[model_config])
    serialized = str(catalog.list_providers()) + str(catalog.list_models())

    assert openai_provider_config.api_key.get_secret_value() not in serialized


def test_catalog_provider_filter(
    openai_provider_config, anthropic_provider_config, model_config
) -> None:
    anthropic_model = LLMModelConfig(
        id="anthropic:test-model",
        provider_id="anthropic",
        provider_model_id="claude-test",
        name="Claude Test",
        context_window=200_000,
        max_output_tokens=32_000,
    )
    catalog = ModelCatalog(
        providers=[openai_provider_config, anthropic_provider_config],
        models=[model_config, anthropic_model],
    )

    assert [item.id for item in catalog.list_models(provider_id="anthropic")] == [
        "anthropic:test-model"
    ]
