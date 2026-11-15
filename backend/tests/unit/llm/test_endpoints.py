import pytest
from starlette.applications import Starlette
from starlette.requests import Request

from ask_ai.api.v1.endpoints.llm import list_models, list_providers
from ask_ai.modules.llm.catalog import ModelCatalog


def _request(catalog: ModelCatalog) -> Request:
    app = Starlette()
    app.state.llm_catalog = catalog
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/v1/models",
        "raw_path": b"/api/v1/models",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "app": app,
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_provider_and_model_catalog_endpoints_do_not_return_secrets(
    openai_provider_config, model_config
) -> None:
    catalog = ModelCatalog(providers=[openai_provider_config], models=[model_config])
    request = _request(catalog)

    providers = await list_providers(request)
    models = await list_models(request, provider_id=None)

    assert providers[0].id == "openai"
    assert models[0].id == model_config.id
    assert openai_provider_config.api_key.get_secret_value() not in repr(providers)
    assert openai_provider_config.api_key.get_secret_value() not in repr(models)


@pytest.mark.asyncio
async def test_model_endpoint_filters_by_provider(openai_provider_config, model_config) -> None:
    catalog = ModelCatalog(providers=[openai_provider_config], models=[model_config])
    request = _request(catalog)

    models = await list_models(request, provider_id="unknown")

    assert models == []
