"""RAG (Retrieval Augmented Generation): база знаний → чанки → эмбеддинги → поиск.

Пайплайн загрузки базы знаний:
  1. Клиент загружает документ (txt/md/pdf до 10 файлов)
  2. Содержимое разбивается на чанки (по абзацам, ~500 символов с перекрытием)
  3. Каждый чанк эмбеддится через LLM-провайдер
  4. Чанки + эмбеддинги сохраняются в knowledge_chunks (pgvector, HNSW)

Пайплайн поиска при ответе:
  1. Сообщение клиента эмбеддится
  2. HNSW-поиск по pgvector: k=5 ближайших чанков
  3. Чанки формируют контекст промпта для LLM
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re
import textwrap
import typing as t
from math import floor

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import KnowledgeChunk, KnowledgeDoc
from app.services.llm import LLMProvider

logger = logging.getLogger(__name__)

# Настройки чанкинга
CHUNK_SIZE = 500       # максимальная длина чанка (символы)
CHUNK_OVERLAP = 50     # перекрытие между чанками (символы)
SEARCH_TOP_K = 5       # количество чанков для контекста


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Разбить текст на перекрывающиеся чанки.

    Алгоритм: разбиваем по абзацам, затем объединяем в чанки
    с заданным перекрытием для сохранения контекста.
    """
    # Сначала разбиваем по абзацам
    paragraphs = re.split(r"\n\s*\n", text.strip())
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    if not paragraphs:
        return []

    chunks: list[str] = []
    current_chunk = ""

    for para in paragraphs:
        # Если параграф сам по себе больше chunk_size — разбиваем на части
        if len(para) > chunk_size:
            # Сначала добавляем current_chunk если есть
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""

            # Разбиваем длинный параграф по словам
            words = para.split()
            parts: list[str] = []
            current_part = ""
            for word in words:
                test = current_part + (" " if current_part else "") + word
                if len(test) > chunk_size:
                    if current_part:
                        parts.append(current_part)
                    current_part = word
                else:
                    current_part = test
            if current_part:
                parts.append(current_part)

            chunks.extend(parts)
            continue

        # Если текущий чанк + новый параграф не превышает лимит — объединяем
        separator = "\n\n" if current_chunk else ""
        if len(current_chunk) + len(separator) + len(para) <= chunk_size:
            current_chunk = current_chunk + separator + para
        else:
            if current_chunk:
                chunks.append(current_chunk)
            # Перекрытие: берём последние N символов
            if overlap > 0 and len(current_chunk) > overlap:
                overlap_text = current_chunk[-overlap:]
                current_chunk = overlap_text + para
            else:
                current_chunk = para

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


