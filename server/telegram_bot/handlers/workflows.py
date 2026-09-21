"""
Workflow command handlers: /workflows, /run, /create, /detail, /delete.
"""

import html
import json
import logging
from typing import Any, Dict, List, Optional, Set

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .. import config
from ..auth import require_auth
from ..session_store import get_user_session
from ..health import metrics
from .chat import (
    _escape_md,
    _rule_line,
    _section_plain,
    truncate_for_telegram,
    send_bpmn_artifacts,
    download_and_send_file,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Server-side credential fallback
# ---------------------------------------------------------------------------
# When the Telegram bot runs a workflow whose agent_user_configs were saved in
# the DB, dispatch.py enters isolation mode (isolate_catalog_environment=True).
# Isolation strips any LLM env key (PWC_GENAI_*, GEMINI_*, LLM_PROVIDER …) not
# present in the merged config.  The browser avoids this because it always sends
# the full credential set from localStorage; the DB-stored config may only
# contain agent-specific keys (JIRA_BASE_URL, etc.) and omit LLM credentials.
#
# We capture the server's .env credentials once at import time (before they
# are scrubbed) and backfill them into each agent's config dict so isolation
# mode has complete data.  For workflows where the DB has NULL configs, we
# construct full configs from .env + catalog defaults.


def _get_all_server_env_defaults() -> Dict[str, str]:
    """Return all non-empty server .env values (cached at first call)."""
    if not hasattr(_get_all_server_env_defaults, "_cache"):
        try:
            from dotenv import dotenv_values
            from pathlib import Path
            env_file = Path(__file__).resolve().parents[2] / ".env"
            vals = dotenv_values(env_file) if env_file.exists() else {}
            _get_all_server_env_defaults._cache = {
                k: v for k, v in vals.items() if v
            }
        except Exception:
            _get_all_server_env_defaults._cache = {}
    return _get_all_server_env_defaults._cache


def _backfill_server_credentials(agent_cfgs: Dict, steps: list) -> Dict:
    """Ensure every agent entry has server .env defaults for catalog-declared keys.

    For each agent in the workflow steps, look up its catalog-declared config
    keys and fill any missing values from the server .env file.
    Agent-saved values always take priority over .env defaults.
    """
    from user_config import get_catalog_env_keys_for_agent, get_agent_display_name_by_id

    all_env = _get_all_server_env_defaults()
    if not all_env:
        return agent_cfgs

    step_agent_ids = {s.get("agent_id") for s in steps if s.get("agent_id")}

    filled: Dict = {}
    for agent_id in step_agent_ids:
        cfg = dict(agent_cfgs.get(agent_id, {}))
        display_name = get_agent_display_name_by_id(agent_id)
        if display_name:
            catalog_keys = get_catalog_env_keys_for_agent(display_name)
            for key in catalog_keys:
                if key not in cfg or not cfg.get(key, "").strip():
                    env_val = all_env.get(key)
                    if env_val:
                        cfg[key] = env_val
        filled[agent_id] = cfg

    # Preserve any extra agents in agent_cfgs not covered by steps
    for agent_id, cfg in agent_cfgs.items():
        if agent_id not in filled:
            filled[agent_id] = cfg

    return filled


def _build_full_agent_configs_from_server(steps: list) -> Optional[Dict]:
    """Build complete agent configs from server .env + catalog defaults.

    Called when the DB has no stored agent_user_configs (NULL).  Constructs
    configs from catalog ``default_config`` plus .env values for each agent
    referenced in the workflow steps.
    """
    from user_config import (
        get_catalog_env_keys_for_agent,
        get_agent_display_name_by_id,
        get_default_config_for_agent,
    )

    all_env = _get_all_server_env_defaults()
    step_agent_ids = [s.get("agent_id") for s in steps if s.get("agent_id")]
    if not step_agent_ids:
        return None

    configs: Dict = {}
    for agent_id in step_agent_ids:
        display_name = get_agent_display_name_by_id(agent_id)
        if not display_name:
            continue

        # Start with catalog default_config
        cfg = dict(get_default_config_for_agent(display_name))

        # Fill any catalog-declared key from .env
        catalog_keys = get_catalog_env_keys_for_agent(display_name)
        for key in catalog_keys:
            if (key not in cfg or not cfg.get(key, "").strip()) and all_env.get(key):
                cfg[key] = all_env[key]

        if cfg:
            configs[agent_id] = cfg

    return configs if configs else None


# Import orchestrator lazily to avoid circular imports at module level.
_orchestrator = None


def _get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        from workflow import orchestrator as _orch
        _orchestrator = _orch
    return _orchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _escape_html(text: str) -> str:
    return html.escape(text or "", quote=False)


def _escape_html_name_multiline(name: str, max_segment: int = 3600) -> str:
    if not name:
        return ""
    parts: List[str] = []
    for line in name.splitlines():
        esc = html.escape(line)
        while len(esc) > max_segment:
            parts.append(esc[:max_segment])
            esc = esc[max_segment:]
        if esc:
            parts.append(esc)
    return "<br/>".join(parts)


def _pack_html_blocks(blocks: List[str], max_len: int = config.TG_HTML_BLOCK_MAX_LEN) -> List[str]:
    out: List[str] = []
    cur: List[str] = []
    cur_len = 0
    sep = "\n\n"
    for b in blocks:
        b = (b or "").strip()
        if not b:
            continue
        extra = len(sep) if cur else 0
        if cur_len + extra + len(b) > max_len and cur:
            out.append(sep.join(cur))
            cur = [b]
            cur_len = len(b)
        elif len(b) > max_len:
            if cur:
                out.append(sep.join(cur))
                cur = []
                cur_len = 0
            sub = b.split("<br/>")
            piece_buf = ""
            for s in sub:
                candidate = piece_buf + ("<br/>" if piece_buf else "") + s
                if len(candidate) <= max_len:
                    piece_buf = candidate
                else:
                    if piece_buf:
                        out.append(piece_buf)
                    piece_buf = s
                    while len(piece_buf) > max_len:
                        out.append(piece_buf[:max_len])
                        piece_buf = piece_buf[max_len:]
            if piece_buf:
                out.append(piece_buf)
        else:
            cur.append(b)
            cur_len += extra + len(b)
    if cur:
        out.append(sep.join(cur))
    return out if out else [""]


def _check_workflow_access(session: Dict, wf: Dict) -> bool:
    user = session.get("user", {})
    if user.get("role") in ("admin", "super_admin"):
        return True
    return wf.get("user_id") == user.get("id")


def _workflow_definition_dict(wf: Dict) -> Dict:
    d = wf.get("definition")
    if d is None:
        return {}
    if isinstance(d, dict):
        return d
    if isinstance(d, str):
        try:
            parsed = json.loads(d)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _workflow_step_count(wf: Dict) -> int:
    steps = _workflow_definition_dict(wf).get("steps")
    return len(steps) if isinstance(steps, list) else 0


def _run_workflow_inline_button_text(
    index: int, name: str, max_len: int = config.TG_INLINE_BTN_MAX_LEN,
) -> str:
    raw = (name or "Untitled").strip() or "Untitled"
    single_line = " ".join(line.strip() for line in raw.splitlines() if line.strip()) or "Untitled"
    prefix = f"\u25b6 {index} \u00b7 "
    budget = max_len - len(prefix)
    if budget < 4:
        return (f"\u25b6{index}")[:max_len]
    if len(single_line) <= budget:
        return (prefix + single_line)[:max_len]
    return (prefix + single_line[: budget - 1] + "\u2026")[:max_len]


def _fmt_workflow_step_banner(
    step_num: int, total_steps: int, agent_label: str,
    status_title: str, status_detail: str = "",
) -> str:
    lines = [
        _rule_line(32), "WORKFLOW EXECUTION",
        f"Step {step_num} of {total_steps}  \u00b7  {agent_label}",
        _rule_line(32), status_title,
    ]
    if status_detail.strip():
        lines.append(status_detail.strip())
    lines.append(_rule_line(32))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@require_auth
async def cmd_workflows(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = context.user_data["session"]
    orch = _get_orchestrator()
    try:
        orch.init_workflow_db()
        user = session["user"]
        is_admin = user.get("role") in ("admin", "super_admin")
        workflows = orch.list_workflows(user_id=user["id"], is_admin=is_admin)

        if not workflows:
            await update.message.reply_text(
                _section_plain("No workflows", "You do not have any saved workflows yet. Use /create to generate one.")
            )
            return

        lines = ["*Saved workflows*\n"]
        for i, wf in enumerate(workflows[:20], 1):
            name = _escape_md(wf.get("name", "Untitled"))
            wf_id = wf.get("id", "")
            short_id = wf_id[:8] if wf_id else "?"
            step_count = _workflow_step_count(wf)
            step_word = "step" if step_count == 1 else "steps"
            lines.append(f"{i}\\. *{name}* \u2014 {step_count} {step_word}\n   ID: `{_escape_md(short_id)}\\.\\.\\. `")

        lines.append("\n_Use /run to execute a workflow\\._")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)
        metrics.record_command()

    except Exception as e:
        logger.exception("Failed to list workflows")
        metrics.record_error()
        await update.message.reply_text(
            _section_plain("Request failed", f"Workflows could not be listed: {str(e)[:200]}")
        )


@require_auth
async def cmd_run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = context.user_data["session"]

    if context.args:
        workflow_id = context.args[0]
        await _execute_workflow(update, workflow_id, context=context, session=session)
        return

    orch = _get_orchestrator()
    try:
        orch.init_workflow_db()
        user = session["user"]
        is_admin = user.get("role") in ("admin", "super_admin")
        workflows = orch.list_workflows(user_id=user["id"], is_admin=is_admin)

        if not workflows:
            await update.message.reply_text(
                _section_plain("No workflows", "You do not have any saved workflows. Use /create to add one.")
            )
            return

        total = len(workflows)
        listed = workflows[:config.RUN_PICKER_MAX_LISTED]
        n_listed = len(listed)
        n_buttons = min(n_listed, config.RUN_PICKER_MAX_BUTTONS)

        header_lines = [
            "<b>\u26a1 Run workflow</b>",
            "<i>Each title and ID is shown in full. Tap <b>\u25b6</b> with the same number.</i>",
        ]
        if total > n_listed:
            header_lines.append(
                f"<i>Listing the <b>{n_listed}</b> most recently updated of <b>{total}</b>. "
                "Open /workflows for the full set, or use <code>/run &lt;workflow_id&gt;</code>.</i>"
            )
        elif n_listed > n_buttons:
            header_lines.append(
                f"<i>Inline buttons cover rows <b>1\u2013{n_buttons}</b>; for rows below, use "
                "<code>/run &lt;workflow_id&gt;</code> with the ID shown.</i>"
            )
        header = "\n".join(header_lines)
        sep = "\u2500" * 28
        blocks: List[str] = [f"{header}\n\n{sep}"]

        for i, wf in enumerate(listed, 1):
            name_html = _escape_html_name_multiline(wf.get("name") or "Untitled")
            wf_id = wf.get("id") or ""
            wid_html = _escape_html(wf_id)
            sc = _workflow_step_count(wf)
            sw = "step" if sc == 1 else "steps"
            blocks.append(f"<b>{i}.</b> {name_html}\n   <i>{sc} {sw}</i> \u00b7 <code>{wid_html}</code>")

        for chunk in _pack_html_blocks(blocks, max_len=config.TG_HTML_BLOCK_MAX_LEN):
            await update.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)

        tail_lines = [
            "<b>\u25b6 Choose</b>",
            f"<i>Numbers match the list above \u00b7 <b>1\u2013{n_buttons}</b> (newest first).</i>",
        ]
        if n_listed > n_buttons:
            tail_lines.append(
                f"<i>For rows <b>{n_buttons + 1}\u2013{n_listed}</b>, send "
                "<code>/run &lt;paste_workflow_id&gt;</code>.</i>"
            )
        tail = "\n".join(tail_lines)
        buttons = []
        for i in range(1, n_buttons + 1):
            wf_btn = listed[i - 1]
            label = _run_workflow_inline_button_text(i, wf_btn.get("name", "Untitled"))
            buttons.append([InlineKeyboardButton(label, callback_data=f"run:{wf_btn.get('id', '')}")])
        markup = InlineKeyboardMarkup(buttons)
        await update.message.reply_text(tail, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)
        metrics.record_command()

    except Exception as e:
        logger.exception("Failed to list workflows for run")
        metrics.record_error()
        await update.message.reply_text(
            _section_plain("Request failed", f"Workflows could not be loaded: {str(e)[:200]}")
        )


