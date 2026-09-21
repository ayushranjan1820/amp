"""
Chat handlers: free-text messages, /start, /help, /new.

Also contains helper functions for calling the AI agent,
sending files/BPMN artifacts, message truncation, and SSE parsing.
"""

import asyncio
import html
import io
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import List, Optional, Tuple

import httpx
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .. import config
from .. import http_client
from ..session_store import get_user_session, get_chat_session, set_chat_session, delete_chat_session
from ..rate_limiter import check_rate_limit, RateLimitExceeded
from ..health import metrics

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _escape_md(text: str) -> str:
    special = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for ch in special:
        text = text.replace(ch, f'\\{ch}')
    return text


def _rule_line(width: int = 28) -> str:
    return "\u2500" * width


def _section_plain(title: str, body: str) -> str:
    r = _rule_line()
    return f"{r}\n{title}\n{r}\n{body.strip()}"


def truncate_for_telegram(text: str, max_len: int = config.TG_MESSAGE_MAX_LEN) -> list:
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_len)
        if split_at <= 0:
            split_at = text.rfind(" ", max(0, max_len - 1200), max_len)
        if split_at <= 0:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n").lstrip(" ")
    return chunks


# ---------------------------------------------------------------------------
# SSE parser for /api/global-chat
# ---------------------------------------------------------------------------

def _parse_global_chat_sse(response_text: str) -> Tuple[str, str, Optional[str], Optional[str]]:
    """Parse SSE body. Returns (response, session_id, download_url, bpmn_xml)."""
    result_text = ""
    chunk_parts: List[str] = []
    session_id_out = ""
    download_url: Optional[str] = None
    bpmn_xml: Optional[str] = None

    for line in response_text.split("\n"):
        line = line.strip()
        if not line.startswith("data: "):
            continue
        try:
            envelope = json.loads(line[6:])
        except json.JSONDecodeError:
            continue
        evt = envelope.get("event")
        payload = envelope.get("data")
        if evt == "response_chunk" and isinstance(payload, dict):
            ch = payload.get("chunk")
            if ch:
                chunk_parts.append(str(ch))
        elif evt == "done" and isinstance(payload, dict):
            if payload.get("response") is not None:
                result_text = str(payload.get("response") or "")
            session_id_out = str(payload.get("session_id") or session_id_out or "")
            if payload.get("download_url"):
                download_url = payload.get("download_url")
            if payload.get("bpmn_xml"):
                bpmn_xml = payload.get("bpmn_xml")

    if not result_text.strip():
        result_text = "".join(chunk_parts)
    return result_text, session_id_out, download_url, bpmn_xml


# ---------------------------------------------------------------------------
# BPMN rendering
# ---------------------------------------------------------------------------

def _bpmn_xml_to_png_bytes(bpmn_xml: str) -> Optional[bytes]:
    """Render BPMN XML to PNG using bpmn-to-image (Puppeteer). Requires Node/npx."""
    if shutil.which("npx") is None:
        logger.info("BPMN PNG: npx not on PATH; skipping image render.")
        return None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bpmn_path = tmp_path / "diagram.bpmn"
            png_path = tmp_path / "diagram.png"
            bpmn_path.write_text(bpmn_xml, encoding="utf-8")
            spec = f"{bpmn_path}:{png_path}"
            cmd = ["npx", "--yes", "bpmn-to-image@0.10.0", "--no-footer", spec]
            r = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=config.BPMN_RENDER_TIMEOUT, cwd=str(tmp_path),
            )
            if r.returncode != 0:
                logger.info("bpmn-to-image exit %s: %s", r.returncode, (r.stderr or r.stdout or "")[:400])
                return None
            if not png_path.is_file():
                return None
            return png_path.read_bytes()
    except Exception as e:
        logger.warning("BPMN PNG render failed: %s", e)
        return None


