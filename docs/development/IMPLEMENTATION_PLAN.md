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
- [x] Add Alembic environment and migration smoke test.
- [x] Add Redis lifecycle and readiness check.
- [x] Add Docker Compose and CI infrastructure.
- [x] Add local setup and migration documentation.

## Milestone 2 — Authentication and authorization

- [x] Implement users, password hashing, email normalization, registration, and login.
- [x] Implement refresh-session rotation, reuse detection, and revocation.
- [x] Implement authenticated user dependency and immediate session-family revocation checks.
- [x] Implement optional Google and Apple OIDC login.
- [x] Add authentication migrations and security tests.

## Milestone 3 — Conversation and message management

- [x] Implement conversation and message ORM models and migration.
- [x] Implement create/list/get/rename/soft-delete conversation operations.
- [x] Implement owner-scoped message append and chronological history retrieval.
- [x] Add keyset pagination and deterministic message sequence pagination.
- [x] Serialize concurrent PostgreSQL message appends with a conversation row lock.
- [x] Add unique sequence constraint, ownership tests, deletion tests, and PostgreSQL concurrency test.

## Milestone 4 — LLM foundation

- [ ] Define normalized generation request, response, stream-event, capability, and error contracts.
- [ ] Implement provider registry and configuration model.
- [ ] Implement first OpenAI-compatible adapter.
- [ ] Implement one provider-native adapter.
- [ ] Build provider contract tests and model catalog.

## Milestone 5 — Generation and streaming

- [ ] Implement generation request lifecycle and idempotency.
- [ ] Implement context-window accounting and bounded history selection.
- [ ] Implement POST + SSE streaming contract.
- [ ] Handle provider timeout, rate limit, partial output, disconnect, and cancellation.
- [ ] Persist assistant output and final usage in a transaction.
- [ ] Reconcile interrupted generation records after restart.

## Milestone 6 — Frontend experience

- [ ] Implement authentication UI and protected routes.
- [ ] Implement conversation list and chat workspace.
- [ ] Implement incremental SSE reader and cancellation.
- [ ] Add safe Markdown/code rendering, accessibility, and mobile layout.
- [ ] Add usage and account screens.

## Milestone 7 — Security, quality, and release

- [ ] Complete threat-model test cases.
- [ ] Add distributed rate limiting and account quotas.
- [ ] Add OpenTelemetry traces and business metrics.
- [ ] Load test concurrent generations and long-lived SSE connections.
- [ ] Define SLOs from measured workloads.
- [ ] Configure secrets, backups, restore tests, staging, and production deployment.
- [ ] Publish runbooks and release checklist.

## Verification status

Milestones 1–3 are implemented in the local source package. Actual PostgreSQL concurrency, full CI checks, dependency lock resolution, Docker execution, and OAuth provider sign-in must be verified in the target environment before production use.
