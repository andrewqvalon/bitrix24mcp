# bitrix24mcp

MCP сервер для CRM Bitrix24 с OAuth2 авторизацией и запуском в Docker.

## Что реализовано

- HTTP MCP endpoint: `POST/GET/DELETE /mcp`
- OAuth2 flow для Bitrix24:
  - `GET /auth/bitrix/start`
  - `GET /auth/bitrix/callback`
  - `GET /auth/status`
- Health endpoint: `GET /healthz`
- MCP tools:
  - `auth_status`
  - `list_deals`
  - `get_deal`
  - `list_contacts`
- Авто-refresh access token по `refresh_token`
- Хранение токенов в файле `data/tokens.json`

## Требования

- Docker + Docker Compose
- Зарегистрированное OAuth приложение в Bitrix24
- Публичный callback URL (в вашем случае: `https://orion.mdaudit.ru/auth/bitrix/callback`)

## Настройка `.env`

Скопируйте `.env.example` в `.env` и заполните:

```bash
cp .env.example .env
```

Обязательные поля:

- `BITRIX_CLIENT_ID`
- `BITRIX_CLIENT_SECRET`
- `BITRIX_REDIRECT_URI` (должен совпадать с redirect URI в приложении Bitrix24)

Рекомендуемые:

- `PORT=4310`
- `HOST=0.0.0.0`
- `MCP_HTTP_PATH=/mcp`
- `BASE_URL=https://orion.mdaudit.ru`

## Запуск в Docker

```bash
docker compose up -d --build
```

Проверка:

```bash
curl http://localhost:4310/healthz
curl http://localhost:4310/auth/status
```

## Как пройти авторизацию Bitrix24

1. Откройте:
   - `https://orion.mdaudit.ru/auth/bitrix/start`
2. Подтвердите доступ в интерфейсе Bitrix24.
3. После редиректа на callback вы получите сообщение:
   - `Bitrix24 authorization complete. You can return to your MCP client.`
4. Проверьте статус:
   - `https://orion.mdaudit.ru/auth/status`
   - `authorized` должно быть `true`.

## Подключение MCP-клиента

Пример конфигурации HTTP MCP:

```json
{
  "mcpServers": {
    "bitrix24-http": {
      "url": "https://orion.mdaudit.ru/mcp"
    }
  }
}
```

## Локальный запуск без Docker

```bash
npm install
npm run start:http
```

или stdio-режим:

```bash
npm run start:stdio
```
