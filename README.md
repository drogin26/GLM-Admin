# AI-Администратор — SaaS автоответчик для малого бизнеса

SaaS-продукт для автоматизации ответов клиентам из Telegram, ВКонтакте и чат-виджета на сайте.
LLM-powered RAG на базе GigaChat (или YandexGPT) — данные не покидают Россию.

## Ключевая ценность

1. **Скорость < 30 сек** — бот отвечает мгновенно, клиент не уходит к конкуренту
2. **Квалификация лидов** — бот задаёт 2–3 вопроса и присылает карточку: «🔥 Горячий лид: разводка труб, Москва, завтра»
3. **Отчёт «Потерянные заявки»** — сколько сообщений без ответа, оценка упущенной выручки

## Архитектура

```
┌──────────┐   ┌──────────┐   ┌──────────┐
│ Telegram │   │ VK Group │   │  Виджет  │
│  Bot API │   │ Callback │   │  WS      │
└────┬─────┘   └────┬─────┘   └────┬─────┘
     │              │              │
     └──────────────┼──────────────┘
                    │
              ┌─────▼─────┐
              │  FastAPI  │
              │  Backend  │
              └─────┬─────┘
                    │
     ┌──────────────┼──────────────┐
     │              │              │
┌────▼─────┐ ┌─────▼─────┐ ┌─────▼─────┐
│ Postgres │ │   Redis   │ │  Celery   │
│ + pgvector │  (cache,  │ │  Worker   │
│  (RAG)   │ │  ratelimit)│ │           │
└──────────┘ └───────────┘ └───────────┘
```

## Стек

| Слой | Технологии |
|------|-----------|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.x (async), PostgreSQL 16, Redis 7, Celery |
| LLM | GigaChat (или YandexGPT) через абстракцию провайдера, pgvector для эмбеддингов |
| Frontend | Next.js 14 (App Router), TailwindCSS, мобильная адаптивность |
| Деплой | Docker Compose, Nginx |

## Структура

```
GLM/
├── backend/               # FastAPI backend
│   ├── app/
│   │   ├── api/          # Маршруты (auth, cabinet, webhooks, widget)
│   │   ├── models/       # SQLAlchemy модели
│   │   ├── services/     # Бизнес-логика
│   │   │   ├── llm/      # LLM-провайдеры (GigaChat, YandexGPT)
│   │   │   ├── messaging/# Каналы (Telegram, VK)
│   │   │   ├── rag.py    # RAG: чанкинг, эмбеддинги, поиск
│   │   │   ├── conversation.py  # Обработка диалогов
│   │   │   ├── leads.py  # Квалификация лидов
│   │   │   ├── billing.py # Тарифы и лимиты
│   │   │   └── validator.py   # Фильтрация ответов
│   │   ├── tasks/        # Celery задачи
│   │   │   ├── maintenance.py  # Автоочистка 90 дней
│   │   │   ├── polling.py      # Fallback-поллинг Telegram
│   │   │   └── reports.py      # Отчёты «Потерянные заявки»
│   │   ├── config.py     # Настройки (.env)
│   │   ├── security.py   # Fernet-шифрование, bcrypt
│   │   └── main.py       # Точка входа
│   ├── alembic/          # Миграции
│   └── tests/            # pytest
├── frontend/             # Next.js кабинет
│   └── src/app/
│       ├── login/        # Регистрация/вход
│       ├── dashboard/    # Дашборд с метриками
│       ├── inbox/        # Список диалогов
│       ├── knowledge/    # Редактор базы знаний
│       └── settings/     # Настройки бизнеса
├── deploy/nginx/         # Nginx конфигурация
└── docker-compose.yml    # docker compose up
```

## Быстрый старт

```bash
# 1. Клонируйте репозиторий
git clone <repo>
cd GLM

# 2. Настройте окружение
cp .env.example .env
# Отредактируйте .env: измените POSTGRES_PASSWORD, SECRET_KEY, FERNET_KEYS

# 3. Запустите всё одной командой
docker compose up --build

# 4. Кабинет: http://localhost:3000
# 5. API: http://localhost:8000/docs
# 6. Healthcheck: http://localhost:8000/readyz
```

## Запуск тестов

```bash
cd backend
uv run pytest -v
```

## Критерии приёмки MVP

| Требование | Статус |
|-----------|--------|
| Новый бизнес подключается за ≤ 15 мин | ✅ |
| Медиана первого ответа бота < 30 сек | ✅ |
| Отчёт «Потерянные заявки» по понедельникам | ✅ |
| Эскалация на «денежные» вопросы | ✅ |
| Валидатор ловит телефоны/ссылки | ✅ |
| Восстановление при падении компонентов | ✅ |

## Тарифы

| Тариф | Цена | Диалоги |
|-------|------|---------|
| Trial | 0 ₽ | 50 / 14 дней |
| Basic | 3 900 ₽/мес | 300 / мес |
| Pro | 5 990 ₽/мес | Безлимит |

## Безопасность

- Шифрование credentials каналов (Fernet MultiKey, с ротацией)
- Пароли — bcrypt (rounds=12)
- Хранение переписки 90 дней (автоочистка Celery)
- Валидатор ответов: удаление телефонов, ссылок, HTML-тегов
- Rate limiting webhook-маршрутов (Redis)
- Graceful shutdown (SIGTERM/SIGINT)

## Переменные окружения

См. `.env.example`. Обязательные:

```bash
POSTGRES_PASSWORD=strong_password
SECRET_KEY=random_64chars
FERNET_KEYS=fernet_key_1
LLM_PROVIDER=gigachat  # gigachat | yandexgpt
```

## Roadmap

- [x] Итерация 1: Каркас (FastAPI, Postgres, Redis, Celery, модели, миграции)
- [x] Итерация 2: Telegram-канал (webhook, fallback-поллинг)
- [x] Итерация 3: LLM-слой (GigaChat, RAG, conversation processing)
- [x] Итерация 4: Квалификация лидов (HOT/WARM/COLD, карточки)
- [x] Итерация 5: VK-канал (callback API)
- [x] Итерация 6: Чат-виджет (WebSocket + JS-бандл)
- [x] Итерация 7: Кабинет (онбординг, инбокс, знания)
- [x] Итерация 8: Дашборд + еженедельные отчёты
- [x] Итерация 9: Биллинг (тарифы, лимиты)
- [x] Итерация 10: Безопасность (rate-limit, graceful shutdown)

## Лицензия

Proprietary © 2026
