"""Перечисления домена."""

from __future__ import annotations

from enum import StrEnum


class PlanType(StrEnum):
    TRIAL = "trial"
    BASIC = "basic"
    PRO = "pro"


class ChannelType(StrEnum):
    TELEGRAM = "tg"
    VK = "vk"
    WIDGET = "widget"


class ChannelStatus(StrEnum):
    DISABLED = "disabled"
    ACTIVE = "active"
    ERROR = "error"


class ConversationStatus(StrEnum):
    NEW = "new"
    BOT = "bot"          # на контроле у бота
    HUMAN = "human"      # владелец вступил в диалог — бот молчит до выхода
    CLOSED = "closed"


class MessageDirection(StrEnum):
    IN = "in"
    OUT = "out"


class MessageSender(StrEnum):
    CLIENT = "client"
    BOT = "bot"
    HUMAN = "human"
    SYSTEM = "system"


class LeadScore(StrEnum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


class LeadUrgency(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class SubscriptionStatus(StrEnum):
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