@require_auth
async def cmd_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = context.user_data["session"]
    orch = _get_orchestrator()

    instruction = " ".join(context.args) if context.args else ""
    if not instruction.strip():
        await update.message.reply_text(
            _section_plain(
                "Create workflow",
                "Format:\n/create <describe the process you want automated>\n\n"
                "Examples:\n"
                "\u2022 /create Research a company and draft an executive summary\n"
                "\u2022 /create Gather recent market news and synthesize key themes\n"
                "\u2022 /create Map a multi-step approval process across agents",
            )
        )
        return

    await update.message.reply_text(
        f"*Generating workflow*\nInstruction:\n_{_escape_md(instruction)}_\n\n"
        f"_This may take a moment\\._",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    await update.effective_chat.send_action("typing")

    try:
        result = await orch.generate_workflow(instruction)
        wf_data = result if isinstance(result, dict) else {}
        wf_name = wf_data.get("name", "Generated Workflow")
        steps = wf_data.get("steps", [])
        mermaid = wf_data.get("mermaid", wf_data.get("mermaid_code", ""))

        orch.init_workflow_db()
        user = session["user"]
        definition = {"name": wf_name, "steps": steps}
        wf_id = orch.save_workflow(None, wf_name, instruction, definition, mermaid, user_id=user["id"])

        lines = [f"*Workflow created*\nName: *{_escape_md(wf_name)}*\n"]
        for s in steps:
            sn = s.get("step_number", "?")
            agent = s.get("agent_name", s.get("agent_id", "Agent"))
            q = s.get("query", "")[:120]
            deps = s.get("depends_on", [])
            dep_str = f" \\(after step {', '.join(str(d) for d in deps)}\\)" if deps else ""
            lines.append(f"  {sn}\\. *{_escape_md(str(agent))}*{dep_str}\n     _{_escape_md(q)}_")

        lines.append(f"\n*Workflow ID*\n`{_escape_md(wf_id)}`")
        buttons = [[InlineKeyboardButton("Run workflow", callback_data=f"run:{wf_id}")]]
        markup = InlineKeyboardMarkup(buttons)

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2, reply_markup=markup)
        metrics.record_command()

    except Exception as e:
        logger.exception("Failed to generate workflow")
        metrics.record_error()
        await update.message.reply_text(
            _section_plain("Generation failed", f"The workflow could not be created: {str(e)[:300]}")
        )


