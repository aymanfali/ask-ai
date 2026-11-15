# Milestone 3 — Conversation and Message Management

**Status:** Implemented in the source package; database-backed and PostgreSQL concurrency verification still required in an environment with the declared dependencies and PostgreSQL service.

## Delivered scope

- Conversation create, list, get, rename, and soft-delete operations.
- User message append and chronological message history retrieval.
- Server-side ownership checks for every conversation/message operation.
- UUID identifiers and database-enforced foreign keys/check constraints.
- Keyset pagination for conversations and sequence-based pagination for messages.
- Conversation-row locking for message sequence allocation on PostgreSQL.
- Unique `(conversation_id, sequence)` constraint as the final integrity guard.
- Deterministic provisional title from the first user message when the conversation still has the default title.

## API contract

All routes are under `/api/v1` and require a valid bearer access token.

Create a conversation:

```http
POST /api/v1/conversations
Authorization: Bearer <access_token>
Content-Type: application/json

{"title": "Project planning"}
```

Append a user message:

```http
POST /api/v1/conversations/<conversation_id>/messages
Authorization: Bearer <access_token>
Content-Type: application/json

{"content": "Summarize the project requirements."}
```

Retrieve the newest message page in chronological order:

```http
GET /api/v1/conversations/<conversation_id>/messages?limit=50
Authorization: Bearer <access_token>
```

Use the returned `next_before_sequence` as `before_sequence` to fetch older messages. `null` means there are no older visible messages.

| Method | Endpoint | Behavior |
|---|---|---|
| POST | `/conversations` | Create an empty conversation; optional title |
| GET | `/conversations?limit=20&cursor=...` | List the authenticated user's active conversations |
| GET | `/conversations/{conversation_id}` | Retrieve one active conversation owned by the user |
| PATCH | `/conversations/{conversation_id}` | Rename an owned conversation |
| DELETE | `/conversations/{conversation_id}` | Soft-delete an owned conversation; returns 204 |
| POST | `/conversations/{conversation_id}/messages` | Append a user-authored message |
| GET | `/conversations/{conversation_id}/messages?limit=50&before_sequence=...` | Retrieve messages in chronological order |

### Conversation pagination

- Sort order is `updated_at DESC, id DESC`.
- The opaque URL-safe cursor encodes the last returned `(updated_at, id)` pair.
- Because `updated_at` changes when a conversation receives activity, concurrent updates can move a conversation between pages; the cursor guarantees deterministic ordering for the observed values, not a multi-request snapshot.
- The next page uses a strict lexicographic less-than predicate, so equal timestamps are deterministic.
- Page size is limited to 1–100.
- Invalid cursors return `422 invalid_pagination_cursor`.

### Message pagination

- The database allocates a strictly increasing `sequence` per conversation.
- The initial request loads the newest page and returns it in chronological order.
- `next_before_sequence` is the sequence of the oldest item in the page when older items remain.
- Older pages request `sequence < before_sequence`.
- Page size is limited to 1–100.

## Data model

### conversations

- `id UUID PK`
- `user_id UUID FK users(id) ON DELETE CASCADE`
- `title VARCHAR(200) NOT NULL`
- `last_message_sequence BIGINT NOT NULL DEFAULT 0`
- `created_at TIMESTAMPTZ NOT NULL`
- `updated_at TIMESTAMPTZ NOT NULL`
- `deleted_at TIMESTAMPTZ NULL`
- Checks: non-empty trimmed title; sequence counter is nonnegative.
- Index: `(user_id, deleted_at, updated_at, id)` for owner-scoped active-conversation keyset pages.

### messages

- `id UUID PK`
- `conversation_id UUID FK conversations(id) ON DELETE CASCADE`
- `role VARCHAR(20) NOT NULL`
- `content TEXT NOT NULL`
- `status VARCHAR(20) NOT NULL DEFAULT 'complete'`
- `sequence BIGINT NOT NULL`
- `created_at TIMESTAMPTZ NOT NULL`
- Unique `(conversation_id, sequence)`.
- Checks constrain role, status, positive sequence, non-empty content, and a 32,000-character maximum.
- Index `(conversation_id, created_at)`.

The write API accepts only user-authored content. Assistant messages are reserved for trusted generation workflows. System/developer roles are internal policy context and are never returned by the user-facing history endpoint; the client cannot select any role.

## Concurrency model

`append_user_message` selects the active conversation row using `SELECT ... FOR UPDATE`, increments `last_message_sequence`, inserts the message, updates conversation activity, and commits in one transaction. PostgreSQL serializes concurrent appends for the same conversation. The unique composite constraint protects against sequence collisions even if a future writer bypasses the service.

SQLite is used only for ordinary service unit tests and does not provide the row-level locking semantics being verified by the PostgreSQL integration test. Set `CONVERSATION_TEST_DATABASE_URL` to a disposable PostgreSQL database to run that test. It creates a uniquely named schema and drops only that schema.

## Deletion and retention

Conversation deletion is a soft delete. Deleted conversations disappear from list/get/message endpoints, while their message rows remain for a future, explicit retention/purge policy. User deletion cascades at the database layer. Do not add individual message deletion or hard conversation purge without a retention, audit, and data-export decision.

## Title behavior

New conversations default to `New conversation`. On the first user message only, if the title is still the default, the service uses the first non-empty line truncated to 80 characters. Users can subsequently rename it. LLM-generated titles are not part of this milestone.

## Verification

Run from `backend/` after installing the lockfile/dependency group and starting the test database if needed:

```powershell
uv run pytest tests/unit/test_conversation_schemas.py tests/unit/test_conversation_cursor.py -q
uv run pytest tests/unit/test_conversation_service.py -q
uv run pytest tests/integration/test_conversation_api.py -q
uv run pytest tests/integration/test_conversation_sequence_concurrency.py -q
uv run pytest tests/integration/test_migrations.py -q
uv run ruff check src tests
uv run mypy src/ask_ai
uv run alembic upgrade head
```

The API/service SQLite tests require `aiosqlite`, included in the development dependency group. The migration and sequence-concurrency integration tests are skipped unless `TEST_DATABASE_URL` and `CONVERSATION_TEST_DATABASE_URL` are set to a disposable PostgreSQL database. They create and remove isolated schemas rather than modifying the database's default schema.

## Explicitly deferred

- LLM generation and assistant message creation (Milestone 4/5).
- Message editing, deleting, regenerating, or branching.
- LLM-assisted title generation.
- Search across message contents.
- Conversation export and retention purge jobs.
- Model/provider selection stored on conversation.
