"""Валидатор ответов LLM: фильтрация запрещённых сущностей.

Требование ТЗ: валидатор вычищает телефоны, мессенджеры, ссылки
из ответов LLM. Telegram/VK запрещают отправку внешних контактов.

Регулярные выражения настроены на русскоязычный контекст.
"""

from __future__ import annotations

import re
import typing as t
import urllib.parse

# Шаблоны для обнаружения и удаления
# Телефоны: +7 (900) 123-45-67, 89001234567, +7-900-1234567
PHONE_PATTERNS: list[tuple[str, re.Pattern]] = [
    (
        r"\+7\s*\(?(\d{3})\)?[\s.-]*(\d{3})[\s.-]*(\d{2})[\s.-]*(\d{2})",
        "+7 (\1) \2-\3-\4",
    ),
    (
        r"8\s*\(?(\d{3})\)?[\s.-]*(\d{3})[\s.-]*(\d{2})[\s.-]*(\d{2})",
        "8 (\1) \2-\3-\4",
    ),
    (
        r"\+7[-.\s]?\d{3}[-.\s]?\d{3}[-.\s]?\d{2}[-.\s]?\d{2}",
        "телефон",
    ),
    (
        r"\b8\d{10}\b",
        "телефон",
    ),
]

# Ссылки: URL, домены, email
URL_PATTERN = re.compile(
    r"(https?://|www\.|[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})"
)

# Мессенджеры: ссылки на Telegram, WhatsApp, Viber, Signal
MESSENGER_PATTERNS: list[tuple[str, re.Pattern]] = [
    (r"(t\.me/|telegram\.com/|@)([a-zA-Z0-9_]+)", "[ссылка на Telegram]"),
    (r"(wa\.me/|whatsapp\.com/)([a-zA-Z0-9_]+)", "[ссылка на WhatsApp]"),
    (r"viber\.com/([a-zA-Z0-9_]+)", "[ссылка на Viber]"),
]

# Слова-триггеры: скидка, бесплатно, доставка, акция (для эскалации)
ESCALATION_KEYWORDS: list[tuple[str, re.Pattern]] = [
    (r"\b(скидк[аоеуияй]|бесплатн[оые]|доставк[уаеыои]|акци[яю]|промокод[ае])\b", "money"),
    (r"\b(плохо|ужасн[оый]|жалоб[аа]|плохое обслуживание|отмена|вернуть деньги)\b", "complaint"),
    (r"\b(поговорит[ьсь]|связат[ьсяь]|человек|администратор|специалист|руководитель)\b", "escalation"),
    (r"\b(сколько стоит|цена|оплат[ауы]|подешевле|дешевле|скидку)\b", "price"),
]


def validate_and_clean(text: str) -> tuple[str, dict[str, t.Any]]:
    """Очистить текст от запрещённых сущностей.

    Args:
        text: Сырой текст от LLM.

    Returns:
        Кортеж (очищенный_текст, метаданные_валидации).
        metadata содержит:
            - cleaned: bool — были ли правки
            - removed_phones: int — количество удалённых телефонов
            - removed_urls: int — количество удалённых ссылок
            - triggers: list[str] — сработавшие триггеры
    """
    metadata: dict[str, t.Any] = {
        "cleaned": False,
        "removed_phones": 0,
        "removed_urls": 0,
        "removed messengers": 0,
        "triggers": [],
    }
    result = text

    # 1. Удаляем телефоны
    for pattern, replacement in PHONE_PATTERNS:
        matches = re.findall(pattern, result)
        if matches:
            metadata["removed_phones"] += len(matches)
            result = re.sub(pattern, replacement, result)
            metadata["cleaned"] = True

    # 2. Удаляем ссылки
    url_matches = URL_PATTERN.findall(result)
    if url_matches:
        metadata["removed_urls"] += len(url_matches)
        result = URL_PATTERN.sub("[удалённая ссылка]", result)
        metadata["cleaned"] = True

    # 3. Удаляем ссылки на мессенджеры
    for pattern, replacement in MESSENGER_PATTERNS:
        regex = re.compile(pattern, re.IGNORECASE)
        matches = regex.findall(result)
        if matches:
            metadata["removed_messengers"] += len(matches)
            result = regex.sub(replacement, result)
            metadata["cleaned"] = True

    # 4. Удаляем HTML-теги (бот не должен слать HTML в TG/VK)
    html_pattern = re.compile(r"<[^>]+>")
    if html_pattern.search(result):
        result = html_pattern.sub("", result)
        metadata["cleaned"] = True

    # 5. Определяем триггеры эскалации
    for keyword_pattern, trigger_type in ESCALATION_KEYWORDS:
        if re.search(keyword_pattern, result, re.IGNORECASE):
            metadata["triggers"].append(trigger_type)

    return result.strip(), metadata


def should_escalate(triggers: list[str]) -> bool:
    """Определить, нужна ли эскалация по триггерам."""
    money_triggers = {"money", "price", "complaint"}
    return bool(money_triggers & set(triggers))


__all__ = [
    "validate_and_clean",
    "should_escalate",
    "PHONE_PATTERNS",
    "URL_PATTERN",
    "MESSENGER_PATTERNS",
    "ESCALATION_KEYWORDS",
]