@require_auth
async def cmd_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = context.user_data["session"]
    orch = _get_orchestrator()

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            _section_plain(
                "Update workflow",
                "Format:\n/update <workflow_id> <new instruction>\n\n"
                "Examples:\n"
                "\u2022 /update abc123 Research a company and draft a SWOT analysis\n"
                "\u2022 /update abc123 Add an email step after market research",
            )
        )
        return

    workflow_id = args[0]
    instruction = " ".join(args[1:])

    try:
        orch.init_workflow_db()
        wf = orch.get_workflow(workflow_id)
        if not wf:
            await update.message.reply_text(_section_plain("Not found", "No workflow exists for that ID."))
            return
        if not _check_workflow_access(session, wf):
            await update.message.reply_text(
                _section_plain("Access denied", "You are not authorized to update this workflow.")
            )
            return

        await update.message.reply_text(
            f"*Updating workflow*\nNew instruction:\n_{_escape_md(instruction)}_\n\n"
            f"_This may take a moment\\._",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        await update.effective_chat.send_action("typing")

        result = await orch.generate_workflow(instruction)
        wf_data = result if isinstance(result, dict) else {}
        wf_name = wf_data.get("name", wf.get("name", "Updated Workflow"))
        steps = wf_data.get("steps", [])
        mermaid = wf_data.get("mermaid", wf_data.get("mermaid_code", ""))

        user = session["user"]
        definition = {"name": wf_name, "steps": steps}
        orch.save_workflow(workflow_id, wf_name, instruction, definition, mermaid, user_id=user["id"])

        lines = [f"*Workflow updated*\nName: *{_escape_md(wf_name)}*\n"]
        for s in steps:
            sn = s.get("step_number", "?")
            agent = s.get("agent_name", s.get("agent_id", "Agent"))
            q = s.get("query", "")[:120]
            deps = s.get("depends_on", [])
            dep_str = f" \\(after step {', '.join(str(d) for d in deps)}\\)" if deps else ""
            lines.append(f"  {sn}\\. *{_escape_md(str(agent))}*{dep_str}\n     _{_escape_md(q)}_")

        lines.append(f"\n*Workflow ID*\n`{_escape_md(workflow_id)}`")
        buttons = [[InlineKeyboardButton("Run workflow", callback_data=f"run:{workflow_id}")]]
        markup = InlineKeyboardMarkup(buttons)

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2, reply_markup=markup)
        metrics.record_command()

    except Exception as e:
        logger.exception("Failed to update workflow")
        metrics.record_error()
        await update.message.reply_text(
            _section_plain("Update failed", f"The workflow could not be updated: {str(e)[:300]}")
        )


