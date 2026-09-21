"""
Telegram Bot Integration for AI Agents Platform.

Enterprise-grade bot with:
  - MongoDB-backed persistent sessions (survive restarts)
  - Per-user rate limiting (burst + sustained)
  - Shared HTTP client with connection pooling & retry
  - Secure two-step login flow via ConversationHandler
  - @require_auth decorator (no repeated boilerplate)
  - Metrics & health reporting (exposed via /api/health)
  - Webhook support (optional; set TELEGRAM_WEBHOOK_URL)
  - Modular handler architecture (handlers/ package)

Setup:
  1. Message @BotFather on Telegram -> /newbot -> get your BOT TOKEN
  2. Set TELEGRAM_BOT_TOKEN environment variable (or add to server/.env)
  3. With the API server: start `uvicorn api:app` — the bot starts automatically if
     TELEGRAM_BOT_TOKEN is set and TELEGRAM_BOT_ENABLED is not off (same process). Only one
     poller may run per token; if you run the bot separately, set TELEGRAM_BOT_STANDALONE=1
     so the API does not also start it.
     Or run standalone only:
     python -m telegram_bot.bot   (from server/)
     Or:  python bot.py               (from server/telegram_bot/)

  Webhook mode: Set TELEGRAM_WEBHOOK_URL to switch from polling to webhooks.

  BPMN diagrams: the bot sends .bpmn files. Optional PNG previews in chat require
  Node.js on the server and TELEGRAM_BPMN_RENDER=1 (uses npx bpmn-to-image).
"""

import asyncio
import logging
from typing import Any, Dict

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.error import Conflict, TimedOut

