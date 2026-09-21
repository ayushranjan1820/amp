"""
Authentication utilities for the Telegram Bot.

- ``@require_auth`` decorator: eliminates repeated login checks in command handlers.
- ``build_login_conversation()`` : multi-step /login via ConversationHandler (secure).
"""

import functools
import html
import logging
from typing import Callable, Optional, Dict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode

from . import config
from .session_store import get_user_session, set_user_session, delete_user_session
from .rate_limiter import check_rate_limit, RateLimitExceeded
from .health import metrics

logger = logging.getLogger(__name__)

# ConversationHandler states
AWAITING_USERNAME = 0
AWAITING_PASSWORD = 1


# ---------------------------------------------------------------------------
# Formatting helpers (duplicated minimally to avoid circular imports)
# ---------------------------------------------------------------------------

def _rule_line(width: int = 28) -> str:
    return "\u2500" * width


def _section_plain(title: str, body: str) -> str:
    r = _rule_line()
    return f"{r}\n{title}\n{r}\n{body.strip()}"


def _escape_md(text: str) -> str:
    special = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for ch in special:
        text = text.replace(ch, f'\\{ch}')
    return text


# ---------------------------------------------------------------------------
# @require_auth decorator
# ---------------------------------------------------------------------------

def require_auth(func: Callable) -> Callable:
    """Decorator for command handlers that require an authenticated session.

    Checks session from the persistent store, integrates rate limiting,
    and injects ``context.user_data["session"]`` for the wrapped handler.
    """
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id

        # Rate-limit check
        try:
            await check_rate_limit(user_id)
        except RateLimitExceeded as exc:
            await update.message.reply_text(
                _section_plain(
                    "Rate limit",
                    f"Too many requests. Please wait {exc.retry_after:.0f}s and try again.",
                )
            )
            metrics.record_error()
            return

        session = get_user_session(user_id)
        if not session:
            await update.message.reply_text(
                _section_plain(
                    "Authentication required",
                    "Please sign in with /login to use this command.",
                )
            )
            return

        context.user_data["session"] = session
        return await func(update, context)

    return wrapper


# ---------------------------------------------------------------------------
# Secure login flow via ConversationHandler
# ---------------------------------------------------------------------------

async def _login_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /login — either inline (deprecated) or start conversation flow."""
    import admin_auth

    args = context.args or []

    # Backward-compatible: /login username password
    if len(args) >= 2:
        username = args[0]
        password = " ".join(args[1:])

        # Try to delete the message containing the password
        try:
            await update.message.delete()
        except Exception:
            pass

        await _do_authenticate(update, context, username, password)

        # Deprecation notice
        try:
            await update.effective_chat.send_message(
                _section_plain(
                    "Tip",
                    "For better security, use /login without arguments.\n"
                    "The bot will prompt you for credentials in a two-step flow "
                    "so your password is never visible alongside your username.",
                )
            )
        except Exception:
            pass

        return ConversationHandler.END

    # New secure flow: prompt for username
    await update.message.reply_text(
        _section_plain(
            "Sign in",
            "Enter your username (or /cancel to abort):",
        )
    )
    return AWAITING_USERNAME


async def _receive_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User sent their username — store it and ask for password."""
    username = (update.message.text or "").strip()
    if not username:
        await update.message.reply_text(
            _section_plain("Sign in", "Username cannot be empty. Please enter your username:")
        )
        return AWAITING_USERNAME

    context.user_data["_login_username"] = username
    await update.message.reply_text(
        _section_plain(
            "Sign in",
            f"Username: {username}\nNow enter your password (it will be deleted from chat):",
        )
    )
    return AWAITING_PASSWORD


async def _receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User sent their password — authenticate and clean up."""
    password = update.message.text or ""
    username = context.user_data.pop("_login_username", "")

    # Immediately delete the password message
    try:
        await update.message.delete()
    except Exception:
        pass

    if not username:
        await update.effective_chat.send_message(
            _section_plain("Sign in", "Session error. Please start again with /login.")
        )
        return ConversationHandler.END

    await _do_authenticate(update, context, username, password)
    return ConversationHandler.END


async def _cancel_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the login conversation."""
    context.user_data.pop("_login_username", None)
    await update.message.reply_text(
        _section_plain("Sign in", "Login cancelled.")
    )
    return ConversationHandler.END


async def _do_authenticate(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    username: str,
    password: str,
) -> None:
    """Shared authentication logic for both inline and conversation flows."""
    import admin_auth

    try:
        user = admin_auth.authenticate_admin(username, password)
    except Exception as e:
        logger.error("Login DB error: %s", e)
        await update.effective_chat.send_message(
            _section_plain("Authentication error", f"Sign-in could not be completed: {str(e)[:200]}")
        )
        metrics.record_error()
        return

    if not user:
        await update.effective_chat.send_message(
            _section_plain(
                "Authentication failed",
                "The username or password is incorrect. Please verify your credentials and try again.",
            )
        )
        return

    perms = user.get("menu_permissions", [])
    role = user.get("role", "user")
    if "agent-studio" not in perms and role not in ("admin", "super_admin"):
        await update.effective_chat.send_message(
            _section_plain(
                "Access denied",
                "Your account is not enabled for Agent Studio. Contact an administrator if you need access.",
            )
        )
        return

    token = admin_auth.generate_token(user)
    set_user_session(update.effective_user.id, {
        "user": user,
        "token": token,
        "username": username,
    })

    role_display = html.escape(role)
    username_display = html.escape(username)

    menu_text = (
        f"<b>Signed in successfully</b>\n"
        f"User: <b>{username_display}</b> \u00b7 <code>{role_display}</code>\n\n"
        f"<b>Here\u2019s what I can do:</b>\n"
        f"\u2022 <b>Chat</b> \u2014 Send any message to talk with AI agents\n"
        f"\u2022 /workflows \u2014 List your saved workflows\n"
        f"\u2022 /create <i>instruction</i> \u2014 Generate a new workflow\n"
        f"\u2022 /update <i>id instruction</i> \u2014 Modify an existing workflow\n"
        f"\u2022 /run \u2014 Execute a workflow\n"
        f"\u2022 /detail <i>id</i> \u2014 Inspect a workflow\n"
        f"\u2022 /delete <i>id</i> \u2014 Remove a workflow\n"
        f"\u2022 /new \u2014 Start a fresh conversation\n"
        f"\u2022 /logout \u2014 End your session"
    )
    buttons = [
        [InlineKeyboardButton("List Workflows", callback_data="menu:workflows")],
        [InlineKeyboardButton("Create Workflow", callback_data="menu:create")],
        [InlineKeyboardButton("Run Workflow", callback_data="menu:run")],
    ]
    markup = InlineKeyboardMarkup(buttons)

    await update.effective_chat.send_message(
        menu_text, parse_mode=ParseMode.HTML, reply_markup=markup,
    )
    metrics.record_command()


async def cmd_logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /logout command."""
    tid = update.effective_user.id
    delete_user_session(tid)
    await update.message.reply_text(
        _section_plain("Signed out", "Your session has ended. Use /login when you need workflow access again.")
    )
    metrics.record_command()


def build_login_conversation() -> ConversationHandler:
    """Build the ConversationHandler for /login."""
    return ConversationHandler(
        entry_points=[CommandHandler("login", _login_entry)],
        states={
            AWAITING_USERNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _receive_username),
            ],
            AWAITING_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _receive_password),
            ],
        },
        fallbacks=[CommandHandler("cancel", _cancel_login)],
        per_user=True,
        per_chat=False,
    )
