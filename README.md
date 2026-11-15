# Ask AI

A production-oriented, multi-provider AI chat platform.

**Status: Milestone 5 implemented locally.** The platform now includes application infrastructure, authentication, owner-scoped conversations, provider-neutral LLM contracts, streaming generation, idempotency, cancellation, context budgeting, partial-response persistence, and token/cost usage records. Live provider calls, PostgreSQL/Redis integration, OAuth credentials, dependency lock generation, and container execution still require verification in the target environment.

## Product objective

Ask AI provides a secure chat workspace over multiple LLM providers through one normalized application interface. The first release focuses on authentication, durable conversations, model selection, streaming generation, cancellation, and auditable usage records.

RAG, autonomous agents, multimodal workflows, fine-tuning, billing, and enterprise workflow automation are outside the first release.

## Technology baseline

| Area | Choice |
|---|---|
| Runtime | Python 3.14 |
| API | FastAPI, Pydantic v2 |
| Persistence | PostgreSQL, SQLAlchemy async, Alembic |
| Ephemeral coordination | Redis |
| Provider transport | OpenAI and Anthropic async SDK adapters |
| Frontend | React, TypeScript, Vite, React Router |
| Python tooling | uv, Ruff, pytest, mypy |
| Infrastructure | Docker Compose; GitHub Actions |

Dependency ranges are constrained in `backend/pyproject.toml`. The lockfile must be generated and committed before a deployable release; do not deploy from floating ranges.

## Repository layout

```text
backend/          FastAPI application and tests
frontend/         React + TypeScript application
docs/             Requirements, architecture, security, and delivery docs
infrastructure/   Local and deployment infrastructure
.github/          CI and contribution templates
```

## Local development

Prerequisites: Python 3.14, uv, Docker with Compose, and Git.

1. Copy `.env.example` to `.env`; its credentials are for local development only.
2. From `backend/`, run `uv lock` once and then `uv sync --all-groups`.
3. Commit `backend/uv.lock`; CI and Docker builds require this lockfile and verify it with `uv lock --check`.
4. Start the complete container stack with `docker compose up --build -d`. The API container applies the Alembic baseline before starting Uvicorn.
5. For host-based development, start dependencies with `docker compose up -d postgres redis`.
6. Run `uv run alembic upgrade head` before starting the API on the host.
7. Start the API with `uv run uvicorn ask_ai.main:app --reload --host 127.0.0.1 --port 8000`.
8. Check `/api/v1/health/live` for process liveness and `/api/v1/health/ready` for PostgreSQL/Redis readiness.
9. Run `uv run ruff check .`, `uv run mypy src`, and `uv run pytest` from `backend/`.

## Engineering principles

1. Keep provider SDKs and provider-specific response formats behind adapters.
2. Keep HTTP concerns out of domain services.
3. Enforce authorization server-side for every user-owned resource.
4. Persist generation state before streaming and finalize it explicitly.
5. Never keep a database transaction open while waiting on a provider.
6. Never retry or switch providers after user-visible output has started.
7. Treat usage accounting as a separate, auditable record.
8. Do not log prompts, completions, credentials, or access tokens by default.
9. Begin with a modular monolith; extract services only when measured needs justify it.
10. Ship each feature with automated tests and operator-facing documentation.

## Documentation

- [Milestone 2 — Authentication](docs/development/MILESTONE_2.md)
- [Milestone 3 — Conversations and messages](docs/development/MILESTONE_3.md)
- [Milestone 4 — LLM foundation and verification](docs/development/MILESTONE_4.md)
- [Milestone 5 — Generation and streaming](docs/development/MILESTONE_5.md)
- [LLM foundation architecture](docs/architecture/LLM_FOUNDATION.md)
- [Authentication security model](docs/security/AUTHENTICATION.md)

- [Product requirements](docs/product/PRD.md)
- [System architecture](docs/architecture/SYSTEM_ARCHITECTURE.md)
- [Database design](docs/architecture/DATABASE_DESIGN.md)
- [Threat model](docs/security/THREAT_MODEL.md)
- [Implementation plan](docs/development/IMPLEMENTATION_PLAN.md)
- [Milestone 1 implementation and verification](docs/development/MILESTONE_1.md)
- [Definition of done](docs/development/DEFINITION_OF_DONE.md)
- [ADR 0001 — Modular monolith](docs/architecture/ADR/0001-modular-monolith.md)
- [ADR 0002 — Provider-neutral LLM abstraction](docs/architecture/ADR/0002-provider-abstraction.md)

## Contributing

See [CONTRIBUTING.md](.github/CONTRIBUTING.md).