async def embed_chunks(
    chunks: list[str],
    provider: LLMProvider,
    batch_size: int = 10,
) -> list[list[float]]:
    """Параллельная генерация эмбеддингов для чанков."""
    all_embeddings: list[list[float]] = []

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        tasks = [provider.embed(chunk) for chunk in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.error("embed_chunk_failed", extra={"error": str(result)})
                all_embeddings.append([0.0] * 1024)  # Заглушка при ошибке
            else:
                all_embeddings.append(result)

    return all_embeddings


async def upsert_chunks(
    session: AsyncSession,
    doc_id: sa.Column,  # type: ignore[name-defined]
    chunks_with_embeddings: list[tuple[int, str, list[float]]],
) -> int:
    """Сохранить/обновить чанки документа.

    Удаляет старые чанки и вставляет новые (атомарная замена).
    Возвращает количество вставленных чанков.
    """
    from app.models.knowledge import EMBEDDING_DIM

    # Удаляем старые чанки этого документа
    await session.execute(
        sa.delete(KnowledgeChunk).where(KnowledgeChunk.doc_id == doc_id)
    )

    if not chunks_with_embeddings:
        return 0

    # batch insert
    now = dt.datetime.now(dt.UTC)
    values = [
        {
            "doc_id": doc_id,
            "chunk_index": idx,
            "content": content,
            "embedding": embedding,
            "created_at": now,
        }
        for idx, (idx, content, embedding) in enumerate(chunks_with_embeddings)
    ]

    # Использование insert().on_conflict_do_nothing() для pgvector
    stmt = pg_insert(KnowledgeChunk).values(values)
    stmt = stmt.on_conflict_do_nothing(
        index_elements=["id"],  # primary key
    )
    await session.execute(stmt)

    inserted = len(chunks_with_embeddings)
    logger.info("chunks_upserted", extra={"doc_id": str(doc_id), "count": inserted})
    return inserted


async def search_similar_chunks(
    session: AsyncSession,
    business_id: sa.Column,  # type: ignore[name-defined]
    query_embedding: list[float],
    top_k: int = SEARCH_TOP_K,
) -> list[tuple[KnowledgeChunk, float]]:
    """Поиск наиболее релевантных чанков базы знаний.

    Использует HNSW-индекс pgvector для быстрого cosine similarity поиска.
    """
    from app.models.knowledge import EMBEDDING_DIM

    # Нормализация вектора
    magnitude = sum(v * v for v in query_embedding) ** 0.5
    if magnitude > 0:
        normalized = [v / magnitude for v in query_embedding]
    else:
        normalized = query_embedding

    # HNSW cosine similarity search
    result = await session.execute(
        sa.select(
            KnowledgeChunk,
            KnowledgeChunk.embedding.cosine_distance(normalized).label("distance"),
        )
        .where(KnowledgeChunk.doc_id.in_(
            sa.select(KnowledgeDoc.id).where(
                KnowledgeDoc.business_id == business_id,
                KnowledgeDoc.is_active == True,  # noqa: E712
            )
        ))
        .order_by(sa.text("distance ASC"))
        .limit(top_k)
    )

    rows = result.all()
    # Чем меньше distance — тем ближе (cosine_distance = 1 - cosine_similarity)
    return [(chunk, round(float(dist), 4)) for chunk, dist in rows]


async def build_rag_prompt(
    session: AsyncSession,
    business_id: sa.Column,  # type: ignore[name-defined]
    user_message: str,
    provider: LLMProvider,
    system_instructions: str,
) -> str:
    """Собрать полный промпт для RAG.

    Структура промпта (жесткая, см. ТЗ жёсткие запреты):
    1. Системные инструкции (роль, правила компании, жёсткие запреты)
    2. Контекст из базы знаний (n релевантных чанков)
    3. Последние N сообщений диалога (контекст беседы)
    4. Пользовательское сообщение
    """
    # Получаем эмбеддинг запроса
    query_embedding = await provider.embed(user_message)

    # Ищем релевантные чанки
    similar = await search_similar_chunks(session, business_id, query_embedding)

    if not similar:
        # Нет релевантных чанков — используем только системный промпт
        logger.info("rag_no_chunks_found")
        return f"{system_instructions}\n\nПользователь: {user_message}"

    # Формируем контекст из чанков
    context_parts: list[str] = []
    for chunk, distance in similar:
        if distance > 0.7:  # Порог релевантности: cosine_similarity < 0.3
            continue
        context_parts.append(chunk.content)

    context = "\n\n".join(context_parts) if context_parts else "Нет релевантной информации в базе знаний."

    # Полный промпт
    rag_prompt = f"""{system_instructions}

=== КОНТЕКСТ ИЗ БАЗЫ ЗНАНИЙ ===
{context}

=== ДИАЛОГ С КЛИЕНТОМ ===

Пользователь: {user_message}

Ответь клиенту, используя только информацию из базы знаний. Не выдумывай."""

    return rag_prompt


async def process_knowledge_doc(
    session: AsyncSession,
    doc: KnowledgeDoc,
    provider: LLMProvider,
) -> int:
    """Обработать новый документ: чанкинг → эмбеддинги → сохранение."""
    # Чанкинг
    chunks_text = chunk_text(doc.content)
    logger.info("document_chunked", extra={"doc_id": str(doc.id), "doc_title": doc.title, "chunks": len(chunks_text)})

    if not chunks_text:
        return 0

    # Эмбеддинги
    embeddings = await embed_chunks(chunks_text, provider)

    # Сохранение
    indexed_chunks = list(enumerate(zip(range(len(chunks_text)), chunks_text, embeddings)))
    count = await upsert_chunks(session, doc.id, indexed_chunks)

    logger.info("document_processed", extra={"doc_id": str(doc.id), "chunks_saved": count})
    return count


async def delete_doc_chunks(session: AsyncSession, doc_id: sa.Column) -> None:  # type: ignore[name-defined]
    """Удалить чанки документа (при деактивации)."""
    await session.execute(sa.delete(KnowledgeChunk).where(KnowledgeChunk.doc_id == doc_id))
    logger.info("chunks_deleted", extra={"doc_id": str(doc_id)})


__all__ = [
    "chunk_text",
    "embed_chunks",
    "upsert_chunks",
    "search_similar_chunks",
    "build_rag_prompt",
    "process_knowledge_doc",
    "delete_doc_chunks",
    "CHUNK_SIZE",
    "CHUNK_OVERLAP",
    "SEARCH_TOP_K",
]
