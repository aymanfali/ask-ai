"""Add durable generation lifecycle and usage ledger."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261115_0004"
down_revision: str | None = "20261114_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Pending/streaming assistant messages may legitimately have empty content.
    op.drop_constraint("content_not_empty", "messages", type_="check")
    op.create_check_constraint(
        "content_not_empty",
        "messages",
        "status != 'complete' OR length(trim(content)) > 0",
    )
    op.drop_constraint("content_max_length", "messages", type_="check")
    op.create_check_constraint("content_max_length", "messages", "length(content) <= 256000")

    op.create_table(
        "generation_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("user_message_id", sa.Uuid(), nullable=False),
        sa.Column("assistant_message_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("provider_id", sa.String(length=48), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("provider_request_id", sa.String(length=255), nullable=True),
        sa.Column("finish_reason", sa.String(length=80), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'streaming', 'completed', 'failed', 'cancelled', 'interrupted')",
            name="status_allowed",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_generation_requests_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], name=op.f("fk_generation_requests_conversation_id_conversations"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_message_id"], ["messages.id"], name=op.f("fk_generation_requests_user_message_id_messages"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assistant_message_id"], ["messages.id"], name=op.f("fk_generation_requests_assistant_message_id_messages"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generation_requests")),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_generation_user_idempotency"),
    )
    op.create_index(
        "ix_generation_requests_user_created",
        "generation_requests",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_generation_requests_conversation_created",
        "generation_requests",
        ["conversation_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_generation_active_conversation",
        "generation_requests",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'streaming')"),
        sqlite_where=sa.text("status IN ('pending', 'streaming')"),
    )

    op.create_table(
        "usage_ledger",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("generation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.String(length=48), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("total_tokens", sa.BigInteger(), nullable=True),
        sa.Column("cached_input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("usage_source", sa.String(length=24), nullable=False),
        sa.Column("estimated_cost", sa.Numeric(precision=18, scale=10), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("pricing_version", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("input_tokens IS NULL OR input_tokens >= 0", name="input_nonnegative"),
        sa.CheckConstraint("output_tokens IS NULL OR output_tokens >= 0", name="output_nonnegative"),
        sa.CheckConstraint("total_tokens IS NULL OR total_tokens >= 0", name="total_nonnegative"),
        sa.CheckConstraint("cached_input_tokens IS NULL OR cached_input_tokens >= 0", name="cached_input_nonnegative"),
        sa.CheckConstraint("usage_source IN ('provider_reported', 'estimated', 'unavailable')", name="usage_source_allowed"),
        sa.CheckConstraint("estimated_cost IS NULL OR estimated_cost >= 0", name="cost_nonnegative"),
        sa.ForeignKeyConstraint(["generation_id"], ["generation_requests.id"], name=op.f("fk_usage_ledger_generation_id_generation_requests"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_usage_ledger_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_ledger")),
        sa.UniqueConstraint("generation_id", name="uq_usage_ledger_generation"),
    )
    op.create_index(
        "ix_usage_ledger_user_created",
        "usage_ledger",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_usage_ledger_user_created", table_name="usage_ledger")
    op.drop_table("usage_ledger")
    op.drop_index("uq_generation_active_conversation", table_name="generation_requests")
    op.drop_index("ix_generation_requests_conversation_created", table_name="generation_requests")
    op.drop_index("ix_generation_requests_user_created", table_name="generation_requests")
    op.drop_table("generation_requests")

    op.drop_constraint("content_not_empty", "messages", type_="check")
    op.create_check_constraint("content_not_empty", "messages", "length(trim(content)) > 0")
    op.drop_constraint("content_max_length", "messages", type_="check")
    op.create_check_constraint("content_max_length", "messages", "length(content) <= 32000")
