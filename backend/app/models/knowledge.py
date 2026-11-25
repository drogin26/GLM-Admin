"""База знаний бизнеса для RAG.

Документ (загруженный текст) → чанки → эмбеддинги (pgvector, HNSW-индекс).
Размерность фиксирована EMBEDDING_DIM (GigaChat = 1024); смена провайдера
с другой размерностью требует миграции колонки.
"""

from __future__ import annotations

import datetime as dt
import typing as t
import uuid

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy import text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPkMixin

if t.TYPE_CHECKING:
    from app.models.business import Business

EMBEDDING_DIM = 1024  # GigaChat embeddings; менять вместе с миграцией


class KnowledgeDoc(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_docs"

    business_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    source_file: Mapped[str | None] = mapped_column(sa.String(255))
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean, default=True, server_default=text("true"), nullable=False
    )

    business: Mapped[Business] = relationship(back_populates="knowledge_docs")
    chunks: Mapped[list[KnowledgeChunk]] = relationship(
        back_populates="doc", cascade="all, delete-orphan"
    )


class KnowledgeChunk(UUIDPkMixin, Base):
    __tablename__ = "knowledge_chunks"

    doc_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("knowledge_docs.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    doc: Mapped[KnowledgeDoc] = relationship(back_populates="chunks")

    __table_args__ = (
        sa.Index(
            "ix_knowledge_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        sa.Index("ix_knowledge_chunks_doc", "doc_id"),
    )
