# Database Design — Initial Logical Model

This is the logical target schema; migrations and ORM entities are added incrementally.

## Entities

### users

- `id UUID PK`
- `email CITEXT UNIQUE NOT NULL` (or normalized canonical text with a unique index)
- `password_hash TEXT NULL` (NULL for identity-only users)
- `display_name TEXT NULL`
- `is_active BOOLEAN NOT NULL`
- `created_at`, `updated_at TIMESTAMPTZ NOT NULL`

### auth_identities

- `id UUID PK`
- `user_id UUID FK users(id)`
- `provider TEXT NOT NULL`
- `provider_subject TEXT NOT NULL`
- `email_at_provider TEXT NULL`
- `created_at TIMESTAMPTZ NOT NULL`
- Unique `(provider, provider_subject)`; never identify an OAuth user by email alone without a verified, explicit account-linking flow.

### refresh_sessions

- `id UUID PK`
- `user_id UUID FK users(id)`
- `token_hash TEXT UNIQUE NOT NULL`
- `expires_at TIMESTAMPTZ NOT NULL`
- `revoked_at TIMESTAMPTZ NULL`
- `created_at`, `last_used_at TIMESTAMPTZ`

Store only a hash of opaque refresh tokens. Access tokens are short-lived and not persisted unless a specific revocation design requires it.

### conversations

- `id UUID PK`
- `user_id UUID FK users(id)`
- `title TEXT NOT NULL`
- `default_model_id UUID FK llm_models(id) NULL`
- `created_at`, `updated_at TIMESTAMPTZ NOT NULL`
- `deleted_at TIMESTAMPTZ NULL`

Index `(user_id, updated_at DESC)` and enforce ownership in every repository query.

### messages

- `id UUID PK`
- `conversation_id UUID FK conversations(id)`
- `generation_id UUID NULL FK generation_requests(id)`
- `role TEXT NOT NULL` (system/developer roles are internal policy-controlled values; user-visible clients cannot inject privileged messages)
- `content TEXT NOT NULL`
- `status TEXT NOT NULL`
- `sequence BIGINT NOT NULL`
- `model_id UUID FK llm_models(id) NULL`
- `created_at TIMESTAMPTZ NOT NULL`
- Unique `(conversation_id, sequence)`; index `(conversation_id, sequence)`.

Use a constrained role/status enum or check constraints. Define edit/regenerate semantics before allowing mutations to historic messages.

### llm_providers and llm_models

Provider records contain non-secret metadata and enabled state. Provider secrets live in a secret manager/environment, not in a general-purpose model table. Model records include stable provider model ID, display name, capability flags, context/output limits, enabled state, and metadata version.

### generation_requests

- `id UUID PK`
- `user_id UUID FK users(id)`
- `conversation_id UUID FK conversations(id)`
- `user_message_id UUID FK messages(id)`
- `assistant_message_id UUID FK messages(id) NULL`
- `provider_id UUID FK llm_providers(id)`
- `model_id UUID FK llm_models(id)`
- `idempotency_key TEXT NOT NULL`
- `status TEXT NOT NULL` (pending/streaming/completed/failed/cancelled/interrupted)
- `error_code TEXT NULL`
- `started_at`, `finished_at TIMESTAMPTZ NULL`
- Unique `(user_id, idempotency_key)`; index `(user_id, created_at DESC)`.

The application must define whether an idempotency key may be reused after expiration and how request payload hashes are checked.

### usage_ledger

- `id UUID PK`
- `generation_id UUID UNIQUE FK generation_requests(id)` for one final accounting record per generation (or use a separate append-only adjustment ledger if corrections are needed)
- `user_id UUID FK users(id)`
- `provider_id`, `model_id`
- `input_tokens BIGINT NULL`, `output_tokens BIGINT NULL`
- `usage_source TEXT NOT NULL` (provider_reported/estimated/unavailable)
- `input_cost`, `output_cost`, `total_cost NUMERIC(20,10) NULL`
- `currency CHAR(3) NOT NULL`
- `pricing_version TEXT NULL`
- `recorded_at TIMESTAMPTZ NOT NULL`

Do not use floating point for money. Preserve raw token counts and pricing-version attribution. Corrections should be explicit adjustment entries, not silent mutation of prior accounting.

## Cross-cutting rules

- Use UUID primary keys and UTC `TIMESTAMPTZ`.
- Use database constraints for uniqueness and referential integrity.
- Use optimistic concurrency/versioning or row locking for sequence allocation and concurrent conversation writes.
- Each concurrent task gets its own SQLAlchemy `AsyncSession`.
- Use explicit retention/deletion policies for personal data and audit records.
- Never cascade-delete usage records without an approved retention/accounting policy.

## Implemented authentication tables (Milestone 2)

### users

- `id UUID PK`
- `email VARCHAR(320) UNIQUE NOT NULL` (normalized and case-folded by the service)
- `password_hash TEXT NULL` (Argon2id; NULL for OIDC-only accounts)
- `display_name VARCHAR(120) NULL`
- `is_active BOOLEAN NOT NULL`
- `email_verified_at TIMESTAMPTZ NULL`
- `created_at`, `updated_at TIMESTAMPTZ NOT NULL`

### auth_identities

- `id UUID PK`
- `user_id UUID FK users(id) ON DELETE CASCADE`
- `provider VARCHAR(32) NOT NULL`
- `provider_subject VARCHAR(255) NOT NULL`
- `email_at_provider VARCHAR(320) NULL`
- `created_at TIMESTAMPTZ NOT NULL`
- Unique `(provider, provider_subject)` and index on `user_id`.

