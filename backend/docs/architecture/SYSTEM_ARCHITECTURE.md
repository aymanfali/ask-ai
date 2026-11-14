# System Architecture

- Status: Baseline architecture
- Style: Modular monolith

## 1. Context

The browser communicates with a FastAPI application over HTTPS. The API owns authentication, authorization, conversations, message persistence, model discovery, generation lifecycle, and usage metering. The API communicates with LLM providers through adapters. PostgreSQL is the durable source of truth; Redis supports distributed rate limits, short-lived coordination, and cache-like data only where justified.

## 2. Logical modules

| Module | Owns | Must not own |
|---|---|---|
| auth | credentials, identities, sessions | conversation business rules |
| conversations | conversation lifecycle and ownership | provider SDK calls |
| chat | generation orchestration and context assembly | HTTP response construction details |
| llm | provider protocols, adapters, model capabilities, normalization | user/account persistence rules |
| models | application-visible model catalog | provider secret material |
| usage | ledger, pricing versions, quota calculations | message content |
| api | HTTP validation, auth dependencies, serialization | business logic |

## 3. Dependency direction

API endpoints call application services. Services depend on domain contracts and repository interfaces. Infrastructure implementations provide SQLAlchemy repositories, Redis coordination, and provider adapters. Domain/application modules must not import FastAPI request/response objects or provider SDK models.

## 4. Generation lifecycle

1. Authenticate user and validate request shape.
2. Load conversation under the authenticated user's ownership scope.
3. Resolve model and verify requested capabilities.
4. Apply account/model/concurrency limits and reserve quota if required.
5. Persist the user message and a pending generation request; commit.
6. Build normalized model input within the context budget.
7. Call the selected provider adapter with bounded connect/read/total timeouts.
8. Normalize provider chunks into application events and forward SSE.
9. Accumulate output for persistence while enforcing output limits.
10. Persist assistant message, terminal generation status, and usage ledger in a final transaction.
11. Release concurrency/quota reservations and close provider/client resources.

Never hold a database transaction open during provider network I/O. If the client disconnects, cancel upstream work when supported and finalize the generation as cancelled or interrupted. If output has already been emitted, do not transparently switch to another provider.

## 5. SSE wire protocol

Use `text/event-stream` and explicit event names. Each event's data is a JSON object.

- `message.started`: `generation_id`, assistant message placeholder ID, model.
- `message.delta`: `generation_id`, incremental text delta.
- `message.usage`: `generation_id`, usage values and source when available.
- `message.completed`: IDs, finish reason, terminal status.
- `message.error`: stable error code and safe user-facing message.
- `message.cancelled`: generation ID and terminal state.

The server must send anti-buffering headers, disable proxy buffering for stream routes, handle backpressure, emit heartbeat comments where needed, and never put secrets or raw provider error bodies in events. For POST streaming, the frontend should use `fetch()` and a streaming reader; native EventSource does not support a POST request body.

## 6. Provider adapter contract

Define normalized request, response, stream-event, health, and error types. Adapters translate to/from provider-specific APIs. Capabilities are explicit metadata, not inferred from model names. Provider errors are mapped to stable internal categories: authentication, invalid request, rate limited, timeout, unavailable, content/policy rejection, context exceeded, malformed response, and unknown.

Retry only transient failures before any user-visible stream delta, with bounded attempts, jitter, and provider retry guidance. Do not retry invalid requests, authentication failures, policy rejections, or context errors. Do not automatically retry a request with uncertain outcome unless idempotency semantics are defined.

## 7. Persistence and coordination

- PostgreSQL stores users, identities, sessions, conversations, messages, generation requests, provider/model metadata, usage records, and pricing versions.
- Redis stores short-lived counters/locks/coordination with TTLs. It is not the durable source of billing or usage truth.
- Every write that changes generation terminal state and usage ledger must be idempotent.
- Each concurrent DB unit of work owns its own SQLAlchemy AsyncSession.

## 8. Deployment topology

Start with stateless API instances behind a reverse proxy. PostgreSQL and Redis are managed or separately operated stateful dependencies. Provider calls are outbound only. Scale API replicas based on measured CPU, memory, active streams, connection pools, provider rate limits, and latency. Do not introduce a message broker until an actual asynchronous workload requires durable queue semantics.

## 9. Security boundaries

- Browser trusts only the Ask AI API origin.
- API derives user identity from validated credentials, never from request-supplied user IDs.
- Provider secrets are server-side and centrally managed.
- User-controlled provider base URLs are out of MVP scope; if introduced, enforce strict host allowlists and SSRF protections.
- Model output is untrusted input for any downstream renderer or tool.
