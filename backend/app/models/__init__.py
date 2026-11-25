"""Все ORM-модели. Импортируйте этот модуль, чтобы metadata была полной."""

from __future__ import annotations

from app.models.base import Base, TimestampMixin, UUIDPkMixin, str_enum
from app.models.billing import Subscription, UsageLog
from app.models.business import Business
from app.models.channel import Channel
from app.models.client import Client
from app.models.conversation import Conversation
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
from app.models.knowledge import EMBEDDING_DIM, KnowledgeChunk, KnowledgeDoc
from app.models.lead import Lead
from app.models.llm import LLMCallLog
from app.models.message import Message
from app.models.user import User

__all__ = [
    "Base",
    "TimestampMixin",
    "UUIDPkMixin",
    "str_enum",
    "Business",
    "User",
    "Channel",
    "Client",
    "Conversation",
    "Message",
    "KnowledgeDoc",
    "KnowledgeChunk",
    "EMBEDDING_DIM",
    "Lead",
    "Subscription",
    "UsageLog",
    "LLMCallLog",
    "PlanType",
    "ChannelType",
    "ChannelStatus",
    "ConversationStatus",
    "MessageDirection",
    "MessageSender",
    "LeadScore",
    "LeadUrgency",
    "SubscriptionStatus",
]
