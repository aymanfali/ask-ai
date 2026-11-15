from fastapi import APIRouter, Query, Request

from ask_ai.modules.llm.catalog import ModelCatalog
from ask_ai.modules.llm.schemas import ModelResponse, ProviderResponse

router = APIRouter(tags=["llm-catalog"])


@router.get(
    "/providers",
    response_model=list[ProviderResponse],
    summary="List configured LLM providers",
)
async def list_providers(request: Request) -> list[ProviderResponse]:
    """Return non-secret metadata for enabled, operator-configured providers."""
    catalog: ModelCatalog = request.app.state.llm_catalog
    return catalog.list_providers()


@router.get("/models", response_model=list[ModelResponse], summary="List available LLM models")
async def list_models(
    request: Request,
    provider_id: str | None = Query(default=None, min_length=2, max_length=48),
) -> list[ModelResponse]:
    """Return enabled model metadata and the effective pricing version, if known."""
    catalog: ModelCatalog = request.app.state.llm_catalog
    return catalog.list_models(provider_id=provider_id)