from . import config
from . import http_client as _http_client
from .session_store import init_session_db, get_store
from .rate_limiter import cleanup_all as _cleanup_rate_limiters
from .health import metrics
from .handlers import (
    cmd_start,
    cmd_help,
    cmd_new,
    handle_message,
    cmd_workflows,
    cmd_run,
    cmd_create,
    cmd_update,
    cmd_detail,
    cmd_delete,
    callback_run_workflow,
    callback_menu_action,
    cmd_logout,
    build_login_conversation,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Embedded-mode state (filled by post_init when running inside FastAPI).
_embed_state: Dict[str, Any] = {}

# Background task for periodic cleanup.
_cleanup_task: asyncio.Task | None = None


# ---------------------------------------------------------------------------
# Formatting helper (used by error handler below)
# ---------------------------------------------------------------------------

def _rule_line(width: int = 28) -> str:
    return "\u2500" * width


def _section_plain(title: str, body: str) -> str:
    r = _rule_line()
    return f"{r}\n{title}\n{r}\n{body.strip()}"


# ---------------------------------------------------------------------------
# Periodic cleanup (sessions + rate limiter buckets)
# ---------------------------------------------------------------------------

async def _periodic_cleanup() -> None:
    """Run session expiry and rate-limiter cleanup on an interval."""
    interval = config.SESSION_CLEANUP_INTERVAL
    while True:
        try:
            await asyncio.sleep(interval)
            store = get_store()
            store.cleanup_expired()
            _cleanup_rate_limiters()
        except asyncio.CancelledError:
            logger.info("Periodic cleanup task cancelled")
            break
        except Exception as exc:
            logger.warning("Periodic cleanup error: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# Application builder
# ---------------------------------------------------------------------------

async def _embedded_post_init(application: Application) -> None:
    """Called after the Application is built in embedded mode."""
    _embed_state["application"] = application
    _embed_state["loop"] = asyncio.get_running_loop()

    # Start periodic cleanup in the application's event loop.
    global _cleanup_task
    _cleanup_task = asyncio.create_task(_periodic_cleanup())


def build_telegram_application(*, embedded: bool = False) -> Application:
    """Build and return a fully-wired Telegram Application."""
    builder = (
        ApplicationBuilder()
        .token(config.TELEGRAM_TOKEN)
        .connect_timeout(config.TELEGRAM_CONNECT_TIMEOUT)
        .read_timeout(config.TELEGRAM_READ_TIMEOUT)
        .write_timeout(config.TELEGRAM_WRITE_TIMEOUT)
        .pool_timeout(config.TELEGRAM_POOL_TIMEOUT)
        .get_updates_connect_timeout(config.TELEGRAM_GET_UPDATES_CONNECT_TIMEOUT)
        .get_updates_read_timeout(config.TELEGRAM_GET_UPDATES_READ_TIMEOUT)
        .get_updates_write_timeout(config.TELEGRAM_GET_UPDATES_WRITE_TIMEOUT)
        .get_updates_pool_timeout(config.TELEGRAM_GET_UPDATES_POOL_TIMEOUT)
    )
    if embedded:
        builder = builder.post_init(_embedded_post_init)
    tg_app = builder.build()

    # Login conversation handler (must be registered before the catch-all text handler).
    tg_app.add_handler(build_login_conversation())

    # Command handlers
    tg_app.add_handler(CommandHandler("start", cmd_start))
    tg_app.add_handler(CommandHandler("help", cmd_help))
    tg_app.add_handler(CommandHandler("new", cmd_new))
    tg_app.add_handler(CommandHandler("logout", cmd_logout))
    tg_app.add_handler(CommandHandler("workflows", cmd_workflows))
    tg_app.add_handler(CommandHandler("run", cmd_run))
    tg_app.add_handler(CommandHandler("workflow", cmd_run))
    tg_app.add_handler(CommandHandler("create", cmd_create))
    tg_app.add_handler(CommandHandler("update", cmd_update))
    tg_app.add_handler(CommandHandler("detail", cmd_detail))
    tg_app.add_handler(CommandHandler("delete", cmd_delete))

    # Callback query for inline "Run workflow" buttons
    tg_app.add_handler(CallbackQueryHandler(callback_run_workflow, pattern=r"^run:"))

    # Callback query for post-login menu buttons
    tg_app.add_handler(CallbackQueryHandler(callback_menu_action, pattern=r"^menu:"))

    # Catch-all: any free text -> AI agent
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Global error handler
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        if isinstance(context.error, Conflict):
            logger.critical(
                "Telegram 409 Conflict: another process is already polling getUpdates for this "
                "bot token. Stop duplicate bots, or set TELEGRAM_BOT_STANDALONE=1 on the API and "
                "run exactly one `python -m telegram_bot`."
            )
            context.application.stop_running()
            return
        logger.error("Unhandled exception: %s", context.error, exc_info=context.error)
        metrics.record_error()
        if update and hasattr(update, "effective_chat") and update.effective_chat:
            try:
                await update.effective_chat.send_message(
                    _section_plain(
                        "Unexpected error",
                        f"An internal error occurred. Please try again.\n\n"
                        f"Reference: {str(context.error)[:300]}",
                    )
                )
            except Exception:
                pass

    tg_app.add_error_handler(error_handler)
    return tg_app


# ---------------------------------------------------------------------------
# Webhook support
# ---------------------------------------------------------------------------

async def process_webhook_update(payload: dict) -> None:
    """Process an incoming Telegram webhook update (called by FastAPI route)."""
    app = _embed_state.get("application")
    if not app:
        logger.warning("Webhook update received but no application is running")
        return
    update = Update.de_json(payload, app.bot)
    await app.process_update(update)


async def setup_webhook() -> None:
    """Set the Telegram webhook URL (call during embedded startup)."""
    app = _embed_state.get("application")
    if app and config.use_webhook():
        await app.bot.set_webhook(
            url=config.WEBHOOK_URL,
            secret_token=config.WEBHOOK_SECRET or None,
        )
        logger.info("Telegram webhook set: %s", config.WEBHOOK_URL)


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------

def shutdown_embedded_bot() -> None:
    """Stop the bot when running inside a background thread (embedded mode)."""
    global _cleanup_task

    # Cancel cleanup task
    if _cleanup_task and not _cleanup_task.done():
        _cleanup_task.cancel()
        _cleanup_task = None

    # Close shared HTTP client
    loop = _embed_state.get("loop")
    if loop and loop.is_running():
        asyncio.run_coroutine_threadsafe(_http_client.close_client(), loop)

    # Stop the Telegram application
    application = _embed_state.get("application")
    if application and loop and loop.is_running():
        loop.call_soon_threadsafe(application.stop_running)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(*, embedded: bool = False):
    import admin_auth

    if not config.TELEGRAM_TOKEN:
        print("=" * 60)
        print("TELEGRAM BOT SETUP")
        print("=" * 60)
        print()
        print("1. Open Telegram and message @BotFather")
        print("2. Send /newbot and follow the prompts")
        print("3. Copy the token BotFather gives you")
        print("4. Set TELEGRAM_BOT_TOKEN in server/.env")
        print()
        print("5. Run this script again:")
        print("   python bot.py          (from server/telegram_bot/)")
        print("   python -m telegram_bot (from server/)")
        print("   Or start the API server (bot auto-starts with TELEGRAM_BOT_TOKEN).")
        print("=" * 60)
        return

    if not config.is_bot_enabled():
        print("Telegram bot is disabled (set TELEGRAM_BOT_ENABLED=1 in server/.env to enable).")
        return

    # Initialize databases
    try:
        admin_auth.init_admin_db()
        admin_auth.seed_default_admin()
        print("Admin DB initialized")
    except Exception as e:
        print(f"Admin DB init skipped: {e}")

    try:
        init_session_db()
        print("Telegram session DB initialized")
    except Exception as e:
        print(f"Session DB init skipped (using in-memory fallback): {e}")

    print(f"Starting Telegram bot...")
    print(f"API endpoint: {config.API_BASE_URL}")
    print(f"Mode: {'webhook' if config.use_webhook() else 'polling'}")
    if not embedded:
        print("Press Ctrl+C to stop.\n")

    tg_app = build_telegram_application(embedded=embedded)

    if config.use_webhook():
        # Webhook mode
        tg_app.run_webhook(
            listen="0.0.0.0",
            port=int(config.WEBHOOK_URL.split(":")[-1].split("/")[0]) if ":" in config.WEBHOOK_URL else 8443,
            url_path=config.WEBHOOK_PATH,
            webhook_url=config.WEBHOOK_URL,
            secret_token=config.WEBHOOK_SECRET or None,
            drop_pending_updates=True,
            stop_signals=None if embedded else None,
        )
    else:
        # Polling mode
        polling_kwargs = {
            "drop_pending_updates": True,
            "bootstrap_retries": config.TELEGRAM_BOOTSTRAP_RETRIES,
        }
        if embedded:
            polling_kwargs["stop_signals"] = None
        try:
            tg_app.run_polling(**polling_kwargs)
        except TimedOut:
            logger.warning(
                "Telegram polling startup timed out. Bot will remain stopped until next restart. "
                "Check internet/firewall access to api.telegram.org or increase TELEGRAM_*_TIMEOUT values."
            )
            if not embedded:
                raise


if __name__ == "__main__":
    main()
