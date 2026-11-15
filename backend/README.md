# Ask AI Backend

## Requirements

- Python 3.14
- `uv`
- Docker Desktop (for PostgreSQL and Redis)

## Local setup

From the repository root:

```powershell
Copy-Item .env.example .env
# Edit .env only when changing local connection settings.
docker compose up -d postgres redis
cd backend
uv lock
uv sync --all-groups
uv run alembic upgrade head
uv run uvicorn ask_ai.main:app --reload --host 127.0.0.1 --port 8000
```

The API is available at `http://127.0.0.1:8000`; interactive documentation is at `/docs` in non-production environments. The container uses `python -m ask_ai.run`, which reads host and port from validated settings. To run the complete local stack in containers, commit `uv.lock` first and then use `docker compose up --build`; Compose applies Alembic migrations before starting the API.

## Infrastructure behavior

- The async SQLAlchemy engine and Redis client are created during FastAPI lifespan startup and closed during shutdown.
- Dependency network checks are performed by `/api/v1/health/ready`, not at import time.
- `/api/v1/health/live` reports only whether the process can serve requests.
- Database sessions are request-scoped. Services own their transaction boundaries.
- Do not keep transactions open during provider network calls.

## Tests

```powershell
uv run ruff check .
uv run mypy src
uv run pytest
```

Integration tests use `TEST_DATABASE_URL`, `TEST_REDIS_URL`, `AUTH_TEST_DATABASE_URL`, and `CONVERSATION_TEST_DATABASE_URL`; without these values, the corresponding external-service tests are skipped. Migration and concurrency tests create uniquely named PostgreSQL schemas and clean them up. GitHub Actions supplies disposable PostgreSQL and Redis services and runs the integration tests.

## Migrations

Create a migration after adding or changing ORM models:

```powershell
uv run alembic revision --autogenerate -m "add users table"
uv run alembic upgrade head
```

Review generated migrations manually. Never treat autogeneration as a substitute for schema review. The migration chain is incremental: `20261114_0001` establishes the baseline, `20261114_0002` adds authentication tables, and `20261114_0003` adds conversations and messages.

## Configuration

Settings are loaded from environment variables and local `.env` files. Never commit real secrets. `DATABASE_URL` must use `postgresql+asyncpg://` in normal environments. SQLite is accepted only for isolated tests. Production requires `APP_DEBUG=false`, a non-local database credential, and a TLS Redis URL (`rediss://`). Use explicit CORS origins when browser access is enabled.

The CI workflow and Docker build resolve a lockfile before installing dependencies. For reproducible local development, run `uv lock` once, commit `uv.lock`, and use `uv sync --locked --all-groups` on subsequent installs.


## Authentication configuration

Authentication routes are documented in `../docs/development/MILESTONE_2.md`. Conversation and message routes are documented in `../docs/development/MILESTONE_3.md`. For local development, configure `SECRET_KEY` in the root `.env`; the example contains a local-only development secret. Never use that value outside local development. Google and Apple are optional; set their client ID/secret pairs and exact redirect URIs to enable them. Google uses a top-level GET callback. Apple uses a POST `form_post` callback and requires a `SameSite=None; Secure` OAuth-state cookie while Apple is enabled; use HTTPS or a browser-supported secure localhost context for local Apple testing.

Apply the authentication migration with `uv run alembic upgrade head`. The refresh credential is an HttpOnly cookie. Refresh and logout require a signed CSRF token in `X-CSRF-Token`. After a browser reload, call `GET /api/v1/auth/csrf` with `credentials: include`, retain the returned token in memory, and then call the refresh endpoint. Do not persist access or CSRF tokens in browser storage.


## Conversation and message management

The conversation API is owner-scoped and requires a bearer access token. It supports conversation create/list/get/rename/soft-delete, appending user messages, and chronological message history. Message append locks the parent conversation row with `SELECT FOR UPDATE` on PostgreSQL and increments its sequence counter in the same transaction. The unique `(conversation_id, sequence)` constraint is the final collision guard. See `../docs/development/MILESTONE_3.md` for API parameters, pagination behavior, deletion semantics, and the PostgreSQL concurrency test.

## LLM foundation

Milestone 4 adds an operator-configured provider registry and model catalog. Configure `LLM_PROVIDERS` and `LLM_MODELS` as JSON arrays in the root `.env`; see the commented examples in `.env.example` and `../docs/development/MILESTONE_4.md`. Supported adapter types are `openai_compatible` (OpenAI Chat Completions-compatible endpoints) and `anthropic` (native Anthropic Messages API). SDK clients are created and closed within FastAPI lifespan, and SDK retries are disabled so future chat orchestration owns retry decisions. Provider credentials are stored as `SecretStr` settings and are never exposed by the catalog endpoints.

The catalog endpoints are `GET /api/v1/providers` and `GET /api/v1/models` (optionally filtered by `provider_id`). These endpoints expose model metadata and the latest effective, versioned pricing record only; unknown pricing remains unknown. They do not generate content. The generation service facade is available internally for Milestone 5; the public generation/SSE endpoint, durable generation lifecycle, usage ledger, and retries are not part of Milestone 4. See `../docs/architecture/LLM_FOUNDATION.md` for the provider contract, error taxonomy, lifecycle, and security decisions.
