"""Тесты валидатора ответов LLM: фильтрация телефонов, ссылок, триггеры эскалации."""

from __future__ import annotations

import pytest

from app.services.validator import (
    ESCALATION_KEYWORDS,
    MESSENGER_PATTERNS,
    PHONE_PATTERNS,
    URL_PATTERN,
    should_escalate,
    validate_and_clean,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


class TestValidateAndClean:
    """Тесты базовой очистки текста."""

    def test_clean_preserves_normal_text(self):
        """Нормальный текст без запрещённых сущностей не меняется."""
        text = "Здравствуйте! Маникюр стоит 1500 рублей. Приходите!"
        result, meta = validate_and_clean(text)
        assert result == text
        assert meta["cleaned"] is False

    def test_clean_removes_phone_russian(self):
        """Удаляет российский номер в формате +7 (XXX) XXX-XX-XX."""
        text = "Маникюр 1500₽. Звоните: +7 (900) 123-45-67"
        result, meta = validate_and_clean(text)
        assert "cleaned" in meta and meta["cleaned"] is True
        assert "900" not in result
        assert "123" not in result
        assert "4567" not in result
        assert meta["removed_phones"] >= 1

    def test_clean_removes_phone_alt_format(self):
        """Удаляет номер в формате 8XXXXXXXXXX."""
        text = "Свяжитесь: 89001234567"
        result, meta = validate_and_clean(text)
        assert meta["removed_phones"] >= 1
        assert "89001234567" not in result

    def test_clean_removes_url(self):
        """Удаляет URL-ссылки."""
        text = "Посмотрите: https://example.com/page"
        result, meta = validate_and_clean(text)
        assert "example.com" not in result
        assert meta["removed_urls"] >= 1
        assert meta["cleaned"] is True

    def test_clean_removes_www_url(self):
        """Удаляет URL с www."""
        text = "Наш сайт: www.salon.ru"
        result, meta = validate_and_clean(text)
        assert meta["removed_urls"] >= 1

    def test_clean_removes_email(self):
        """Удаляет email-адреса."""
        text = "Пишите на salon@example.com"
        result, meta = validate_and_clean(text)
        assert "salon@example.com" not in result
        assert meta["removed_urls"] >= 1

    def test_clean_removes_telegram_link(self):
        """Удаляет ссылки на Telegram."""
        text = "Наш Telegram: t.me/my_salon_bot"
        result, meta = validate_and_clean(text)
        assert "t.me" not in result
        assert meta["removed_messengers"] >= 1

    def test_clean_removes_telegram_username(self):
        """Удаляет @username Telegram."""
        text = "Наш аккаунт: @my_salon"
        result, meta = validate_and_clean(text)
        assert meta["removed_messengers"] >= 1

    def test_clean_removes_whatsapp_link(self):
        """Удаляет ссылки на WhatsApp."""
        text = "WhatsApp: wa.me/79001234567"
        result, meta = validate_and_clean(text)
        assert "wa.me" not in result
        assert meta["removed_messengers"] >= 1

    def test_clean_removes_html_tags(self):
        """Удаляет HTML-теги из ответа LLM."""
        text = "Добрый <b>день!</b> Стоимость <i>1500₽</i>."
        result, meta = validate_and_clean(text)
        assert "<b>" not in result
        assert "<i>" not in result
        assert meta["cleaned"] is True

    def test_clean_complex_response(self):
        """Сложный ответ LLM с множеством запрещённых сущностей."""
        text = """Здравствуйте! Маникюр стоит 1500₽.
Звоните: +7 (900) 123-45-67 или пишите нам в Telegram: t.me/my_salon
Наш сайт: https://salon.example.com
Скидка 10% на первое посещение!"""
        result, meta = validate_and_clean(text)
        assert "900" not in result
        assert "123" not in result
        assert "salon.example.com" not in result
        assert "t.me" not in result
        assert meta["cleaned"] is True
        assert meta["removed_phones"] >= 1
        assert meta["removed_urls"] >= 1
        assert meta["removed_messengers"] >= 1


class TestShouldEscalate:
    """Тесты определения необходимости эскалации."""

    def test_escalate_on_money(self):
        assert should_escalate(["money", "price"]) is True

    def test_escalate_on_price(self):
        assert should_escalate(["price"]) is True

    def test_escalate_on_complaint(self):
        assert should_escalate(["complaint"]) is True

    def test_no_escalate(self):
        assert should_escalate([]) is False
        assert should_escalate(["normal"]) is False


class TestTriggerKeywords:
    """Тесты срабатывания ключевых слов для эскалации."""

    def test_price_keywords(self):
        patterns = [p for k, p in ESCALATION_KEYWORDS if k == "price"]
        text = "Сколько стоит маникюр?"
        for pattern in patterns:
            assert pattern.search(text) is not None

    def test_discount_keywords(self):
        patterns = [p for k, p in ESCALATION_KEYWORDS if k == "money"]
        text = "Есть ли у вас скидка?"
        for pattern in patterns:
            assert pattern.search(text) is not None

    def test_complaint_keywords(self):
        patterns = [p for k, p in ESCALATION_KEYWORDS if k == "complaint"]
        text = "У вас ужасное обслуживание!"
        for pattern in patterns:
            assert pattern.search(text) is not None

    def test_escalation_keywords(self):
        patterns = [p for k, p in ESCALATION_KEYWORDS if k == "escalation"]
        text = "Можно поговорить с администратором?"
        for pattern in patterns:
            assert pattern.search(text) is not None
