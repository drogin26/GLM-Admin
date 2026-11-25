"""Каркас: все таблицы MVP (businesses, users, channels, clients, conversations,
messages, knowledge_docs, knowledge_chunks, leads, subscriptions, usage_logs, llm_calls).

Revision ID: 0001
Revises:
Create Date: 2026-11-24
"""

from __future__ import annotations

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op
from app.models.base import str_enum
from app.models.enums import (
    ChannelStatus,
    ChannelType,
    ConversationStatus,
    LeadScore,
    LeadUrgency,
    MessageDirection,
    MessageSender,
    PlanType,
    SubscriptionStatus,
)
from app.models.knowledge import EMBEDDING_DIM

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None

UUID_COL = UUID(as_uuid=True)
NOW = sa.text("now()")
JSONB_EMPTY = sa.text("'{}'::jsonb")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "businesses",
        sa.Column("id", UUID_COL, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("plan", str_enum(PlanType), server_default=sa.text("'trial'"), nullable=False),
        sa.Column("telegram_notify_chat_id", sa.String(64), nullable=True),
        sa.Column("working_hours", JSONB, server_default=JSONB_EMPTY, nullable=False),
        sa.Column("auto_mode", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("settings", JSONB, server_default=JSONB_EMPTY, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_businesses")),
    )

    op.create_table(
        "users",
        sa.Column("id", UUID_COL, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), server_default=sa.text("'owner'"), nullable=False),
        sa.Column("business_id", UUID_COL, sa.ForeignKey("businesses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "channels",
        sa.Column("id", UUID_COL, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("business_id", UUID_COL, sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", str_enum(ChannelType), nullable=False),
        sa.Column("credentials_enc", JSONB, nullable=True),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("status", str_enum(ChannelStatus), server_default=sa.text("'disabled'"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_channels")),
        sa.UniqueConstraint("business_id", "type", name="uq_channels_business_type"),
    )

    op.create_table(
        "clients",
        sa.Column("id", UUID_COL, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("business_id", UUID_COL, sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("external_refs", JSONB, server_default=JSONB_EMPTY, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clients")),
    )
    op.create_index("ix_clients_business_phone", "clients", ["business_id", "phone"], unique=True)

    op.create_table(
        "conversations",
        sa.Column("id", UUID_COL, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("business_id", UUID_COL, sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", UUID_COL, sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", UUID_COL, sa.ForeignKey("clients.id", ondelete="SET NULL"), nullable=True),
        sa.Column("external_chat_id", sa.String(255), nullable=False),
        sa.Column("client_name", sa.String(255), nullable=True),
        sa.Column("client_phone", sa.String(32), nullable=True),
        sa.Column("status", str_enum(ConversationStatus), server_default=sa.text("'new'"), nullable=False),
        sa.Column("last_msg_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
        sa.UniqueConstraint("channel_id", "external_chat_id", name="uq_conversations_channel_chat"),
    )
    op.create_index("ix_conversations_business_status", "conversations", ["business_id", "status"])
    op.create_index("ix_conversations_last_msg_at", "conversations", ["last_msg_at"])

    op.create_table(
        "messages",
        sa.Column("id", UUID_COL, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("conversation_id", UUID_COL, sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("direction", str_enum(MessageDirection), nullable=False),
        sa.Column("sender", str_enum(MessageSender), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=True),
        sa.Column("llm_metadata", JSONB, server_default=JSONB_EMPTY, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
        sa.UniqueConstraint("conversation_id", "external_id", name="uq_messages_conversation_external"),
    )
    op.create_index("ix_messages_conversation_created", "messages", ["conversation_id", "created_at"])
    op.create_index(op.f("ix_messages_created_at"), "messages", ["created_at"])

    op.create_table(
        "knowledge_docs",
        sa.Column("id", UUID_COL, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("business_id", UUID_COL, sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_file", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_docs")),
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", UUID_COL, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("doc_id", UUID_COL, sa.ForeignKey("knowledge_docs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_chunks")),
    )
    op.create_index("ix_knowledge_chunks_embedding", "knowledge_chunks", ["embedding"],
                   postgresql_using="hnsw", postgresql_ops={"embedding": "vector_cosine_ops"})
    op.create_index("ix_knowledge_chunks_doc", "knowledge_chunks", ["doc_id"])

    op.create_table(
        "leads",
        sa.Column("id", UUID_COL, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("conversation_id", UUID_COL, sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("urgency", str_enum(LeadUrgency), server_default=sa.text("'normal'"), nullable=False),
        sa.Column("city", sa.String(128), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("score", str_enum(LeadScore), server_default=sa.text("'warm'"), nullable=False),
        sa.Column("extra", JSONB, server_default=JSONB_EMPTY, nullable=False),
        sa.Column("notified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_leads")),
    )
    op.create_index("ix_leads_conversation", "leads", ["conversation_id"])
    op.create_index("ix_leads_notified", "leads", ["notified"])

    op.create_table(
        "subscriptions",
        sa.Column("id", UUID_COL, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("business_id", UUID_COL, sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan", str_enum(PlanType), nullable=False),
        sa.Column("status", str_enum(SubscriptionStatus), server_default=sa.text("'trialing'"), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_renew", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
        sa.UniqueConstraint("business_id", name="uq_subscriptions_business_id"),
    )

    op.create_table(
        "usage_logs",
        sa.Column("id", UUID_COL, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("business_id", UUID_COL, sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("llm_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("meta", JSONB, server_default=JSONB_EMPTY, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_logs")),
    )
    op.create_index("ix_usage_logs_business_created", "usage_logs", ["business_id", "created_at"])
    op.create_index("ix_usage_logs_business_action", "usage_logs", ["business_id", "action"])

    op.create_table(
        "llm_calls",
        sa.Column("id", UUID_COL, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("conversation_id", UUID_COL, sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("prompt_hash", sa.String(64), nullable=False),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("escalated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("tokens_in", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_calls")),
    )
    op.create_index("ix_llm_calls_conversation", "llm_calls", ["conversation_id"])


def downgrade() -> None:
    # Расширение vector не удаляем: им могут пользоваться другие базы инстанса.
    op.drop_table("llm_calls")
    op.drop_table("usage_logs")
    op.drop_table("subscriptions")
    op.drop_table("leads")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_docs")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("clients")
    op.drop_table("channels")
    op.drop_table("users")
    op.drop_table("businesses")