async def send_bpmn_artifacts(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    bpmn_xml: str,
    *,
    caption: str = "BPMN 2.0 diagram (open with Camunda Modeler, VS Code, or compatible tools).",
) -> None:
    """Send BPMN as a document; optionally a PNG preview."""
    text = (bpmn_xml or "").strip()
    if not text:
        return
    try:
        bio = io.BytesIO(text.encode("utf-8"))
        bio.name = "diagram.bpmn"
        await context.bot.send_document(
            chat_id=chat_id, document=bio, filename="diagram.bpmn",
            caption=caption[:config.TG_CAPTION_MAX_LEN],
        )
    except Exception as e:
        logger.warning("Failed to send BPMN document: %s", e, exc_info=True)

    if not config.BPMN_RENDER_ENABLED:
        return
    png = await asyncio.to_thread(_bpmn_xml_to_png_bytes, text)
    if not png:
        await context.bot.send_message(
            chat_id=chat_id,
            text=_section_plain(
                "Diagram preview",
                "A PNG preview could not be generated. The BPMN file attached above is complete; "
                "open it in your modeling tool.",
            ),
        )
        return
    try:
        pic = io.BytesIO(png)
        pic.name = "diagram.png"
        await context.bot.send_photo(
            chat_id=chat_id, photo=pic, caption="BPMN diagram (image preview)",
        )
    except Exception as e:
        logger.warning("Failed to send BPMN preview image: %s", e, exc_info=True)


# ---------------------------------------------------------------------------
# File download & delivery
# ---------------------------------------------------------------------------

async def download_and_send_file(
    chat_id: int, download_url: str,
    context: ContextTypes.DEFAULT_TYPE, caption: str = "",
) -> None:
    """Download a file from the API server and send it as a Telegram document."""
    try:
        if download_url.startswith("/"):
            url = f"{config.API_BASE_URL}{download_url}"
        else:
            url = download_url

        resp = await http_client.get_with_retry(url, timeout=config.FILE_DOWNLOAD_TIMEOUT)
        if resp.status_code != 200:
            await context.bot.send_message(
                chat_id=chat_id,
                text=_section_plain(
                    "File delivery",
                    f"Your file was created but could not be retrieved (HTTP {resp.status_code}).\n\nDirect link:\n{url}",
                ),
            )
            return

        filename = download_url.split("/")[-1] if "/" in download_url else "file"
        cd = resp.headers.get("content-disposition", "")
        if "filename=" in cd:
            filename = cd.split("filename=")[-1].strip('" ')

        file_bytes = io.BytesIO(resp.content)
        file_bytes.name = filename
        await context.bot.send_document(
            chat_id=chat_id, document=file_bytes,
            caption=(caption[:config.TG_CAPTION_MAX_LEN] if caption else f"Attachment: {filename}"),
            filename=filename,
        )
    except Exception as e:
        logger.error("Failed to send file: %s", e, exc_info=True)
        fallback_url = f"{config.API_BASE_URL}{download_url}" if download_url.startswith("/") else download_url
        await context.bot.send_message(
            chat_id=chat_id,
            text=_section_plain(
                "File delivery",
                f"The file could not be sent via Telegram ({str(e)[:200]}).\n\n"
                f"Try this URL in your browser:\n{fallback_url}",
            ),
        )


# ---------------------------------------------------------------------------
# Agent call
# ---------------------------------------------------------------------------

async def call_agent(query: str, session_id: str | None = None) -> tuple:
    """Call /api/global-chat. Returns (response_text, session_id, download_url, bpmn_xml)."""
    payload = {"query": query, "session_id": session_id, "skip_save": False}
    try:
        response = await http_client.post_with_retry(
            f"{config.API_BASE_URL}/api/global-chat",
            json=payload,
            headers={"Accept": "text/event-stream"},
            timeout=config.AGENT_CALL_TIMEOUT,
        )
    except Exception:
        return (
            "The service is currently unavailable. Please try again later.",
            session_id or "", None, None,
        )

    if response.status_code != 200:
        return (
            f"The service returned an error (HTTP {response.status_code}). Please try again later.",
            session_id or "", None, None,
        )

    result_text, result_session_id, download_url, bpmn_xml = _parse_global_chat_sse(response.text)
    if not result_session_id:
        result_session_id = session_id or ""
    if not result_text:
        result_text = "No response was returned. Please try again or rephrase your request."
    return result_text, result_session_id, download_url, bpmn_xml


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = get_user_session(update.effective_user.id)

    lines = [
        "🤖 <b>AI Agents Platform</b>",
        "<i>Multi-agent chat and workflow automation</i>",
        "",
    ]

    if session:
        username = html.escape(session.get("username", ""))
        role = html.escape(session.get("user", {}).get("role", "user"))
        lines += [f"👤 Signed in as <b>{username}</b> · <code>{role}</code>", ""]
    else:
        lines += ["⚠️ <i>Not signed in — use /login to access workflow commands.</i>", ""]

    lines += [
        "💬 <b>Chat</b>",
        "Send any message to chat with AI agents. <i>(Login required)</i>",
        "/new — Start a fresh conversation",
        "",
        "⚡ <b>Workflows</b>",
        "/login — Sign in (secure two-step flow)",
        "/workflows — List your saved workflows",
        "/run or /workflow — Pick and run a workflow",
        "/create <code>instruction</code> — Generate a workflow from a description",
        "/update <code>workflow_id instruction</code> — Update an existing workflow",
        "/detail <code>workflow_id</code> — Inspect definition and steps",
        "/delete <code>workflow_id</code> — Remove a workflow",
        "/logout — End your session",
        "/help — Show this overview",
    ]

    await update.message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )
    metrics.record_command()


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    delete_chat_session(chat_id)
    await update.message.reply_text(
        _section_plain("New conversation", "Your chat context has been reset. You may continue with your next message.")
    )
    metrics.record_command()


