"""Кабинет: API маршруты для фронтенд Next.js.

Маршруты:
  POST /api/auth/register  — регистрация нового бизнеса
  POST /api/auth/login     — вход в кабинет
  GET  /api/business       — данные текущего бизнеса
  PUT  /api/business       — обновление настроек

  POST /api/onboarding/step/{step}  — онбординг-визард (шаг за шагом)
  GET  /api/onboarding/status       — статус прохождения онбординга

  GET  /api/conversations          — список диалогов с фильтрами
  GET  /api/conversations/{id}     — диалог с сообщениями
  POST /api/conversations/{id}/reply  — ответ от администратора

  GET  /api/knowledge/docs        — список документов
  POST /api/knowledge/docs        — загрузка нового документа
  DELETE /api/knowledge/docs/{id}  — удаление/деактивация

  GET  /api/dashboard            — дашборд с метриками
  GET  /api/dashboard/lost-leads — отчёт «Потерянные заявки»

  GET  /api/billing/plans        — список тарифов
  GET  /api/billing/subscription — текущая подписка
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.auth import TokenData, create_access_token, get_current_user, LoginRequest
from app.api.deps import get_session
from app.models import (
    Business,
    Channel,
    ChannelStatus,
    ChannelType,
    Conversation,
    ConversationStatus,
    KnowledgeDoc,
    Message,
    MessageDirection,
    MessageSender,
    PlanType,
    Subscription,
    SubscriptionStatus,
    User,
    UsageLog,
)
from app.security import hash_password
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)
router = APIRouter(tags=["cabinet"])


# ======================== Аутентификация ========================


@router.post("/auth/register")
async def register(
    email: str,
    password: str,
    business_name: str,
    session: AsyncSession = None,  # type: ignore[assignment]
    user: dict = None,  # type: ignore[assignment]
) -> dict[str, str]:
    """Регистрация нового бизнеса и пользователя."""
    from sqlalchemy import select

    # Проверяем email
    result = await session.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email уже зарегистрирован")

    # Создаём бизнес
    business = Business(name=business_name)
    session.add(business)
    await session.flush()

    # Создаём пользователя
    user_obj = User(
        email=email,
        password_hash=hash_password(password),
        role="owner",
        business_id=business.id,
    )
    session.add(user_obj)
    await session.flush()

    # Создаём триггер подписки
    subscription = Subscription(
        business_id=business.id,
        plan=PlanType.TRIAL,
        status=SubscriptionStatus.TRIALING,
        period_end=dt.datetime.now(dt.UTC) + dt.timedelta(days=14),
    )
    session.add(subscription)

    await session.commit()

    token = create_access_token(user_obj.id, business.id, user_obj.role)
    return {"access_token": token, "token_type": "bearer"}


@router.post("/auth/login")
async def login(
    request: LoginRequest,
    session: AsyncSession = None,  # type: ignore[assignment]
) -> dict[str, str]:
    """Вход в кабинет."""
    from app.security import verify_password

    result = await session.execute(select(User).where(User.email == request.email))
    user_obj = result.scalar_one_or_none()

    if not user_obj or not verify_password(request.password, user_obj.password_hash):
        raise HTTPException(status_code=401, detail="Неверный email или пароль")

    if not user_obj.is_active:
        raise HTTPException(status_code=403, detail="Аккаунт заблокирован")

    token = create_access_token(user_obj.id, user_obj.business_id, user_obj.role)
    return {"access_token": token, "token_type": "bearer"}


# ======================== Бизнес ========================


@router.get("/business")
async def get_business(
    user: dict = Depends(get_current_user),
    session: AsyncSession = None,  # type: ignore[assignment]
) -> dict:
    """Данные текущего бизнеса."""
    business_id = user["business_id"]
    if not business_id:
        raise HTTPException(status_code=400, detail="User not linked to a business")

    result = await session.execute(
        select(Business).where(Business.id == business_id).options(selectinload(Business.subscription))
    )
    business = result.scalar_one_or_none()
    if not business:
        raise HTTPException(status_code=404, detail="Бизнес не найден")

    return {
        "id": str(business.id),
        "name": business.name,
        "plan": business.plan.value,
        "auto_mode": business.auto_mode,
        "telegram_notify_chat_id": business.telegram_notify_chat_id,
        "working_hours": business.working_hours,
        "settings": business.settings,
        "subscription": {
            "plan": business.subscription.plan.value if business.subscription else None,
            "status": business.subscription.status.value if business.subscription else None,
            "period_end": business.subscription.period_end.isoformat() if business.subscription and business.subscription.period_end else None,
        },
    }


@router.put("/business")
async def update_business(
    data: dict,
    user: dict = Depends(get_current_user),
    session: AsyncSession = None,  # type: ignore[assignment]
) -> dict:
    """Обновление настроек бизнеса."""
    business_id = user["business_id"]
    if not business_id:
        raise HTTPException(status_code=400, detail="User not linked to a business")

    result = await session.execute(select(Business).where(Business.id == business_id))
    business = result.scalar_one_or_none()
    if not business:
        raise HTTPException(status_code=404, detail="Бизнес не найден")

    if "name" in data:
        business.name = data["name"]
    if "auto_mode" in data:
        business.auto_mode = data["auto_mode"]
    if "telegram_notify_chat_id" in data:
        business.telegram_notify_chat_id = data["telegram_notify_chat_id"]
    if "working_hours" in data:
        business.working_hours = data["working_hours"]
    if "settings" in data:
        business.settings = data["settings"]

    await session.commit()
    return {"status": "ok"}


# ======================== Онбординг ========================


class OnboardingStepRequest(BaseModel):
    """Общая структура для шагов онбординга."""
    step: str  # telegram, vk, widget, knowledge, mode, notify
    data: dict = {}


@router.post("/onboarding/step/{step}")
async def onboarding_step(
    step: str,
    data: dict = {},
    user: dict = Depends(get_current_user),
    session: AsyncSession = None,  # type: ignore[assignment]
) -> dict:
    """Обработка шага онбординга."""
    business_id = user["business_id"]
    if not business_id:
        raise HTTPException(status_code=400, detail="User not linked to a business")

    if step == "telegram":
        # Подключение Telegram-бота
        from app.security import encrypt_credentials

        token = data.get("bot_token", "")
        if not token:
            raise HTTPException(status_code=400, detail="Не указан токен бота")

        channel = Channel(
            business_id=business_id,
            type=ChannelType.TELEGRAM,
            credentials_enc=encrypt_credentials({"token": token}, []),  # type: ignore[arg-type]
            status=ChannelStatus.ACTIVE,
            external_id="telegram_bot",
        )
        session.add(channel)

    elif step == "vk":
        # Подключение VK группы
        from app.security import encrypt_credentials

        token = data.get("group_token", "")
        group_id = data.get("group_id", "")
        if not token:
            raise HTTPException(status_code=400, detail="Не указан токен группы")

        channel = Channel(
            business_id=business_id,
            type=ChannelType.VK,
            credentials_enc=encrypt_credentials({"token": token, "group_id": group_id}, []),  # type: ignore[arg-type]
            status=ChannelStatus.ACTIVE,
            external_id=group_id,
        )
        session.add(channel)

    elif step == "mode":
        result = await session.execute(select(Business).where(Business.id == business_id))
        business = result.scalar_one_or_none()
        if business:
            business.auto_mode = data.get("auto_mode", False)

    await session.commit()
    return {"status": "ok", "step": step}


@router.get("/onboarding/status")
async def onboarding_status(
    user: dict = Depends(get_current_user),
    session: AsyncSession = None,  # type: ignore[assignment]
) -> dict:
    """Статус прохождения онбординга."""
    business_id = user["business_id"]
    if not business_id:
        raise HTTPException(status_code=400, detail="User not linked to a business")

    result = await session.execute(
        select(Channel).where(Channel.business_id == business_id)
    )
    channels = result.scalars().all()
    channel_types = {c.type for c in channels}

    return {
        "completed": {
            "telegram": ChannelType.TELEGRAM in channel_types,
            "vk": ChannelType.VK in channel_types,
            "widget": ChannelType.WIDGET in channel_types,
        },
        "auto_mode": None,  # Будет заполнено из настроек бизнеса
    }


# ======================== Инбокс ========================


@router.get("/conversations")
async def list_conversations(
    status_filter: str = "all",  # new, bot, human, closed
    user: dict = Depends(get_current_user),
    session: AsyncSession = None,  # type: ignore[assignment]
) -> dict:
    """Список диалогов с фильтрами."""
    business_id = user["business_id"]
    if not business_id:
        raise HTTPException(status_code=400, detail="User not linked to a business")

    query = select(Conversation).where(
        Conversation.business_id == business_id
    ).order_by(Conversation.last_msg_at.desc()).limit(100)

    if status_filter != "all":
        status_enum = getattr(ConversationStatus, status_filter.upper(), None)
        if status_enum:
            query = query.where(Conversation.status == status_enum)

    result = await session.execute(query)
    conversations = result.scalars().all()

    return {
        "conversations": [
            {
                "id": str(c.id),
                "client_name": c.client_name,
                "client_phone": c.client_phone,
                "status": c.status.value,
                "last_msg_at": c.last_msg_at.isoformat() if c.last_msg_at else None,
                "channel": c.channel.type.value if c.channel else None,
                "unread": False,  # Placeholder
            }
            for c in conversations
        ]
    }


@router.get("/conversations/{conv_id}")
async def get_conversation(
    conv_id: str,
    user: dict = Depends(get_current_user),
    session: AsyncSession = None,  # type: ignore[assignment]
) -> dict:
    """Диалог с сообщениями."""
    business_id = user["business_id"]
    conv_uuid = uuid.UUID(conv_id)

    # Проверяем принадлежность бизнесу
    conv_result = await session.execute(
        select(Conversation).where(
            Conversation.id == conv_uuid,
            Conversation.business_id == business_id,
        )
    )
    conversation = conv_result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Диалог не найден")

    # Получаем сообщения
    msgs_result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conv_uuid)
        .order_by(Message.created_at)
    )
    messages = msgs_result.scalars().all()

    return {
        "id": str(conversation.id),
        "client_name": conversation.client_name,
        "client_phone": conversation.client_phone,
        "status": conversation.status.value,
        "messages": [
            {
                "id": str(m.id),
                "direction": m.direction.value,
                "sender": m.sender.value,
                "text": m.text,
                "created_at": m.created_at.isoformat(),
                "is_draft": m.llm_metadata.get("is_draft", False) if m.llm_metadata else False,
            }
            for m in messages
        ],
    }


@router.post("/conversations/{conv_id}/reply")
async def reply_to_conversation(
    conv_id: str,
    data: dict,
    user: dict = Depends(get_current_user),
    session: AsyncSession = None,  # type: ignore[assignment]
) -> dict:
    """Ответ от администратора (человека)."""
    business_id = user["business_id"]
    conv_uuid = uuid.UUID(conv_id)

    text = data.get("text", "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Текст ответа обязателен")

    # Проверяем принадлежность
    conv_result = await session.execute(
        select(Conversation).where(
            Conversation.id == conv_uuid,
            Conversation.business_id == business_id,
        )
    )
    conversation = conv_result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Диалог не найден")

    # Отправляем сообщение
    msg = Message(
        conversation_id=conv_uuid,
        direction=MessageDirection.OUT,
        sender=MessageSender.HUMAN,
        text=text,
    )
    session.add(msg)

    conversation.status = ConversationStatus.HUMAN
    conversation.last_msg_at = dt.datetime.now(dt.UTC)

    await session.commit()

    return {"status": "ok", "message_id": str(msg.id)}


# ======================== База знаний ========================


@router.get("/knowledge/docs")
async def list_knowledge_docs(
    user: dict = Depends(get_current_user),
    session: AsyncSession = None,  # type: ignore[assignment]
) -> dict:
    """Список документов базы знаний."""
    business_id = user["business_id"]
    result = await session.execute(
        select(KnowledgeDoc).where(
            KnowledgeDoc.business_id == business_id
        ).order_by(KnowledgeDoc.created_at.desc())
    )
    docs = result.scalars().all()

    return {
        "docs": [
            {
                "id": str(d.id),
                "title": d.title,
                "is_active": d.is_active,
                "source_file": d.source_file,
                "created_at": d.created_at.isoformat(),
            }
            for d in docs
        ]
    }


@router.post("/knowledge/docs")
async def upload_knowledge_doc(
    title: str,
    content: str,
    source_file: str = "",
    user: dict = Depends(get_current_user),
    session: AsyncSession = None,  # type: ignore[assignment]
) -> dict:
    """Загрузка нового документа."""
    business_id = user["business_id"]

    doc = KnowledgeDoc(
        business_id=business_id,
        title=title,
        content=content,
        source_file=source_file or None,
        is_active=True,
    )
    session.add(doc)
    await session.flush()

    # Триггерим обработку чанков (Celery задача — итерация 9)
    # celery_app.send_task("knowledge.process_doc", args=[str(doc.id)])

    await session.commit()
    return {"id": str(doc.id), "status": "ok"}


@router.delete("/knowledge/docs/{doc_id}")
async def deactivate_knowledge_doc(
    doc_id: str,
    user: dict = Depends(get_current_user),
    session: AsyncSession = None,  # type: ignore[assignment]
) -> dict:
    """Деактивация документа."""
    doc_uuid = uuid.UUID(doc_id)
    business_id = user["business_id"]

    result = await session.execute(
        select(KnowledgeDoc).where(
            KnowledgeDoc.id == doc_uuid,
            KnowledgeDoc.business_id == business_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Документ не найден")

    doc.is_active = False
    await session.commit()
    return {"status": "ok"}


# ======================== Дашборд ========================


@router.get("/dashboard")
async def dashboard(
    user: dict = Depends(get_current_user),
    session: AsyncSession = None,  # type: ignore[assignment]
) -> dict:
    """Дашборд с метриками."""
    business_id = user["business_id"]
    now = dt.datetime.now(dt.UTC)
    week_ago = now - dt.timedelta(days=7)
    month_ago = now - dt.timedelta(days=30)

    # Общие счётчики
    total_convs = await session.scalar(
        select(func.count(Conversation.id)).where(
            Conversation.business_id == business_id,
            Conversation.created_at >= week_ago,
        )
    ) or 0

    bot_answered = await session.scalar(
        select(func.count(Message.id)).where(
            Message.conversation_id.in_(
                select(Conversation.id).where(
                    Conversation.business_id == business_id,
                    Conversation.created_at >= week_ago,
                )
            ),
            Message.direction == MessageDirection.OUT,
            Message.sender == MessageSender.BOT,
        )
    ) or 0

    human_handoff = await session.scalar(
        select(func.count(Conversation.id)).where(
            Conversation.business_id == business_id,
            Conversation.status == ConversationStatus.HUMAN,
            Conversation.last_msg_at >= week_ago,
        )
    ) or 0

    # Потерянные заявки (без ответа > 1 часа)
    lost_since = now - dt.timedelta(hours=1)
    lost_count = await session.scalar(
        select(func.count(Conversation.id)).where(
            Conversation.business_id == business_id,
            Conversation.status == ConversationStatus.NEW,
            Conversation.last_msg_at <= lost_since,
        )
    ) or 0

    # Вне рабочих часов
    after_hours_count = 0  # Placeholder — нужно сравнить с working_hours

    # Средняя стоимость заказа
    avg_order = 0
    business_result = await session.execute(
        select(Business.settings["avg_order_price"].as_string()).where(Business.id == business_id)
    )
    avg_order_val = business_result.scalar()
    if avg_order_val:
        try:
            avg_order = float(avg_order_val)
        except (ValueError, TypeError):
            pass

    estimated_lost_revenue = lost_count * avg_order

    return {
        "total_conversations": total_convs,
        "bot_answered": bot_answered,
        "human_handoff": human_handoff,
        "lost_conversations": lost_count,
        "avg_response_time": "—",  # Placeholder
        "estimated_lost_revenue": round(estimated_lost_revenue, 2),
        "avg_order_price": avg_order,
    }


@router.get("/dashboard/lost-leads")
async def lost_leads_report(
    user: dict = Depends(get_current_user),
    session: AsyncSession = None,  # type: ignore[assignment]
    period_days: int = 7,
) -> dict:
    """Отчёт «Потерянные заявки» за период."""
    business_id = user["business_id"]
    period_start = dt.datetime.now(dt.UTC) - dt.timedelta(days=period_days)

    # Конверсации без ответа
    result = await session.execute(
        select(Conversation)
        .where(
            Conversation.business_id == business_id,
            Conversation.status == ConversationStatus.NEW,
            Conversation.created_at >= period_start,
        )
        .order_by(Conversation.created_at.desc())
    )
    conversations = result.scalars().all()

    total = len(conversations)
    still_unanswered = sum(1 for c in conversations if c.last_msg_at and c.last_msg_at < period_start)

    business_result = await session.execute(select(Business).where(Business.id == business_id))
    business = business_result.scalar_one_or_none()
    avg_order = 0
    if business and business.settings.get("avg_order_price"):
        try:
            avg_order = float(business.settings["avg_order_price"])
        except (ValueError, TypeError):
            pass

    return {
        "period_days": period_days,
        "total_messages": total,
        "still_unanswered": still_unanswered,
        "estimated_lost_revenue": round(still_unanswered * avg_order, 2),
        "avg_order_price": avg_order,
    }


# ======================== Биллинг ========================


@router.get("/billing/plans")
async def list_plans() -> list[dict]:
    """Список тарифов."""
    return [
        {
            "id": PlanType.TRIAL.value,
            "name": "Триал",
            "price_rub": 0,
            "dialog_limit": 50,
            "description": "14 дней бесплатно, до 50 диалогов",
        },
        {
            "id": PlanType.BASIC.value,
            "name": "Basic",
            "price_rub": 3900,
            "dialog_limit": 300,
            "description": "До 300 диалогов в месяц",
        },
        {
            "id": PlanType.PRO.value,
            "name": "Pro",
            "price_rub": 5990,
            "dialog_limit": -1,  # безлимит
            "description": "Безлимитные диалоги",
        },
    ]


@router.get("/billing/subscription")
async def get_subscription(
    user: dict = Depends(get_current_user),
    session: AsyncSession = None,  # type: ignore[assignment]
) -> dict:
    """Текущая подписка."""
    business_id = user["business_id"]
    result = await session.execute(
        select(Subscription).where(Subscription.business_id == business_id)
    )
    sub = result.scalar_one_or_none()

    if not sub:
        return {"exists": False}

    # Считаем использование за текущий период
    usage_count = await session.scalar(
        select(func.count(UsageLog.id)).where(
            UsageLog.business_id == business_id,
            UsageLog.action == "llm_reply",
            UsageLog.created_at >= sub.period_end - dt.timedelta(days=30) if sub.period_end else dt.datetime.min.replace(tzinfo=dt.UTC),
        )
    ) or 0

    return {
        "exists": True,
        "plan": sub.plan.value,
        "status": sub.status.value,
        "period_end": sub.period_end.isoformat() if sub.period_end else None,
        "auto_renew": sub.auto_renew,
        "usage_count": usage_count,
    }
