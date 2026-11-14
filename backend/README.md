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

Integration tests use `TEST_DATABASE_URL` and `TEST_REDIS_URL`; without these values, the external-service tests are skipped. GitHub Actions supplies disposable PostgreSQL and Redis services and runs the integration tests.

## Migrations

Create a migration after adding or changing ORM models:

```powershell
uv run alembic revision --autogenerate -m "add users table"
uv run alembic upgrade head
```

Review generated migrations manually. Never treat autogeneration as a substitute for schema review. The initial `20261114_0001` revision is intentionally empty and establishes the migration chain before domain tables are introduced.

## Configuration

Settings are loaded from environment variables and local `.env` files. Never commit real secrets. `DATABASE_URL` must use `postgresql+asyncpg://` in normal environments. SQLite is accepted only for isolated tests. Production requires `APP_DEBUG=false`, a non-local database credential, and a TLS Redis URL (`rediss://`). Use explicit CORS origins when browser access is enabled.

The CI workflow and Docker build resolve a lockfile before installing dependencies. For reproducible local development, run `uv lock` once, commit `uv.lock`, and use `uv sync --locked --all-groups` on subsequent installs.
