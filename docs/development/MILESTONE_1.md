# Milestone 1 — Foundation Implementation

## Delivered

- Validated environment settings with bounded connection-pool and timeout settings.
- PostgreSQL async SQLAlchemy engine created at application startup and disposed at shutdown.
- Request-scoped async session dependency; domain services own transaction boundaries.
- Redis async client created and closed through FastAPI lifespan.
- Liveness and readiness endpoints with concurrent, time-bounded dependency probes.
- Pure ASGI request context middleware with UUID request IDs, response correlation header, and request duration logging.
- Structlog + standard-library logging integration, JSON in staging/production, console output locally, recursive sensitive-field redaction.
- Standard API error envelope for application, HTTP, validation, and unexpected errors. Validation responses never echo submitted values.
- Alembic async migration environment, naming conventions, empty baseline revision, and fresh-database migration smoke test.
- Docker Compose for PostgreSQL, Redis, and API with health checks and localhost-only published ports.
- GitHub Actions services for PostgreSQL and Redis, lint/type/test commands, and integration test execution.

## Local verification

On Windows PowerShell, run `./scripts/verify_milestone_1.ps1` from the repository root. It starts PostgreSQL and Redis, resolves dependencies if needed, applies migrations, and runs lint, type, and test checks.

Manual commands:

```bash
cp .env.example .env
cd backend
uv lock
uv sync --all-groups
# Commit backend/uv.lock before running CI or the Docker build.
cd ..

docker compose up --build -d
# Compose applies the Alembic baseline before starting the API.

# Or run backend from host
cd backend
uv run alembic upgrade head
uv run ruff check .
uv run mypy src
uv run pytest --cov=ask_ai --cov-report=term-missing
```

## Health endpoints

- `GET /api/v1/health/live`: process liveness only.
- `GET /api/v1/health/ready`: returns 200 only when PostgreSQL and Redis both answer a bounded probe; otherwise 503 with dependency names and no connection details.

## Important operational decisions

- Startup constructs clients but does not require dependencies to be reachable. The process can start and report unready while dependencies recover.
- Do not open a database transaction before making external LLM calls.
- Do not use SQLite in production. It is only allowed in isolated tests.
- Redis is not the source of truth for durable user usage or billing records.
- The initial migration is intentionally empty. Domain tables are introduced in later milestones.
- Local Compose credentials are for development only. Do not reuse them in staging or production.

## Verification limitation for this build

The build environment provided Python 3.13.5, not the project's required Python 3.14, and did not have Docker or network access to download missing packages. Static syntax/configuration checks can be run here; full dependency, Docker, PostgreSQL, Redis, and CI runtime verification must run in the project's target environment.
