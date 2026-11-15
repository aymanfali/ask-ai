"""Add conversations and ordered message history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261114_0003"
down_revision: str | None = "20261114_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "title",
            sa.String(length=200),
            server_default=sa.text("'New conversation'"),
            nullable=False,
        ),
        sa.Column("last_message_sequence", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(trim(title)) > 0", name="title_not_empty"),
        sa.CheckConstraint(
            "last_message_sequence >= 0",
            name="last_sequence_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_conversations_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
    )
    op.create_index(
        "ix_conversations_user_deleted_updated_id",
        "conversations",
        ["user_id", "deleted_at", "updated_at", "id"],
        unique=False,
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="complete", nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("sequence >= 1", name="sequence_positive"),
        sa.CheckConstraint("length(trim(content)) > 0", name="content_not_empty"),
        sa.CheckConstraint("length(content) <= 32000", name="content_max_length"),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'system', 'developer')",
            name="role_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('complete', 'pending', 'streaming', 'failed', 'cancelled', 'interrupted')",
            name="status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_messages_conversation_id_conversations",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
        sa.UniqueConstraint(
            "conversation_id", "sequence", name="uq_messages_conversation_sequence"
        ),
    )
    op.create_index(
        "ix_messages_conversation_created",
        "messages",
        ["conversation_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_messages_conversation_created", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_user_deleted_updated_id", table_name="conversations")
    op.drop_table("conversations")