@require_auth
async def cmd_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = context.user_data["session"]
    orch = _get_orchestrator()

    if not context.args:
        await update.message.reply_text(_section_plain("Workflow details", "Format:\n/detail <workflow_id>"))
        return

    workflow_id = context.args[0]
    try:
        orch.init_workflow_db()
        wf = orch.get_workflow(workflow_id)
        if not wf:
            await update.message.reply_text(_section_plain("Not found", "No workflow exists for that ID."))
            return
        if not _check_workflow_access(session, wf):
            await update.message.reply_text(_section_plain("Access denied", "You are not authorized to view this workflow."))
            return

        name = wf.get("name", "Untitled")
        instruction = wf.get("instruction", "")
        definition = wf.get("definition", {})
        if isinstance(definition, str):
            definition = json.loads(definition)
        steps = definition.get("steps", [])

        lines = [f"*Workflow*\n*{_escape_md(name)}*\n"]
        if instruction:
            lines.append(f"*Original instruction*\n_{_escape_md(instruction[:300])}_\n")
        lines.append(f"*Steps* \\({len(steps)}\\)\n")
        for s in steps:
            sn = s.get("step_number", "?")
            agent = s.get("agent_name", s.get("agent_id", "Agent"))
            q = s.get("query", "")[:150]
            deps = s.get("depends_on", [])
            dep_str = f" \u2192 depends on step {', '.join(str(d) for d in deps)}" if deps else ""
            lines.append(f"  {sn}\\. *{_escape_md(str(agent))}*{_escape_md(dep_str)}\n     _{_escape_md(q)}_")

        wf_id = wf.get("id", workflow_id)
        buttons = [[InlineKeyboardButton("Run workflow", callback_data=f"run:{wf_id}")]]
        markup = InlineKeyboardMarkup(buttons)
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2, reply_markup=markup)
        metrics.record_command()

    except Exception as e:
        logger.exception("Failed to get workflow detail")
        metrics.record_error()
        await update.message.reply_text(
            _section_plain("Request failed", f"Details could not be loaded: {str(e)[:200]}")
        )