### refresh_sessions

- `id UUID PK`
- `user_id UUID FK users(id) ON DELETE CASCADE`
- `family_id UUID NOT NULL` (groups rotations for one device/browser session)
- `token_hash CHAR(64) UNIQUE NOT NULL` (SHA-256 of a 48-byte random opaque token)
- `expires_at TIMESTAMPTZ NOT NULL`
- `family_expires_at TIMESTAMPTZ NOT NULL` (absolute 90-day family expiry)
- `rotated_at TIMESTAMPTZ NULL`
- `revoked_at TIMESTAMPTZ NULL`
- `replaced_by_id UUID FK refresh_sessions(id) NULL`
- `created_at TIMESTAMPTZ NOT NULL`
- Indexes on `user_id`, `family_id`, and `expires_at`.

Refresh rotation selects the current row `FOR UPDATE`, inserts the replacement, and marks the old row rotated in the same transaction. Reuse of a rotated token revokes all non-revoked rows in that family. Protected API calls join the access token's family ID to an active, unrotated refresh-session row to support immediate revocation.

## Implemented conversation/message tables (Milestone 3)

### conversations

- `id UUID PK`
- `user_id UUID FK users(id) ON DELETE CASCADE`
- `title VARCHAR(200) NOT NULL DEFAULT 'New conversation'`
- `last_message_sequence BIGINT NOT NULL DEFAULT 0`
- `created_at`, `updated_at TIMESTAMPTZ NOT NULL`
- `deleted_at TIMESTAMPTZ NULL`
- Checks enforce a non-empty trimmed title and nonnegative sequence counter.
- Index `(user_id, deleted_at, updated_at, id)` supports owner-scoped keyset pagination.

### messages

- `id UUID PK`
- `conversation_id UUID FK conversations(id) ON DELETE CASCADE`
- `role VARCHAR(20) NOT NULL` with a database check for the supported internal roles.
- `content TEXT NOT NULL`, non-empty after trimming.
- `status VARCHAR(20) NOT NULL` with constrained lifecycle values.
- `sequence BIGINT NOT NULL`, positive and unique within a conversation.
- `created_at TIMESTAMPTZ NOT NULL`
- Unique `(conversation_id, sequence)` guarantees no duplicate ordering positions.
- Index `(conversation_id, created_at)` supports history access.

### Sequence allocation

Message append locks the parent conversation row with `SELECT FOR UPDATE`, increments `last_message_sequence`, inserts the message, and updates `updated_at` in one transaction. PostgreSQL serializes concurrent writers to one conversation. The unique constraint remains the last line of defense.

### Deletion

Conversation API deletion is soft deletion through `deleted_at`; reads exclude deleted rows. Message rows remain until a defined retention/purge policy executes. Foreign keys cascade on hard deletion of a user or conversation, but ordinary API deletion does not hard-delete history.

## Implemented generation and usage tables (Milestone 5)

### generation_requests

- `id UUID PK`
- `user_id UUID FK users(id) ON DELETE CASCADE`
- `conversation_id UUID FK conversations(id) ON DELETE CASCADE`
- `user_message_id UUID FK messages(id) ON DELETE CASCADE`
- `assistant_message_id UUID FK messages(id) ON DELETE CASCADE`
- `idempotency_key VARCHAR(128) NOT NULL`
- `request_hash CHAR(64) NOT NULL` (SHA-256 of normalized caller-supplied request values)
- `provider_id VARCHAR(48) NOT NULL`, `model_id VARCHAR(128) NOT NULL` (resolved from the operator-managed model catalog)
- `status VARCHAR(20) NOT NULL` (pending/streaming/completed/failed/cancelled/interrupted)
- `error_code`, `provider_request_id`, `finish_reason` nullable
- `cancel_requested_at`, `lease_expires_at`, `started_at`, `completed_at`, `created_at`, `updated_at` TIMESTAMPTZ
- Unique `(user_id, idempotency_key)`; a partial unique index allows at most one pending/streaming generation per conversation.
- Active generation rows are locked when finalizing, checkpointing, cancelling, and recovering expired leases.

### usage_ledger

- `id UUID PK`
- `generation_id UUID UNIQUE FK generation_requests(id) ON DELETE CASCADE`
- `user_id UUID FK users(id) ON DELETE CASCADE`
- `provider_id VARCHAR(48)`, `model_id VARCHAR(128)`
- `input_tokens`, `output_tokens`, `total_tokens`, `cached_input_tokens` BIGINT NULL
- `usage_source VARCHAR(24) NOT NULL` (provider_reported/estimated/unavailable)
- `estimated_cost NUMERIC(18,10) NULL`, `currency CHAR(3) NULL`, `pricing_version VARCHAR(40) NULL`
- `created_at TIMESTAMPTZ NOT NULL`

The current implementation writes one final usage row per generation. Unknown prices remain null. If provider usage is incomplete, token counts are labelled estimated; if a worker lease expires before usage can be recovered, usage is labelled unavailable. Hard-delete cascading is retained only for explicit account/data deletion; ordinary conversation deletion is soft deletion.

### Generation/message consistency

The application inserts the user and pending assistant messages first, then inserts the generation row referencing both, within one transaction. Generation status and assistant message status intentionally use separate vocabularies: generation `completed` corresponds to assistant message `complete`.