# ---------------------------------------------------------------------------
# Free-text message handler
# ---------------------------------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text:
        return

    # Auth gate: require login for free-text chat
    session = get_user_session(update.effective_user.id)
    if not session:
        await update.message.reply_text(
            _section_plain(
                "Sign in required",
                "Please sign in with /login to start chatting with AI agents.",
            )
        )
        return

    # Rate limiting
    try:
        await check_rate_limit(update.effective_user.id)
    except RateLimitExceeded as exc:
        await update.message.reply_text(
            _section_plain("Rate limit", f"Too many requests. Please wait {exc.retry_after:.0f}s and try again.")
        )
        metrics.record_error()
        return

    await update.message.chat.send_action("typing")
    logger.info("Chat %d: %s...", chat_id, user_text[:80])

    # Acknowledge immediately so the user knows the request is being processed.
    ack = await update.message.reply_text("Please wait, we are processing your request...")

    session_id = get_chat_session(chat_id)
    t0 = time.time()

    try:
        response_text, session_id, download_url, bpmn_xml = await call_agent(user_text, session_id)
        set_chat_session(chat_id, session_id)

        elapsed_ms = (time.time() - t0) * 1000
        metrics.record_message(elapsed_ms)

        # Remove the "please wait" acknowledgement before sending the real response.
        try:
            await ack.delete()
        except Exception:
            pass

        chunks = truncate_for_telegram(response_text)
        n_chunks = len(chunks)
        for i, chunk in enumerate(chunks):
            if n_chunks > 1:
                bar = _rule_line(28)
                if i == 0:
                    chunk = f"{bar}\nAssistant response\n{bar}\n\n{chunk}"
                else:
                    chunk = f"{bar}\nContinued ({i + 1} of {n_chunks})\n{bar}\n\n{chunk}"
            try:
                await update.message.reply_text(chunk, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(chunk)

        if bpmn_xml:
            await send_bpmn_artifacts(chat_id, context, bpmn_xml)
        if download_url:
            cap = response_text[:200].strip().replace("\n", " ") if response_text else ""
            cap = f"Deliverable \u2014 {cap}" if cap else "Deliverable attachment"
            await download_and_send_file(chat_id, download_url, context, caption=cap)

    except httpx.TimeoutException:
        metrics.record_error()
        try:
            await ack.delete()
        except Exception:
            pass
        await update.message.reply_text(
            _section_plain("Request timed out", "The assistant did not finish in time. Try again or narrow your request.")
        )
    except httpx.ConnectError:
        metrics.record_error()
        try:
            await ack.delete()
        except Exception:
            pass
        await update.message.reply_text(
            _section_plain("Service unavailable", "Could not reach the AI Agents API. Confirm the server is running.")
        )
    except Exception as e:
        metrics.record_error()
        logger.error("Error handling message: %s", e, exc_info=True)
        try:
            await ack.delete()
        except Exception:
            pass
        await update.message.reply_text(
            _section_plain("Error", f"Your message could not be processed: {str(e)[:200]}")
        )
