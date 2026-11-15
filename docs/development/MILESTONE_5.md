# Milestone 5 — Generation and streaming

## Scope delivered

Milestone 5 connects the authenticated conversation API to the normalized LLM provider layer. It introduces a durable generation lifecycle, POST-based SSE, model-aware context selection, cancellation, idempotency, partial-response persistence, bounded provider retry, and a per-generation usage ledger.

## API

### Start a generation

`POST /api/v1/conversations/{conversation_id}/messages/stream`

Authentication: bearer access token.

Required header:

```http
Idempotency-Key: 5d6f7d4c-unique-request-key
Content-Type: application/json
```

Request:

```json
{
  "content": "Explain async database transactions.",
  "model_id": "openai:my-model",
  "max_output_tokens": 1200,
  "temperature": 0.2,
  "top_p": null,
  "stop_sequences": []
}
```

`max_output_tokens`, `temperature`, `top_p`, and `stop_sequences` are optional. If the output limit is omitted, the server uses the configured default capped by the model's configured maximum. The same idempotency key and identical normalized request return the original result; using the same key for a different payload returns `409 idempotency_key_reused`. The fingerprint uses caller-supplied values (including an omitted output-token limit), not mutable server defaults. An active duplicate returns `409 generation_in_progress` and includes the generation ID in error details. If its execution lease has expired, the retry first marks the abandoned generation interrupted and then replays its terminal state.

### Inspect generation

`GET /api/v1/generations/{generation_id}` returns status, model/provider identifiers, terminal error code, timestamps and usage metadata. The lookup is always scoped to the authenticated user.

### Request cancellation

`POST /api/v1/generations/{generation_id}/cancel` requests cancellation through a short-lived Redis marker. The running stream polls Redis while waiting for provider chunks, so cancellation works across API processes. The endpoint is idempotent for terminal generations.

## SSE event contract

The endpoint returns `text/event-stream`, disables proxy buffering, and emits monotonically increasing per-stream event IDs.

| Event | Data | Meaning |
|---|---|---|
| `generation.started` | generation/conversation/message IDs, assistant sequence, replay flag | Durable request accepted and stream initialized |
| `message.delta` | generation ID, assistant message ID, text | Incremental assistant text |
| `generation.usage` | input/output/total tokens, source | Provider-reported usage when available |
| `stream.heartbeat` | generation ID | Keeps idle streams alive while waiting for the provider |
| `generation.completed` | message ID, finish reason, provider request ID, usage | Assistant response and usage ledger committed |
| `generation.error` | safe generation error code | Generation failed or was interrupted |
| `generation.cancelled` | generation and message IDs | Cancellation was persisted |

Example:

```text
event: generation.started
data: {"generation_id":"...","assistant_message_id":"..."}

event: message.delta
data: {"generation_id":"...","message_id":"...","text":"Hello"}

event: generation.completed
data: {"generation_id":"...","message_id":"...","finish_reason":"stop","usage":{"input_tokens":20,"output_tokens":3,"total_tokens":23}}
```

The frontend must use `fetch()` and a streaming response reader because this endpoint uses POST with a JSON body. The native browser `EventSource` API is GET-only and cannot send this request body or an Authorization header.

## Lifecycle and persistence

A generation transaction locks the parent conversation and atomically inserts:

1. The completed user message.
2. An empty pending assistant message.
3. A `generation_requests` record with an idempotency key, request fingerprint, and lease expiry.

The transaction commits before any provider network I/O. No database transaction is held open while waiting for the LLM.

The record transitions through `pending` → `streaming` → one terminal state: `completed`, `failed`, `cancelled`, or `interrupted`. The durable `streaming` transition is committed before the first `generation.started` event is emitted. The assistant message uses its own status vocabulary: `pending`, `streaming`, `complete`, `failed`, `cancelled`, or `interrupted`.

The conversation row is locked while allocating the user/assistant sequence pair. A partial unique index permits only one active generation per conversation. Normal message append and conversation deletion are rejected while generation is active. A lease expiry marks abandoned work as interrupted and permits the conversation to continue after a worker crash.

