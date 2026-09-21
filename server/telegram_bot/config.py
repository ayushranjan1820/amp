"""
Centralized configuration for the Telegram Bot.

All environment variables, timeouts, and constants live here.
Backward-compatible with existing env vars; new ones have sensible defaults.
"""

import os
import sys

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(BOT_DIR)

if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from user_config import load_dotenv_then_scrub_pwc

load_dotenv_then_scrub_pwc(os.path.join(SERVER_DIR, ".env"))

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
API_BASE_URL: str = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")

# ---------------------------------------------------------------------------
# Webhook (empty = polling mode)
# ---------------------------------------------------------------------------
WEBHOOK_URL: str = os.getenv("TELEGRAM_WEBHOOK_URL", "")
WEBHOOK_SECRET: str = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
WEBHOOK_PATH: str = os.getenv("TELEGRAM_WEBHOOK_PATH", "/api/telegram/webhook")

# ---------------------------------------------------------------------------
# Timeouts (seconds)
# ---------------------------------------------------------------------------
AGENT_CALL_TIMEOUT: float = float(os.getenv("TELEGRAM_AGENT_TIMEOUT", "120"))
FILE_DOWNLOAD_TIMEOUT: float = float(os.getenv("TELEGRAM_FILE_TIMEOUT", "60"))
BPMN_RENDER_TIMEOUT: int = int(os.getenv("TELEGRAM_BPMN_TIMEOUT", "180"))

# Telegram API bootstrap/network tuning.
TELEGRAM_BOOTSTRAP_RETRIES: int = int(os.getenv("TELEGRAM_BOOTSTRAP_RETRIES", "5"))
TELEGRAM_CONNECT_TIMEOUT: float = float(os.getenv("TELEGRAM_CONNECT_TIMEOUT", "20"))
TELEGRAM_READ_TIMEOUT: float = float(os.getenv("TELEGRAM_READ_TIMEOUT", "30"))
TELEGRAM_WRITE_TIMEOUT: float = float(os.getenv("TELEGRAM_WRITE_TIMEOUT", "30"))
TELEGRAM_POOL_TIMEOUT: float = float(os.getenv("TELEGRAM_POOL_TIMEOUT", "10"))

# Dedicated getUpdates timeouts for long-polling mode.
TELEGRAM_GET_UPDATES_CONNECT_TIMEOUT: float = float(
    os.getenv("TELEGRAM_GET_UPDATES_CONNECT_TIMEOUT", "20")
)
TELEGRAM_GET_UPDATES_READ_TIMEOUT: float = float(
    os.getenv("TELEGRAM_GET_UPDATES_READ_TIMEOUT", "60")
)
TELEGRAM_GET_UPDATES_WRITE_TIMEOUT: float = float(
    os.getenv("TELEGRAM_GET_UPDATES_WRITE_TIMEOUT", "30")
)
TELEGRAM_GET_UPDATES_POOL_TIMEOUT: float = float(
    os.getenv("TELEGRAM_GET_UPDATES_POOL_TIMEOUT", "10")
)

# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
SESSION_TTL_SECONDS: int = int(os.getenv("TELEGRAM_SESSION_TTL", "86400"))  # 24h
SESSION_CLEANUP_INTERVAL: int = int(os.getenv("TELEGRAM_SESSION_CLEANUP_INTERVAL", "900"))  # 15min

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
RATE_LIMIT_MESSAGES: int = int(os.getenv("TELEGRAM_RATE_LIMIT_MESSAGES", "20"))
RATE_LIMIT_WINDOW: float = float(os.getenv("TELEGRAM_RATE_LIMIT_WINDOW", "60"))
RATE_LIMIT_BURST: int = int(os.getenv("TELEGRAM_RATE_LIMIT_BURST", "5"))
RATE_LIMIT_BURST_WINDOW: float = float(os.getenv("TELEGRAM_RATE_LIMIT_BURST_WINDOW", "5"))

# ---------------------------------------------------------------------------
# HTTP client pooling
# ---------------------------------------------------------------------------
HTTP_MAX_CONNECTIONS: int = int(os.getenv("TELEGRAM_HTTP_MAX_CONN", "20"))
HTTP_MAX_KEEPALIVE: int = int(os.getenv("TELEGRAM_HTTP_MAX_KEEPALIVE", "10"))

# ---------------------------------------------------------------------------
# BPMN rendering
# ---------------------------------------------------------------------------
BPMN_RENDER_ENABLED: bool = os.getenv("TELEGRAM_BPMN_RENDER", "").strip().lower() in (
    "1", "true", "yes",
)

# ---------------------------------------------------------------------------
# UI constants
# ---------------------------------------------------------------------------
TG_INLINE_BTN_MAX_LEN: int = 64
RUN_PICKER_MAX_LISTED: int = 35
RUN_PICKER_MAX_BUTTONS: int = 18
TG_MESSAGE_MAX_LEN: int = 4096
TG_CAPTION_MAX_LEN: int = 1024
TG_HTML_BLOCK_MAX_LEN: int = 4000


def is_bot_enabled() -> bool:
    """Check if the bot is enabled via TELEGRAM_BOT_ENABLED (unset = on)."""
    raw = (os.getenv("TELEGRAM_BOT_ENABLED") or "").strip().lower()
    if not raw:
        return True
    return raw in ("1", "true", "yes", "on")


def use_webhook() -> bool:
    """True when webhook mode should be used (TELEGRAM_WEBHOOK_URL is set)."""
    return bool(WEBHOOK_URL.strip())
