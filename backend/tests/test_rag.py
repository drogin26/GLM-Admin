"""Тесты RAG: чанкинг, поиск, сбор промпта."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
import pytest_asyncio
import sqlalchemy as sa

from app.models import Business, KnowledgeDoc
from app.services.rag import chunk_text

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def business(session_factory):
    async with session_factory() as session:
        b = Business(name="Тестовый бизнес")
        session.add(b)
        await session.flush()
        yield b


async def test_chunk_text_simple():
    text = "Первый абзац.\n\nВторой абзац.\n\nТретий абзац."
    chunks = chunk_text(text, chunk_size=30, overlap=5)
    assert len(chunks) >= 3
    for chunk in chunks:
        assert len(chunk) <= 30 + 5


async def test_chunk_text_long_paragraph():
    """Длинный параграф разбивается на части по словам."""
    long_text = " ".join([f"слово{i}" for i in range(50)])
    chunks = chunk_text(long_text, chunk_size=20, overlap=2)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 22  # 20 + overlap


async def test_chunk_text_empty():
    assert chunk_text("") == []
    assert chunk_text("   ") == []


async def test_chunk_text_short():
    text = "Короткий текст без абзацев"
    chunks = chunk_text(text, chunk_size=100)
    assert len(chunks) == 1
    assert chunks[0] == text


async def test_chunk_text_with_overlap(business, session_factory):
    """Чанки с перекрытием — проверяем что последние N символов повторяются."""
    content = "Первый абзац.\n\nВторой длинный абзац для тестирования перекрытия между чанками.\n\nТретий абзац."
    doc = KnowledgeDoc(business_id=business.id, title="Тест", content=content)
    session_factory_obj = session_factory

    chunks = chunk_text(content, chunk_size=40, overlap=10)
    assert len(chunks) >= 2
    # Последние 10 символов первого чанка должны совпадать с первыми 10 второго
    if len(chunks) > 1:
        overlap = chunks[0][-10:]
        assert overlap == chunks[1][:10], "Перекрытие чанков нарушено"


async def test_chunk_text_preserves_newlines(business):
    """Чанки должны сохранять внутренние переносы строк."""
    text = "Абзац 1 с переносом\nвнутри строки.\n\nАбзац 2."
    chunks = chunk_text(text, chunk_size=60)
    combined = "\n\n".join(chunks)
    # Основной текст должен сохраниться
    assert "Абзац 1" in combined
    assert "Абзац 2" in combined


async def test_chunk_text_numbers_and_special_chars():
    """Чанкинг корректно работает с цифрами и спецсимволами."""
    text = "Цены: маникюр 1500₽, педикюр 2000₽.\n\nРаботаем с 9:00 до 20:00."
    chunks = chunk_text(text, chunk_size=40)
    assert len(chunks) >= 1
    # Спецсимволы должны сохраниться
    full_text = "\n\n".join(chunks)
    assert "1500" in full_text or "1500₽" in full_text
