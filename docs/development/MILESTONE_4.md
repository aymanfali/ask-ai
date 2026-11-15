# Milestone 4 — LLM Foundation

## Delivered

- Validated, discriminated provider settings for OpenAI-compatible and Anthropic providers.
- Validated model catalog entries with upstream capabilities and versioned pricing metadata.
- Provider-neutral message, request, result, token usage, and internal stream event schemas.
- Provider protocol, app-lifespan registry, and provider-independent `LLMService` facade.
- OpenAI-compatible Chat Completions adapter.
- Native Anthropic Messages API adapter.
- Normalized provider error taxonomy and bounded `Retry-After` parsing.
- `GET /api/v1/providers` and `GET /api/v1/models` endpoints.
- Provider SDK dependency declarations and environment examples.
- Unit tests for validation, catalog selection, adapter mapping, streaming normalization, error handling, and service delegation.

## Configure providers

1. Copy `.env.example` to `.env`.
2. Uncomment and configure `LLM_PROVIDERS` with server-side API credentials.
3. Uncomment and configure `LLM_MODELS` using the exact upstream model IDs, context windows, max output sizes, and capability values supported by your provider account.
4. Add real, verified pricing versions when known. Leave pricing fields omitted/null until verified.
5. Never commit `.env` or real credentials. In staging/production, configured custom provider base URLs must use HTTPS.

`LLM_PROVIDERS` is a JSON array. Example shape (replace all example values):

```json
[
  {
    "id": "openai",
    "name": "OpenAI",
    "type": "openai_compatible",
    "api_key": "replace-me",
    "base_url": "https://api.openai.com/v1",
    "max_output_tokens_parameter": "max_completion_tokens"
  },
  {
    "id": "anthropic",
    "name": "Anthropic",
    "type": "anthropic",
    "api_key": "replace-me"
  }
]
```

`LLM_MODELS` is also a JSON array. Use an internal stable ID such as `openai:my-model` and the exact remote `provider_model_id`. Do not assume that all accounts have access to the same models or limits.

For OpenAI-compatible endpoints, set `max_output_tokens_parameter` to `max_tokens` or `max_completion_tokens` according to that endpoint's documented contract. Set `include_usage_in_stream=false` for gateways that reject `stream_options.include_usage`.

## API examples

```powershell
curl http://localhost:8000/api/v1/providers
curl "http://localhost:8000/api/v1/models"
curl "http://localhost:8000/api/v1/models?provider_id=openai"
```

The endpoints return only enabled configuration and never return API keys. These are catalog endpoints only. A user-facing generation endpoint is intentionally deferred to Milestone 5.

## Tests

```powershell
cd backend
uv sync --all-groups
uv run pytest tests/unit/llm -q
uv run pytest -q
uv run ruff check src tests
uv run mypy src/ask_ai
```

Live provider smoke tests require valid provider credentials and billable API calls; they are not run by the default unit suite. PostgreSQL/Redis integration suites remain separate from adapter tests.

## Verification caveats

The unit adapter tests use fake SDK-shaped clients and do not spend provider credits. Confirm the installed SDK versions, exact model availability, model-specific request parameters, streaming usage support, and pricing against your account before staging deployment. Provider-side integration tests and full CI are required before release.

## Explicitly deferred to Milestone 5

- User-facing generation endpoint.
- Durable generation state machine and idempotency.
- SSE public event contract and disconnect cancellation.
- Provider retries/fallback policy at chat orchestration layer.
- Usage ledger writes and quota reservations.
- Tokenizer-based context budgeting.

## Local verification performed for this delivery

The following checks were run in the build environment:

- `PYTHONPATH=src pytest -q tests/unit/llm tests/unit/test_config.py tests/unit/test_conversation_schemas.py tests/unit/test_conversation_cursor.py` — **54 passed**.
- `python -m compileall -q backend/src backend/tests` — passed.
- `backend/pyproject.toml` parsed successfully with Python `tomllib`.
- `alembic upgrade head --sql` generated PostgreSQL migration SQL through revision `20261114_0003`.
- A production-settings test verifies that explicitly configured custom LLM provider URLs must use HTTPS.
- Adapter tests verify that incomplete upstream streams are not emitted as successful completions.

The execution environment provides Python 3.13.5 rather than the project's required Python 3.14, and does not have Docker, Ruff, Mypy, PostgreSQL/Redis services, or the declared OpenAI/Anthropic SDK packages installed. Therefore the following remain required on the target machine/CI: lock resolution with `uv lock`, full test suite, Ruff/Mypy, live database/Redis integration tests, actual SDK contract tests, Docker build, and credentialed provider smoke tests. Unit adapter tests use SDK-shaped fakes and do not contact providers or consume credits.
