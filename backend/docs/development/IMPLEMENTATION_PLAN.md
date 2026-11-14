# Implementation Plan

## Milestone 0 — Product and architecture baseline

- [x] Establish PRD, system architecture, logical data model, threat model, and modular-monolith ADR.
- [x] Define API error-envelope and configuration conventions.
- [x] Define development and deployment assumptions.

## Milestone 1 — Foundation

- [x] Bootstrap FastAPI application and validated settings.
- [x] Add structured logging with sensitive-field redaction.
- [x] Add request correlation IDs and request timing logs.
- [x] Add a stable API error envelope and safe exception handlers.
- [x] Add liveness and dependency readiness probes.
- [x] Add PostgreSQL async engine/session lifecycle.
- [x] Add Alembic environment, initial baseline revision, and migration smoke test.
- [x] Add Redis lifecycle and readiness check.
- [x] Add Docker Compose for PostgreSQL, Redis, and API.
- [x] Add CI with lint, type checks, unit tests, and external-service integration tests.
- [x] Add local setup and migration documentation.

Milestone 1 implementation is complete in the local bootstrap source. Runtime verification requiring Python 3.14, Docker, PostgreSQL, and Redis must be completed on a machine with those tools available.

## Milestone 2 — Identity and conversations

- [ ] Implement users, password hashing, email normalization, and registration/login.
- [ ] Implement refresh-session rotation and revocation.
- [ ] Implement conversations/messages repositories and services.
- [ ] Add user ownership isolation to all operations.
- [ ] Add pagination, indexes, and concurrency-safe message ordering.

## Milestone 3 — LLM foundation

- [ ] Define normalized request, response, event, capability, and error contracts.
- [ ] Implement provider registry and configuration model.
- [ ] Implement first OpenAI-compatible adapter.
- [ ] Implement one provider-native adapter.
- [ ] Build provider contract tests and model catalog.

## Milestone 4 — Generation and streaming

- [ ] Implement generation request lifecycle and idempotency.
- [ ] Implement context-window accounting and bounded history selection.
- [ ] Implement POST + SSE streaming contract.
- [ ] Handle provider timeout, rate limit, partial output, disconnect, and cancellation.
- [ ] Persist assistant output and final usage in a transaction.
- [ ] Reconcile interrupted generation records after restart.

## Milestone 5 — Frontend experience

- [ ] Implement authentication UI and protected routes.
- [ ] Implement conversation list and chat workspace.
- [ ] Implement incremental SSE reader and cancellation.
- [ ] Add safe Markdown/code rendering, accessibility, and mobile layout.
- [ ] Add usage and account screens.

## Milestone 6 — Security, quality, and release

- [ ] Complete threat-model test cases.
- [ ] Add distributed rate limiting and account quotas.
- [ ] Add OpenTelemetry traces and business metrics.
- [ ] Load test concurrent generations and long-lived SSE connections.
- [ ] Define SLOs from measured workloads.
- [ ] Configure secrets, backups, restore tests, staging, and production deployment.
- [ ] Publish runbooks and release checklist.
