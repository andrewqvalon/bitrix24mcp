# Bitrix24 MCP Server

MCP-сервер для работы с CRM Bitrix24. Реализует кеширующую архитектуру:

```
Bitrix24 REST API  →  Локальная БД (PostgreSQL/SQLite)  →  MCP-инструменты  →  AI-агент
```

## Архитектура

```
src/bitrix24mcp/
├── bitrix/        # Адаптер к REST API Bitrix24 (пагинация, retry, rate-limit)
├── db/            # ORM-модели SQLAlchemy + CRUD-репозиторий
├── sync/          # Фоновый синхронизатор (full-pull из Bitrix24)
├── webhook/       # Опциональный HTTP-обработчик вебхуков Bitrix24
└── server.py      # MCP-сервер со всеми инструментами
```

## Инструменты MCP

| Инструмент | Описание |
|---|---|
| `sync_crm_data` | Синхронизировать данные из Bitrix24 в кеш |
| `find_contacts` | Поиск контактов по имени/телефону/email |
| `get_contact` | Получить контакт по ID |
| `find_companies` | Поиск компаний |
| `get_company` | Получить компанию по ID |
| `find_deals` | Поиск/фильтрация сделок |
| `get_deal` | Получить сделку по ID |
| `find_leads` | Поиск лидов |
| `get_lead` | Получить лид по ID |
| `list_pipelines` | Список воронок (категорий сделок) |
| `get_deal_stages` | Стадии конкретной воронки |
| `get_client_summary` | Агрегированная сводка по клиенту |
| `get_crm_timeline` | Лента событий по клиенту/сделке |
| `create_contact` | Создать контакт |
| `create_deal` | Создать сделку |
| `update_deal_stage` | Перевести сделку на новую стадию |
| `create_lead` | Создать лид |
| `add_crm_comment` | Добавить комментарий в ленту CRM |
| `get_portfolio_report` | Отчёт по портфелю сделок |

## Быстрый старт

### 1. Установка

```bash
pip install -e ".[webhook]"   # с поддержкой вебхуков
# или
pip install -e .              # только MCP-сервер
```

### 2. Настройка аутентификации

Есть два способа авторизации. **OAuth2 рекомендуется** — он проще и не требует ручной настройки токенов.

---

#### Способ А: OAuth2 (рекомендуется) — вход через всплывающее окно Bitrix24

**Шаг 1.** Зарегистрируйте приложение Bitrix24:
1. Откройте `https://www.bitrix24.ru/apps/add.php` (или `/marketplace/app/add/` на вашем портале)
2. Выберите **«Другое»** → **«Серверное приложение»**
3. В поле **Redirect URI** укажите: `http://localhost:8765/oauth/callback`
4. Скопируйте `client_id` (APP.ID) и `client_secret`

**Шаг 2.** Скопируйте `.env.example` в `.env` и заполните:

```bash
cp .env.example .env
```

```env
BITRIX24_CLIENT_ID=local.YOUR_APP_ID
BITRIX24_CLIENT_SECRET=YOUR_APP_SECRET
BITRIX24_REDIRECT_URI=http://localhost:8765/oauth/callback

DATABASE_URL=sqlite:///bitrix24mcp.sqlite
```

**Шаг 3.** Запустите сервер и вызовите инструмент авторизации:

```bash
bitrix24mcp
```

В агенте (Claude, Cursor и т.д.) вызовите инструмент:
```
authorize_bitrix24
```

Откроется всплывающее окно Bitrix24 с формой входа. Введите логин и пароль — система автоматически получит и сохранит токены. Больше ничего делать не нужно.

---

#### Способ Б: Входящий вебхук (простой вариант без регистрации приложения)

```env
BITRIX24_WEBHOOK_URL=https://your-domain.bitrix24.ru/rest/1/YOUR_TOKEN/
DATABASE_URL=sqlite:///bitrix24mcp.sqlite
```

Вебхук создаётся в Bitrix24: **Настройки → Разработчикам → Входящие вебхуки → Добавить вебхук**.

---

### 3. Поднять PostgreSQL (опционально)

```bash
docker compose up -d
```

### 4. Запустить MCP-сервер

```bash
# Через stdio (для интеграции с Claude Desktop / Cursor и т.д.)
bitrix24mcp

# Или напрямую:
python -m bitrix24mcp
```

### 5. Проверить статус авторизации

```
get_auth_status
```

### 6. Первичная синхронизация данных

```
sync_crm_data
```

### 7. Вебхуки реального времени (опционально)

Для мгновенных обновлений при изменениях в CRM запустите HTTP-обработчик:

```bash
uvicorn bitrix24mcp.webhook.handler:app --host 0.0.0.0 --port 8080
```

Зарегистрируйте в Bitrix24 события на URL `http://your-server:8080/webhook`:
- `onCrmContactAdd` / `onCrmContactUpdate`
- `onCrmCompanyAdd` / `onCrmCompanyUpdate`
- `onCrmDealAdd` / `onCrmDealUpdate`
- `onCrmLeadAdd` / `onCrmLeadUpdate`

## Интеграция с Claude Desktop

### OAuth2 (рекомендуется)

```json
{
  "mcpServers": {
    "bitrix24": {
      "command": "bitrix24mcp",
      "env": {
        "BITRIX24_CLIENT_ID": "local.YOUR_APP_ID",
        "BITRIX24_CLIENT_SECRET": "YOUR_APP_SECRET",
        "BITRIX24_REDIRECT_URI": "http://localhost:8765/oauth/callback",
        "DATABASE_URL": "sqlite:///bitrix24mcp.sqlite"
      }
    }
  }
}
```

После запуска сервера один раз вызовите `authorize_bitrix24` — откроется браузер с формой входа Bitrix24.

### Webhook (альтернатива)

```json
{
  "mcpServers": {
    "bitrix24": {
      "command": "bitrix24mcp",
      "env": {
        "BITRIX24_WEBHOOK_URL": "https://your-domain.bitrix24.ru/rest/1/TOKEN/",
        "DATABASE_URL": "sqlite:///bitrix24mcp.sqlite"
      }
    }
  }
}
```

## Разработка и тесты

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## Схема базы данных

| Таблица | Описание |
|---|---|
| `crm_contacts` | Кеш контактов |
| `crm_companies` | Кеш компаний |
| `crm_deals` | Кеш сделок |
| `crm_leads` | Кеш лидов |
| `crm_pipelines` | Воронки продаж |
| `crm_stages` | Стадии сделок |
| `crm_activities` | Активности/события CRM (лента) |
| `sync_state` | Время последней синхронизации |

## Принцип работы

1. **Чтение** — все запросы обслуживаются из локального кеша (PostgreSQL/SQLite).
2. **Запись** — мутации пишутся в Bitrix24 напрямую, затем обновляется локальный кеш.
3. **Синхронизация** — данные обновляются при вызове `sync_crm_data` или через вебхуки.
4. **TTL** — `CACHE_TTL` определяет, насколько «свежими» считаются данные.
