"""Shared scaffolding for the three Zoho workflow agents.

Each agent is a thin orchestrator over the service layer. Everything they have
in common lives here:

* building a request-scoped :class:`ZohoClient` plus its services
* the dry-run write gate, so a demo never sends real mail by accident
* LLM extraction of workflow inputs, with a deterministic fallback
* thinking-step emission and the response envelope the SSE wrapper expects
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional

from agents.base_ai_service import BaseAIService

from .config import ZohoSettings, get_settings
from .services import (
    ZohoCalendarService,
    ZohoCliqService,
    ZohoCRMService,
    ZohoDeskService,
    ZohoMailService,
)
from .zoho_auth import ZohoAuthError
from .zoho_client import ZohoAPIError, ZohoClient
from .zoho_mcp import ZohoMCPError
from .services.projects_service import ZohoProjectsService

_log = logging.getLogger("zoho_workflow")

ThinkingCallback = Optional[Callable[[Dict[str, Any]], Any]]

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


class ZohoWorkflowError(RuntimeError):
    """A workflow could not continue; the message is safe to show a user."""


@dataclass
class WorkflowContext:
    """Request-scoped transport plus one service per Zoho product.

    Two transports are supported and the services expose the same methods for
    both, so the workflow agents are transport-agnostic:

    * ``rest`` - direct Zoho REST APIs with an OAuth refresh token.
    * ``mcp``  - a pre-authorized Zoho MCP connection, where the console holds
      the authorization and this side only needs the connection URL.
    """

    settings: ZohoSettings
    client: Any  # ZohoClient in REST mode, ZohoMCPClient in MCP mode
    mail: Any = field(init=False)
    calendar: Any = field(init=False)
    crm: Any = field(init=False)
    projects: Any = field(init=False)
    desk: Any = field(init=False)
    cliq: Any = field(init=False)

    def __post_init__(self) -> None:
        if self.settings.uses_mcp:
            from .services.mcp_services import (
                McpCalendarService,
                McpCliqService,
                McpCRMService,
                McpDeskService,
                McpMailService,
                McpProjectsService,
            )

            self.mail = McpMailService(self.client, self.settings)
            self.calendar = McpCalendarService(self.client, self.settings)
            self.crm = McpCRMService(self.client, self.settings)
            self.projects = McpProjectsService(self.client, self.settings)
            self.desk = McpDeskService(self.client, self.settings)
            self.cliq = McpCliqService(self.client, self.settings)
        else:
            self.mail = ZohoMailService(self.client)
            self.calendar = ZohoCalendarService(self.client)
            self.crm = ZohoCRMService(self.client)
            self.projects = ZohoProjectsService(self.client)
            self.desk = ZohoDeskService(self.client)
            self.cliq = ZohoCliqService(self.client)

    @property
    def transport(self) -> str:
        return self.settings.backend

    async def aclose(self) -> None:
        await self.client.aclose()


class ZohoWorkflowAgent:
    """Base class for the Zoho workflow agents.

    Subclasses implement :meth:`run_workflow` and declare ``agent_name`` plus
    ``workflow_steps`` (used for progress messaging and documentation).
    """

    agent_name: str = "Zoho Workflow Agent"
    workflow_steps: List[str] = []
    # Products this workflow touches, surfaced in error messages.
    required_products: List[str] = []

    def __init__(self, ai_service: Optional[BaseAIService] = None, http: Optional[Any] = None):
        """``ai_service`` and ``http`` are injectable so tests can run with stubs."""
        self._ai_service = ai_service
        self._http = http
        self.sessions: Dict[str, Dict[str, Any]] = {}

    def build_context(self, settings: ZohoSettings) -> WorkflowContext:
        """Create the request-scoped client + services. Overridable in tests."""
        if settings.uses_mcp:
            from .zoho_mcp import ZohoMCPClient

            client: Any = ZohoMCPClient(settings.mcp_url, http=self._http)
        else:
            client = ZohoClient(settings, http=self._http)
        return WorkflowContext(settings=settings, client=client)

    # ------------------------------------------------------------------ #
    # Public entry point
    # ------------------------------------------------------------------ #
    async def process_query(
        self,
        query: str,
        session_id: Optional[str] = None,
        on_thinking_step: ThinkingCallback = None,
    ) -> Dict[str, Any]:
        """Run the workflow and return the standard response envelope."""
        thinking: List[Dict[str, Any]] = []

        def step(content: str, step_type: str = "thinking", tool_name: str = "") -> None:
            entry: Dict[str, Any] = {"type": step_type, "content": content}
            if tool_name:
                entry["tool_name"] = tool_name
            thinking.append(entry)
            if on_thinking_step:
                try:
                    on_thinking_step(entry)
                except Exception:  # a UI callback must never break the workflow
                    _log.debug("on_thinking_step callback raised", exc_info=True)

        settings = get_settings()
        if settings.uses_mcp:
            step(
                f"Starting {self.agent_name} over the pre-authorized Zoho MCP connection "
                "(the connection holds the authorization; no local Zoho tokens are used)"
            )
        else:
            step(f"Starting {self.agent_name} on the {settings.dc.upper()} Zoho data center")

        missing = settings.missing_credentials()
        if missing:
            return self._envelope(
                False,
                "Zoho is not connected yet. Add "
                + ", ".join(missing)
                + " in this agent's configuration, then run the workflow again.\n\n"
                + self._setup_hint(),
                thinking,
            )

        if settings.dry_run:
            step(
                "Dry-run mode is ON: the workflow will plan every Zoho write and show it, "
                "without sending mail or creating records. Set ZOHO_CONFIRM_WRITES=true "
                "(and ZOHO_DRY_RUN=false) to execute for real.",
                step_type="thinking",
            )

        context = self.build_context(settings)
        try:
            result = await self.run_workflow(query or "", context, step, session_id or "default")
            actions = result.get("actions", [])
            response = result.get("response") or self.render_summary(actions, settings, result)
            return self._envelope(
                result.get("success", True),
                response,
                thinking,
                actions=actions,
                dry_run=settings.dry_run,
                workflow=result.get("workflow", self.agent_name),
                data=result.get("data", {}),
            )
        except (ZohoWorkflowError, ZohoAuthError) as exc:
            step(f"Workflow stopped: {exc}", step_type="tool_result")
            return self._envelope(False, str(exc), thinking, dry_run=settings.dry_run)
        except (ZohoAPIError, ZohoMCPError) as exc:
            step(f"Zoho API call failed: {exc}", step_type="tool_result")
            return self._envelope(
                False,
                f"A Zoho API call failed: {exc}\n\nNothing further was attempted, so no partial "
                "records were left behind beyond any step already reported above.",
                thinking,
                dry_run=settings.dry_run,
            )
        except asyncio.TimeoutError:
            return self._envelope(
                False, "The Zoho workflow timed out. Retry, or narrow the request.", thinking
            )
        except Exception as exc:  # pragma: no cover - defensive
            _log.exception("%s failed", self.agent_name)
            return self._envelope(
                False, f"{self.agent_name} hit an unexpected error: {exc}", thinking
            )
        finally:
            await context.aclose()

    # Subclasses implement this.
    async def run_workflow(
        self,
        query: str,
        ctx: WorkflowContext,
        step: Callable[..., None],
        session_id: str,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Write gate
    # ------------------------------------------------------------------ #
    async def guarded_write(
        self,
        ctx: WorkflowContext,
        *,
        label: str,
        description: str,
        call: Callable[[], Awaitable[Dict[str, Any]]],
        step: Callable[..., None],
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a Zoho write, or describe it when dry-run is on.

        Returns an action record in both modes so the summary reads the same
        whether or not the write actually happened.
        """
        action: Dict[str, Any] = {
            "label": label,
            "description": description,
            "details": details or {},
            "executed": False,
            "skipped_reason": "",
        }
        if ctx.settings.dry_run:
            step(f"[dry run] Would {description}", step_type="tool_call", tool_name=label)
            action["skipped_reason"] = "dry_run"
            return action

        step(f"{description}", step_type="tool_call", tool_name=label)
        try:
            outcome = await call()
        except (ZohoAPIError, ZohoMCPError) as exc:
            step(f"{label} failed: {exc}", step_type="tool_result", tool_name=label)
            action["error"] = str(exc)
            return action
        action["executed"] = True
        action["result"] = outcome
        step(f"{label} done: {_short(outcome)}", step_type="tool_result", tool_name=label)
        return action

    # ------------------------------------------------------------------ #
    # LLM extraction
    # ------------------------------------------------------------------ #
    @property
    def ai(self) -> BaseAIService:
        if self._ai_service is None:
            self._ai_service = BaseAIService(agent_name=self.agent_name)
        return self._ai_service

    async def extract_json(
        self,
        prompt: str,
        *,
        fallback: Optional[Dict[str, Any]] = None,
        step: Optional[Callable[..., None]] = None,
    ) -> Dict[str, Any]:
        """Ask the LLM for a JSON object; fall back rather than fail the run."""
        from agents.JIRA_agent.helpers.llm_json_extract import parse_llm_json_object

        try:
            raw = await asyncio.to_thread(self.ai.call_genai, prompt)
            return parse_llm_json_object(raw)
        except Exception as exc:
            _log.info("%s LLM extraction fell back: %s", self.agent_name, exc)
            if step:
                step(
                    f"LLM extraction unavailable ({exc}); using rule-based extraction instead.",
                    step_type="tool_result",
                )
            if fallback is None:
                raise ZohoWorkflowError(
                    "Could not understand the request and no LLM is configured. "
                    "Check the LLM provider settings for this agent."
                ) from exc
            return fallback

    # ------------------------------------------------------------------ #
    # Rendering
    # ------------------------------------------------------------------ #
    def render_summary(
        self,
        actions: List[Dict[str, Any]],
        settings: ZohoSettings,
        result: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Markdown recap of what the workflow did (or would do)."""
        mode = "Dry run - nothing was sent or created" if settings.dry_run else "Executed against Zoho"
        lines = [f"### {self.agent_name}", f"**Mode:** {mode}", ""]
        if not actions:
            lines.append("No workflow actions were produced.")
            return "\n".join(lines)

        for i, action in enumerate(actions, 1):
            if action.get("executed"):
                marker = "Done"
            elif action.get("error"):
                marker = f"Failed - {action['error']}"
            elif action.get("skipped_reason") == "dry_run":
                marker = "Planned (dry run)"
            else:
                marker = "Skipped"
            lines.append(f"{i}. **{action['label']}** - {action['description']}")
            lines.append(f"   - Status: {marker}")
            for key, value in (action.get("details") or {}).items():
                if value:
                    lines.append(f"   - {key}: {value}")
            result_obj = action.get("result") or {}
            for id_key in ("message_id", "event_uid", "task_id", "thread_id", "note_id", "comment_id"):
                if result_obj.get(id_key):
                    lines.append(f"   - {id_key}: {result_obj[id_key]}")
            lines.append("")

        if settings.dry_run:
            lines.append(
                "_To run this for real, set `ZOHO_DRY_RUN=false` and `ZOHO_CONFIRM_WRITES=true` "
                "in this agent's configuration._"
            )
        return "\n".join(lines).strip()

    def _setup_hint(self) -> str:
        products = ", ".join(self.required_products) if self.required_products else "the Zoho products in use"
        return (
            "**Setup, option A (recommended) - Zoho MCP connection:** in the Zoho MCP console create a "
            f"connection with Authorization via Connection enabled, add {products} to it, then set "
            "`ZOHO_MCP_URL` to the connection's `/message` URL. The connection holds the authorization, "
            "so no client id, secret or refresh token is needed here.\n\n"
            "**Option B - direct REST:** create a Server-based or Self Client app in the Zoho API Console, "
            f"grant scopes for {products}, generate a refresh token, and set `ZOHO_CLIENT_ID`, "
            "`ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN` and `ZOHO_DC` (us, eu, in, au, jp, ca, cn, sa)."
        )

    def _envelope(
        self,
        success: bool,
        response: str,
        thinking: List[Dict[str, Any]],
        **extra: Any,
    ) -> Dict[str, Any]:
        payload = {
            "success": success,
            "response": response,
            "thinking_steps": thinking,
            "agent": self.agent_name,
        }
        payload.update(extra)
        return payload


# ---------------------------------------------------------------------- #
# Shared helpers
# ---------------------------------------------------------------------- #

def extract_emails(text: str) -> List[str]:
    """All email addresses in a blob of text, de-duplicated, order preserved."""
    seen: List[str] = []
    for match in EMAIL_RE.findall(text or ""):
        if match not in seen:
            seen.append(match)
    return seen


def parse_datetime_hint(value: Any, *, default_hour: int = 10) -> Optional[datetime]:
    """Parse an LLM-supplied date/time into a datetime.

    Accepts ISO 8601 (with or without a time), ``YYYY-MM-DD HH:MM`` and a few
    relative words. Returns ``None`` when nothing usable is present, so callers
    can ask the user instead of guessing.
    """
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None

    lowered = text.lower()
    now = datetime.now()
    relative = {
        "today": now.date(),
        "tomorrow": (now + timedelta(days=1)).date(),
        "day after tomorrow": (now + timedelta(days=2)).date(),
        "next week": (now + timedelta(days=7)).date(),
    }
    for word, day in relative.items():
        if lowered.startswith(word):
            hour_match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", lowered[len(word):])
            hour, minute = default_hour, 0
            if hour_match:
                hour = int(hour_match.group(1))
                minute = int(hour_match.group(2) or 0)
                meridiem = hour_match.group(3)
                if meridiem == "pm" and hour < 12:
                    hour += 12
                elif meridiem == "am" and hour == 12:
                    hour = 0
            return datetime(day.year, day.month, day.day, min(hour, 23), min(minute, 59))

    cleaned = text.replace("Z", "+00:00")
    for candidate in (cleaned, cleaned.replace(" ", "T")):
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
        except ValueError:
            continue

    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%d %b %Y %H:%M", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def next_business_hour(base: Optional[datetime] = None, *, hour: int = 10, days_ahead: int = 1) -> datetime:
    """A sensible default meeting slot: next weekday at ``hour``."""
    start = (base or datetime.now()) + timedelta(days=days_ahead)
    while start.weekday() >= 5:  # Saturday/Sunday
        start += timedelta(days=1)
    return start.replace(hour=hour, minute=0, second=0, microsecond=0)


def _short(value: Any, limit: int = 160) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


__all__ = [
    "EMAIL_RE",
    "ThinkingCallback",
    "WorkflowContext",
    "ZohoWorkflowAgent",
    "ZohoWorkflowError",
    "extract_emails",
    "next_business_hour",
    "parse_datetime_hint",
]
