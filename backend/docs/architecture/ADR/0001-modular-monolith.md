# ADR 0001: Start with a modular monolith

- Status: Accepted
- Date: 2026-11-14

## Context

The MVP is being developed by a small team and has a limited set of synchronous domains: authentication, conversations, chat orchestration, provider adapters, model metadata, and usage accounting. Microservices would add deployment, networking, tracing, consistency, and operational costs before independent scaling needs are known.

## Decision

Build one deployable FastAPI application with explicit modules and dependency boundaries. Keep provider adapters behind contracts. Use PostgreSQL as the durable source of truth and Redis for ephemeral cross-instance coordination.

## Consequences

Positive:
- Easier local development and end-to-end testing.
- Simpler transactions for message and generation state transitions.
- Lower deployment and operational overhead.
- Modules can be extracted later if independent scaling or ownership is justified.

Trade-offs:
- Teams must enforce module boundaries through code review and tests.
- Long-running streaming requests share the API deployment footprint.
- A single release artifact contains all backend modules.

## Revisit when

Measured throughput, deployment isolation, independent team ownership, provider-specific resource needs, or fault-containment requirements justify service extraction. Do not split services based only on theoretical future scale.
