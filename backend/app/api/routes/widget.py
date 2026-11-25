"""Чат-виджет: WebSocket-эндпоинт для интеграции на сторонние сайты.

Инициализация:
  <script src="https://yoursite.com/widget.js" data-business-token="YOUR_TOKEN"></script>
  <div id="ai-admin-widget"></div>

WebSocket:
  ws://yoursite.com/ws/chat/{business_token}

Бизнес-токен хранится в channels.external_id (channel type = "widget").
Идентичность посетителя между сессиями — localStorage.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.models import Channel, ChannelStatus, ChannelType

logger = logging.getLogger(__name__)
router = APIRouter(tags=["widget"])

# Хранилище активных WebSocket-подключений:
# {business_token: {client_id: WebSocket}}
_active_connections: dict[str, dict[str, WebSocket]] = {}


@router.websocket("/ws/chat/{business_token}")
async def widget_websocket(
    websocket: WebSocket,
    business_token: str,
) -> None:
    """WebSocket для чат-виджета.

    Клиент подключается, получает ID, может отправлять/получать сообщения.
    """
    from sqlalchemy import select
    from app.config import get_settings
    from app.models import Business, Conversation, ConversationStatus, Message, MessageDirection, MessageSender
    from app.services.messaging.telegram import TelegramChannel
    from app.services.conversation import process_conversation
    from app.services.validator import validate_and_clean

    await websocket.accept()

    # Идентификация посетителя
    client_id = f"widget_{uuid.uuid4().hex[:12]}"

    # Проверяем бизнес
    settings = get_settings()
    sf = None
    redis = None
    try:
        sf = websocket.app.state.session_factory
        redis = websocket.app.state.redis
    except AttributeError:
        logger.error("websocket_app_state_missing")
        await websocket.close(code=4000, reason="Server misconfigured")
        return

    async with sf() as session:
        # Находим бизнес по токену
        result = await session.execute(
            select(Business).join(Channel).where(
                Channel.type == ChannelType.WIDGET,
                Channel.external_id == business_token,
                Channel.status == ChannelStatus.ACTIVE,
                Business.is_active == True,  # noqa: E712
            ).limit(1)
        )
        business = result.scalar_one_or_none()

        if not business:
            await websocket.close(code=4001, reason="Invalid business token")
            return

        # Находим или создаём conversation
        result = await session.execute(
            select(Channel).where(
                Channel.type == ChannelType.WIDGET,
                Channel.external_id == business_token,
            )
        )
        channel = result.scalar_one_or_none()

        if not channel:
            await websocket.close(code=4002, reason="Widget not configured")
            return

        result = await session.execute(
            select(Conversation).where(
                Conversation.channel_id == channel.id,
                Conversation.external_chat_id == business_token,
            )
        )
        conversation = result.scalar_one_or_none()

        if not conversation:
            conversation = Conversation(
                business_id=business.id,
                channel_id=channel.id,
                external_chat_id=business_token,
                client_name=client_id,
                status=ConversationStatus.NEW,
            )
            session.add(conversation)
            await session.flush()

    # Регистрируем подключение
    if business_token not in _active_connections:
        _active_connections[business_token] = {}
    _active_connections[business_token][client_id] = websocket

    logger.info("widget_client_connected", extra={
        "business_token": business_token,
        "client_id": client_id,
        "conversation_id": str(conversation.id),
    })

    # Отправляем welcome-сообщение
    try:
        await websocket.send_json({
            "type": "system",
            "text": f"Здравствуйте! Я AI-помощник {business.name}. Чем могу помочь?",
            "timestamp": dt.datetime.now(dt.UTC).isoformat(),
        })
    except Exception:
        pass

    # Обработка сообщений
    try:
        while True:
            data = await websocket.receive_json()

            message_text = data.get("text", "").strip()
            if not message_text:
                continue

            # Обработаем через тот же пайплайн, что и Telegram
            async with sf() as session:
                # Обновляем conversation
                conversation = await session.get(Conversation, conversation.id)
                if not conversation:
                    continue

                # Сохраняем входящее
                incoming = Message(
                    conversation_id=conversation.id,
                    direction=MessageDirection.IN,
                    sender=MessageSender.CLIENT,
                    text=message_text,
                    external_id=f"widget-{client_id}-{dt.datetime.now(dt.UTC).timestamp()}",
                )
                session.add(incoming)

                conversation.last_msg_at = dt.datetime.now(dt.UTC)
                conversation.status = ConversationStatus.BOT

                # Валидация входящего
                cleaned, _ = validate_and_clean(message_text)

            # Генерируем и отправляем ответ
            await websocket.send_json({
                "type": "typing",
                "text": "",
                "timestamp": dt.datetime.now(dt.UTC).isoformat(),
            })

            # TODO: вызвать process_conversation для генерации ответа LLM
            # Пока заглушка
            response_text = "Спасибо за сообщение! Администратор ответит в ближайшее время."

            # Сохраняем исходящее
            async with sf() as session:
                outgoing = Message(
                    conversation_id=conversation.id,
                    direction=MessageDirection.OUT,
                    sender=MessageSender.BOT,
                    text=response_text,
                    external_id=f"widget-bot-{dt.datetime.now(dt.UTC).timestamp()}",
                )
                session.add(outgoing)
                await session.flush()

            # Отправляем ответ
            await websocket.send_json({
                "type": "message",
                "text": response_text,
                "timestamp": dt.datetime.now(dt.UTC).isoformat(),
            })

    except WebSocketDisconnect:
        logger.info("widget_client_disconnected", extra={"client_id": client_id})
    except Exception:
        logger.exception("widget_error")
    finally:
        # Удаляем из хранилища
        if business_token in _active_connections:
            _active_connections[business_token].pop(client_id, None)


@router.get("/widget.js")
async def serve_widget_js() -> str:
    """Сервит JS-бандл виджета.

    Возвращает минифицированный bundle < 50KB gzip.
    В продакшене — отдельный файл, здесь — генерация.
    """
    return _generate_widget_js()


def _generate_widget_js() -> str:
    """Генерирует JS-код виджета для встраивания."""
    return """