@require_auth
async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = context.user_data["session"]
    orch = _get_orchestrator()

    if not context.args:
        await update.message.reply_text(_section_plain("Delete workflow", "Format:\n/delete <workflow_id>"))
        return

    workflow_id = context.args[0]
    try:
        orch.init_workflow_db()
        wf = orch.get_workflow(workflow_id)
        if not wf:
            await update.message.reply_text(_section_plain("Not found", "No workflow exists for that ID."))
            return
        if not _check_workflow_access(session, wf):
            await update.message.reply_text(_section_plain("Access denied", "You are not authorized to delete this workflow."))
            return
        deleted = orch.delete_workflow(workflow_id)
        if deleted:
            await update.message.reply_text(_section_plain("Deleted", "The workflow has been removed from your account."))
        else:
            await update.message.reply_text(_section_plain("Not found", "The workflow could not be deleted (it may already be removed)."))
        metrics.record_command()

    except Exception as e:
        logger.exception("Failed to delete workflow")
        metrics.record_error()
        await update.message.reply_text(
            _section_plain("Request failed", f"The workflow could not be deleted: {str(e)[:200]}")
        )


# ---------------------------------------------------------------------------
# Workflow execution
# ---------------------------------------------------------------------------

async def _execute_workflow(
    update_or_query, workflow_id: str,
    *, is_callback: bool = False,
    session: Optional[Dict] = None,
    context: ContextTypes.DEFAULT_TYPE = None,
) -> None:
    orch = _get_orchestrator()

    if is_callback:
        query = update_or_query
        chat = query.message.chat
        reply_fn = query.message.reply_text
        if not session:
            session = get_user_session(query.from_user.id)
    else:
        chat = update_or_query.effective_chat
        reply_fn = update_or_query.message.reply_text
        if not session:
            session = get_user_session(update_or_query.effective_user.id)

    try:
        orch.init_workflow_db()
        wf = orch.get_workflow(workflow_id)
        if not wf:
            await reply_fn(_section_plain("Not found", "No workflow exists for the ID you provided."))
            return
        if session and not _check_workflow_access(session, wf):
            await reply_fn(_section_plain("Access denied", "You are not authorized to run this workflow."))
            return

        wf_name = wf.get("name", "Untitled")
        definition = wf.get("definition", {})
        if isinstance(definition, str):
            definition = json.loads(definition)
        steps = definition.get("steps", [])

        exec_intro = (
            f"*Workflow started*\nName: *{_escape_md(wf_name)}*\n"
            f"Steps: {len(steps)}\n\n"
            f"_Execution is in progress\\. You will receive an update after each step completes\\._"
        )
        if is_callback:
            await update_or_query.edit_message_text(exec_intro, parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await reply_fn(exec_intro, parse_mode=ParseMode.MARKDOWN_V2)

        await chat.send_action("typing")

        raw_cfg = wf.get("agent_user_configs")
        agent_cfgs: Optional[Dict] = None
        if raw_cfg:
            if isinstance(raw_cfg, str):
                try:
                    raw_cfg = json.loads(raw_cfg)
                except json.JSONDecodeError:
                    raw_cfg = None
            if isinstance(raw_cfg, dict) and raw_cfg:
                agent_cfgs = _backfill_server_credentials(raw_cfg, steps)

        # When the DB has no stored configs, build from server .env + catalog defaults
        if agent_cfgs is None:
            agent_cfgs = _build_full_agent_configs_from_server(steps)

        total_steps = len(steps)
        step_by_num = {s["step_number"]: s for s in steps}
        sent_file_urls: list[str] = []
        sent_bpmn_steps: Set[int] = set()
        bot = context.bot if context else None

        async def on_step_update(step_num: int, status: str, payload: Any) -> None:
            if not bot:
                return
            st = step_by_num.get(step_num, {})
            agent_label = st.get("agent_name", st.get("agent_id", "Agent"))
            chat_id = chat.id
            try:
                if status == "running":
                    hdr = _fmt_workflow_step_banner(step_num, total_steps, agent_label, "Status: Running")
                    await bot.send_message(chat_id=chat_id, text=hdr)
                    task = (st.get("query") or "").strip()
                    if task:
                        for chunk in truncate_for_telegram("Step input / task:\n" + task):
                            await bot.send_message(chat_id=chat_id, text=chunk)
                elif status == "completed":
                    hdr = _fmt_workflow_step_banner(step_num, total_steps, agent_label, "Status: Completed")
                    await bot.send_message(chat_id=chat_id, text=hdr)
                    if isinstance(payload, dict):
                        resp_text = payload.get("response", "") or ""
                        dl_url = payload.get("download_url")
                        bx = payload.get("bpmn_xml")
                    else:
                        resp_text = str(payload or "")
                        dl_url = None
                        bx = None
                    if resp_text.strip():
                        for chunk in truncate_for_telegram(resp_text):
                            await bot.send_message(chat_id=chat_id, text=chunk)
                    if bx and context and step_num not in sent_bpmn_steps:
                        await send_bpmn_artifacts(chat_id, context, bx, caption=f"Step {step_num} \u2014 BPMN 2.0 diagram")
                        sent_bpmn_steps.add(step_num)
                    if dl_url and context:
                        await download_and_send_file(chat_id, dl_url, context)
                        sent_file_urls.append(dl_url)
                elif status == "failed":
                    err = payload if isinstance(payload, str) else str(payload or "Unknown error")
                    hdr = _fmt_workflow_step_banner(step_num, total_steps, agent_label, "Status: Failed")
                    for chunk in truncate_for_telegram(f"{hdr}\n\nDetails:\n{err}"):
                        await bot.send_message(chat_id=chat_id, text=chunk)
            except Exception as send_err:
                logger.warning("Telegram step update send failed: %s", send_err, exc_info=True)

        result = await orch.execute_workflow(definition, on_step_update=on_step_update, agent_user_configs=agent_cfgs)

        step_results = result.get("results", {})
        step_statuses = result.get("statuses", {})
        overall_success = result.get("success", False)

        outcome = "Completed successfully" if overall_success else "Completed with errors"
        summary_lines = [
            _rule_line(32), "WORKFLOW SUMMARY", _rule_line(32),
            f"Workflow: {wf_name}", f"Outcome: {outcome}", "", "Steps:",
        ]
        for step in steps:
            sn = step["step_number"]
            status = step_statuses.get(str(sn), "unknown")
            status_word = "Completed" if status == "completed" else "Failed" if status == "failed" else "Pending / unknown"
            agent_name = step.get("agent_name", step.get("agent_id", "Agent"))
            summary_lines.append(f"  \u2022 Step {sn} \u2014 {agent_name} \u2014 {status_word}")
        summary_lines.append(_rule_line(32))

        for chunk in truncate_for_telegram("\n".join(summary_lines)):
            await reply_fn(chunk)

        # Send any artifacts not already sent during streaming.
        for step in steps:
            sn = step["step_number"]
            sr = step_results.get(str(sn), {}) or {}
            dl_url = sr.get("download_url")
            bx = sr.get("bpmn_xml")
            if bx and sn not in sent_bpmn_steps and context:
                await send_bpmn_artifacts(chat.id, context, bx, caption=f"Step {sn} \u2014 BPMN 2.0 diagram")
                sent_bpmn_steps.add(sn)
            if dl_url and dl_url not in sent_file_urls and context:
                await download_and_send_file(chat.id, dl_url, context)

        metrics.record_command()

    except Exception as e:
        logger.exception("Failed to execute workflow")
        metrics.record_error()
        await reply_fn(_section_plain("Execution failed", f"The workflow could not be completed: {str(e)[:300]}"))


async def callback_run_workflow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    session = get_user_session(query.from_user.id)
    if not session:
        await query.edit_message_text(
            _section_plain("Session expired", "Please sign in again with /login to continue.")
        )
        return

    data = query.data
    if not data.startswith("run:"):
        return

    workflow_id = data[4:]
    await _execute_workflow(query, workflow_id, is_callback=True, context=context, session=session)


async def callback_menu_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle presses on the post-login capabilities menu inline buttons."""
    query = update.callback_query
    await query.answer()

    session = get_user_session(query.from_user.id)
    if not session:
        await query.edit_message_text(
            _section_plain("Session expired", "Please sign in again with /login.")
        )
        return

    data = query.data or ""
    action = data.split(":", 1)[1] if ":" in data else ""

    if action == "workflows":
        orch = _get_orchestrator()
        try:
            orch.init_workflow_db()
            user = session["user"]
            is_admin = user.get("role") in ("admin", "super_admin")
            workflows = orch.list_workflows(user_id=user["id"], is_admin=is_admin)

            if not workflows:
                await query.edit_message_text(
                    _section_plain("No workflows", "You do not have any saved workflows yet.\nUse /create to generate one.")
                )
                return

            lines = ["<b>Saved workflows</b>\n"]
            for i, wf in enumerate(workflows[:20], 1):
                name = _escape_html(wf.get("name", "Untitled"))
                wf_id = wf.get("id", "")
                short_id = wf_id[:8] if wf_id else "?"
                step_count = _workflow_step_count(wf)
                step_word = "step" if step_count == 1 else "steps"
                lines.append(f"{i}. <b>{name}</b> \u2014 {step_count} {step_word}\n   ID: <code>{_escape_html(short_id)}...</code>")

            lines.append("\n<i>Use /run to execute a workflow.</i>")
            await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.exception("Menu: failed to list workflows")
            await query.edit_message_text(
                _section_plain("Request failed", f"Workflows could not be listed: {str(e)[:200]}")
            )

    elif action == "create":
        await query.edit_message_text(
            _section_plain(
                "Create workflow",
                "Send a /create command followed by your instruction.\n\n"
                "Examples:\n"
                "\u2022 /create Research a company and draft an executive summary\n"
                "\u2022 /create Gather recent market news and synthesize key themes\n"
                "\u2022 /create Map a multi-step approval process across agents",
            )
        )

    elif action == "run":
        orch = _get_orchestrator()
        try:
            orch.init_workflow_db()
            user = session["user"]
            is_admin = user.get("role") in ("admin", "super_admin")
            workflows = orch.list_workflows(user_id=user["id"], is_admin=is_admin)

            if not workflows:
                await query.edit_message_text(
                    _section_plain("No workflows", "You do not have any saved workflows.\nUse /create to add one.")
                )
                return

            n_buttons = min(len(workflows), config.RUN_PICKER_MAX_BUTTONS)
            buttons = []
            for i in range(n_buttons):
                wf_btn = workflows[i]
                label = _run_workflow_inline_button_text(i + 1, wf_btn.get("name", "Untitled"))
                buttons.append([InlineKeyboardButton(label, callback_data=f"run:{wf_btn.get('id', '')}")])

            markup = InlineKeyboardMarkup(buttons)
            await query.edit_message_text(
                "<b>\u25b6 Choose a workflow to run</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
        except Exception as e:
            logger.exception("Menu: failed to list workflows for run")
            await query.edit_message_text(
                _section_plain("Request failed", f"Workflows could not be loaded: {str(e)[:200]}")
            )

    else:
        await query.edit_message_text(
            _section_plain("Unknown action", "Use /help to see available commands.")
        )
