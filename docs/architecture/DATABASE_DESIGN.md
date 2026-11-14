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