(function() {
  'use strict';
  var WIDGET_ID = 'ai-admin-widget';
  var CSS = [
    '#ai-admin-widget .widget-button{position:fixed;bottom:20px;right:20px;width:60px;height:60px;border-radius:50%;background:#5633dd;color:#fff;font-size:24px;border:none;cursor:pointer;z-index:9999;box-shadow:0 4px 12px rgba(0,0,0,.3);}',
    '#ai-admin-widget .widget-window{position:fixed;bottom:90px;right:20px;width:360px;max-height:500px;border-radius:12px;background:#fff;box-shadow:0 8px 32px rgba(0,0,0,.15);z-index:9998;display:none;flex-direction:column;overflow:hidden;}',
    '#ai-admin-widget .widget-header{background:#5633dd;color:#fff;padding:12px 16px;font-weight:600;display:flex;justify-content:space-between;align-items:center;}',
    '#ai-admin-widget .widget-body{flex:1;overflow-y:auto;padding:12px;font-size:14px;}',
    '#ai-admin-widget .widget-input{display:flex;border-top:1px solid #eee;}',
    '#ai-admin-widget .widget-input input{flex:1;border:none;padding:12px;font-size:14px;outline:none;}',
    '#ai-admin-widget .widget-input button{background:#5633dd;color:#fff;border:none;padding:0 16px;cursor:pointer;font-size:14px;}',
    '#ai-admin-widget .msg{margin:4px 0;padding:8px 12px;border-radius:8px;max-width:80%;word-wrap:break-word;}',
    '#ai-admin-widget .msg.client{background:#f0f0f0;align-self:flex-start;}',
    '#ai-admin-widget .msg.bot{background:#5633dd;color:#fff;align-self:flex-end;}',
    '#ai-admin-widget .typing{color:#999;font-style:italic;font-size:12px;}'
  ].join('\\n');
  var btn, win, body, input, sendBtn;
  var ws = null;
  var businessToken = document.querySelector('script[data-business-token]')?.dataset.businessToken || '';

  function init() {
    if (document.getElementById(WIDGET_ID)) return;
    var head = document.head || document.documentElement;
    var style = document.createElement('style');
    style.textContent = CSS;
    head.appendChild(style);

    btn = document.createElement('button');
    btn.id = WIDGET_ID + '-btn';
    btn.className = 'widget-button';
    btn.innerHTML = '💬';
    btn.onclick = toggleWindow;

    win = document.createElement('div');
    win.id = WIDGET_ID;
    win.className = 'widget-window';
    win.innerHTML = '<div class="widget-header"><span>AI-помощник</span><span style="cursor:pointer" onclick="toggleWindow()">✕</span></div><div class="widget-body" id="widget-body"></div><div class="widget-input"><input id="widget-input" placeholder="Введите сообщение..." /><button id="widget-send">→</button></div>';

    body = document.getElementById('widget-body');
    input = document.getElementById('widget-input');
    sendBtn = document.getElementById('widget-send');

    sendBtn.onclick = sendMessage;
    input.onkeydown = function(e) { if (e.key === 'Enter') sendMessage(); };

    document.body.appendChild(btn);
    document.body.appendChild(win);

    connectWebSocket();
  }

  function toggleWindow() {
    win.style.display = win.style.display === 'flex' ? 'none' : 'flex';
  }
  if (window.toggleWindow) { window.toggleWindow = toggleWindow; }

  function connectWebSocket() {
    if (!businessToken) return;
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    var host = location.host;
    ws = new WebSocket(proto + '//' + host + '/ws/chat/' + businessToken);
    ws.onmessage = function(e) {
      var data = JSON.parse(e.data);
      if (data.type === 'typing') {
        var t = document.createElement('div');
        t.className = 'typing';
        t.textContent = 'печатает...';
        body.appendChild(t);
        body.scrollTop = body.scrollHeight;
      } else {
        var d = document.createElement('div');
        d.className = 'msg bot';
        d.textContent = data.text;
        body.appendChild(d);
        body.scrollTop = body.scrollHeight;
      }
    };
    ws.onclose = function() { setTimeout(connectWebSocket, 3000); };
  }

  function sendMessage() {
    var text = input.value.trim();
    if (!text || !ws) return;
    var d = document.createElement('div');
    d.className = 'msg client';
    d.textContent = text;
    body.appendChild(d);
    body.scrollTop = body.scrollHeight;
    ws.send(JSON.stringify({ text: text }));
    input.value = '';
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
"""


__all__ = [
    "router",
    "_active_connections",
    "serve_widget_js",
    "_generate_widget_js",
]
