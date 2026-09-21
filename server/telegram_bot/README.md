# Telegram Bot for AI Agents Platform

Enterprise-grade Telegram bot with persistent sessions, rate limiting, connection pooling, secure login, health reporting, and webhook support.

## Quick Start

```bash
# From the server/ directory:

# Start the bot (polling mode)
python -m telegram_bot
# or
python telegram_bot/bot.py

# Stop all running instances
python telegram_bot/stop.py
```

## Prerequisites

1. **Bot Token**: Message `@BotFather` on Telegram -> `/newbot` -> copy the token
2. **Environment**: Add `TELEGRAM_BOT_TOKEN=your-token` to `server/.env`
3. **API Server**: The main API server must be running (or set `API_BASE_URL` in `.env`)
4. **Database**: MongoDB (`CORE_SYSTEM_MONGO_DB` / `MONGODB_URI`) for persistent sessions via the core system DB; falls back to in-memory if unavailable

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and command list |
| `/help` | Same as /start |
| `/new` | Start a new chat conversation |
| `/login` | Authenticate (secure two-step flow) |
| `/logout` | Sign out |
| `/workflows` | List your saved workflows |
| `/run` | Select and execute a workflow |
| `/create <instruction>` | Generate a new workflow from description |
| `/detail <id>` | View workflow details |
| `/delete <id>` | Delete a workflow |

Any free-text message is forwarded to the AI agent for a response.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | (required) | Bot token from @BotFather |
| `API_BASE_URL` | `http://127.0.0.1:8000` | Backend API URL |
| `TELEGRAM_BOT_ENABLED` | `true` | Enable/disable the bot |
| `TELEGRAM_WEBHOOK_URL` | (empty) | Set to use webhooks instead of polling |
| `TELEGRAM_WEBHOOK_SECRET` | (empty) | Webhook secret token |
| `TELEGRAM_BOOTSTRAP_RETRIES` | `5` | Retry count for Telegram bootstrap/getMe during startup |
| `TELEGRAM_CONNECT_TIMEOUT` | `20` | Telegram API connect timeout (seconds) |
| `TELEGRAM_READ_TIMEOUT` | `30` | Telegram API read timeout (seconds) |
| `TELEGRAM_WRITE_TIMEOUT` | `30` | Telegram API write timeout (seconds) |
| `TELEGRAM_GET_UPDATES_READ_TIMEOUT` | `60` | Long-polling read timeout for getUpdates (seconds) |
| `TELEGRAM_AGENT_TIMEOUT` | `120` | AI agent call timeout (seconds) |
| `TELEGRAM_FILE_TIMEOUT` | `60` | File download timeout (seconds) |
| `TELEGRAM_SESSION_TTL` | `86400` | Session lifetime (seconds, default 24h) |
| `TELEGRAM_RATE_LIMIT_MESSAGES` | `20` | Max messages per window |
| `TELEGRAM_RATE_LIMIT_WINDOW` | `60` | Rate limit window (seconds) |
| `TELEGRAM_RATE_LIMIT_BURST` | `5` | Max burst messages |
| `TELEGRAM_RATE_LIMIT_BURST_WINDOW` | `5` | Burst window (seconds) |
| `TELEGRAM_HTTP_MAX_CONN` | `20` | HTTP connection pool size |
| `TELEGRAM_BPMN_RENDER` | `false` | Enable BPMN PNG preview (needs Node.js) |

## Architecture

```
telegram_bot/
  config.py          - Centralized configuration (all env vars)
  session_store.py   - PostgreSQL-backed sessions with in-memory fallback
  http_client.py     - Shared httpx client with connection pooling & retry
  rate_limiter.py    - Per-user rate limiting (burst + sustained)
  auth.py            - @require_auth decorator + secure login ConversationHandler
  health.py          - Metrics counters + health report
  bot.py             - Application builder, wiring, entry point
  stop.py            - Cross-platform instance killer
  handlers/
    chat.py          - Free-text chat, /start, /help, /new
    workflows.py     - /workflows, /run, /create, /detail, /delete
    auth_handlers.py - /login, /logout
```

## Key Features

- **Persistent Sessions**: MongoDB-backed (survives restarts); auto in-memory fallback
- **Rate Limiting**: Per-user burst (5/5s) and sustained (20/60s) limits
- **Connection Pooling**: Shared httpx.AsyncClient with retry on transient errors
- **Secure Login**: Two-step conversation flow; password message auto-deleted
- **Health Metrics**: Messages/commands processed, error rate, response time (via `/api/health`)
- **Webhook Support**: Set `TELEGRAM_WEBHOOK_URL` for production scalability
- **Cross-Platform**: Stop utility works on Windows and Unix