The assistant response is checkpointed every configured number of characters, on elapsed-time checkpoints while the provider is idle, and on terminal paths. A browser disconnect marks the generation interrupted and retains the partial text; an explicit cancellation request marks it cancelled. Finalization, partial checkpoints, and lease recovery lock the generation row, preventing a late worker from overwriting a terminal state. If cancellation commits before the finalization lock is acquired, cancellation wins the terminal transition.

## Context window management

The server builds context from the latest completed user/assistant history plus the new user message. The optional operator system prompt is placed first. Only a contiguous newest suffix of history is selected; an incomplete/failed message is excluded, and an orphaned assistant answer is not retained without its initiating user message.

The input budget is calculated as:

`floor((model.context_window - requested_output_tokens) * generation_context_safety_factor)`

The built-in estimator is deliberately conservative and language-aware at a coarse character level. It is not a tokenizer and is never labelled provider-reported. Exact provider token usage supersedes estimates when both input and output counts are supplied.

## Retry and fallback policy

Provider SDK automatic retries remain disabled. The orchestration layer performs a small bounded retry only for a rate-limit response received before any normalized provider event was emitted, respecting bounded `Retry-After` guidance. It does not retry timeouts or ambiguous provider-unavailable failures, and it never retries after a stream event or user-visible delta. It never silently switches providers mid-response.

A retry before the first event does not guarantee that an upstream provider did no work; providers do not share a universal request-idempotency contract. This policy is deliberately narrow to reduce duplicate execution and surprise charges.

## Usage accounting

Every terminal generation writes at most one `usage_ledger` row. `usage_source` distinguishes:

- `provider_reported`: provider supplied both input and output token counts.
- `estimated`: one or both counts were estimated by the local heuristic.
- `unavailable`: a worker lease expired before reliable usage could be recovered.

Costs use `Decimal`, the current effective versioned model pricing record, and are stored only when both required input and output rates are known. Cached-input pricing is applied only when a provider supplies cached-token counts and a cached rate exists. Unknown prices remain null; no prices are invented.

## Database migration

`20261115_0004_generation_and_usage` adds:

- `generation_requests`: user-owned generation lifecycle, idempotency, request fingerprint, timestamps, provider/model identifiers, and cancellation/lease metadata.
- `usage_ledger`: one unique, auditable usage record per generation.

The messages content constraint now permits empty content while an assistant message is pending/streaming or terminally failed/cancelled/interrupted. Completed messages must contain non-whitespace content; maximum persisted message size is 256,000 characters.

## Configuration

| Variable | Default | Purpose |
|---|---:|---|
| `GENERATION_DEFAULT_MAX_OUTPUT_TOKENS` | 1024 | Default output budget |
| `GENERATION_HISTORY_MAX_MESSAGES` | 100 | Maximum history messages considered |
| `GENERATION_CONTEXT_SAFETY_FACTOR` | 0.85 | Input budget safety margin |
| `GENERATION_MAX_RETRIES` | 1 | Maximum rate-limit retries before first event |
| `GENERATION_RETRY_BASE_SECONDS` | 0.5 | Exponential retry base |
| `GENERATION_MAX_DURATION_SECONDS` | 180 | Total generation deadline |
| `GENERATION_PARTIAL_FLUSH_CHARACTERS` | 4096 | Persistence checkpoint interval |
| `GENERATION_CANCEL_SIGNAL_TTL_SECONDS` | 300 | Redis cancellation marker TTL |
| `GENERATION_SYSTEM_PROMPT` | unset | Optional operator system instruction |

## Verification

The repository includes unit tests for context budgeting, token-estimation semantics, idempotency fingerprints, pricing arithmetic, cancellation polling, heartbeat behavior, and retry-delay bounds. The SQLite integration suite covers the HTTP stream lifecycle, idempotent replay, stale-worker recovery, persistence, usage accounting, and request validation. PostgreSQL migration tests must assert revision `20261115_0004`; PostgreSQL integration remains necessary for row-lock and partial-index concurrency guarantees.

Live provider credentials, Docker execution, PostgreSQL/Redis integration, and frontend stream integration must be verified in the target development environment before production release.
