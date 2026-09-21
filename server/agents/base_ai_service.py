"""Shared AI service base for all agents.

Consolidates the duplicated LLM-call boilerplate (headers, request body,
credential reading, continuation routing) that was previously copy-pasted
across 20+ agent ``ai_service.py`` files.

Usage — sync (requests-based)::

    from agents.base_ai_service import BaseAIService
    ai_service = BaseAIService()                       # Gemini flash, sync
    text = ai_service.call_genai("Summarize this…")

Usage — sync (httpx-based)::

    ai_service = BaseAIService(transport="httpx_sync")
    text = ai_service.call_genai("Summarize this…")

Usage — async::

    ai_service = BaseAIService(transport="async")
    text = await ai_service.call_genai_async("…")

Usage — custom model::

    ai_service = BaseAIService(default_model=os.getenv("MY_AGENT_MODEL", ""))
"""

from __future__ import annotations

import os
import re
from typing import Any, Callable, Dict, Optional


DEFAULT_MODEL = ""
DEFAULT_ENDPOINT = "https://genai-sharedservice-americas.pwc.com/completions"


class BaseAIService:
    """Unified LLM facade shared across agents.

    Parameters
    ----------
    default_model : str
        Model identifier included in every request body.
    default_temperature : float
        Default temperature when not overridden per-call.
    default_max_tokens : int
        Default max_tokens when not overridden per-call.
    timeout : int | float
        HTTP timeout in seconds.
    transport : str
        One of ``"requests"`` (sync, requests lib), ``"httpx_sync"`` (sync, httpx),
        ``"async"`` (async, httpx).
    agent_name : str
        Human-readable agent name used in Langfuse traces. When empty the name
        is derived automatically from the subclass module path.
    """

    def __init__(
        self,
        *,
        default_model: str = DEFAULT_MODEL,
        default_temperature: float = 0.7,
        default_max_tokens: int = 8192,
        timeout: int | float = 180,
        transport: str = "requests",
        agent_name: str = "",
    ):
        self.default_model = default_model
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens
        self.timeout = timeout
        self.transport = transport
        self._agent_name = agent_name

    # ── Agent-name helpers (used by Langfuse tracer) ──────────────────

    @property
    def _display_name(self) -> str:
        """Return the best available agent name for Langfuse traces.

        Priority: explicit ``agent_name`` kwarg → module-path derivation → class-name derivation.
        """
        if self._agent_name:
            return self._agent_name
        # Derive from module path: 'agents.Basic_agent.ai_service' → 'Basic Agent'
        module = type(self).__module__ or ""
        parts = module.split(".")
        if len(parts) >= 2 and parts[0] == "agents":
            folder = parts[1]  # e.g. 'Basic_agent', 'Trace_debugger_agent'
            name = re.sub(r"_[Aa]gent$", "", folder).replace("_", " ").strip()
            if name:
                return f"{name} Agent"
        # Fallback: class name without 'AIService' suffix, spaced
        class_name = re.sub(r"AIService$", "", type(self).__name__)
        spaced = re.sub(r"([A-Z])", r" \1", class_name).strip()
        return f"{spaced} Agent" if spaced else "Unknown Agent"

    def _stamp_langfuse_context(self) -> None:
        """Stamp agent name into Langfuse tracing context for the current thread.

        Called at the top of every LLM method.  Only overwrites the context when
        it is still at the default "unknown" / empty value — so a name set by
        ``_stream_agent_response`` at route-entry level is preserved; the derived
        class name is used as a fallback for paths that skipped route-level setup.
        """
        try:
            from langfuse_tracer import _read_agent_name, set_current_agent  # noqa: PLC0415
            if _read_agent_name() in ("", "unknown"):
                set_current_agent(self._display_name)
        except Exception:
            pass

    # ── Credential helpers (read per-call so injected env is always current) ──

    def _api_key(self) -> str:
        return os.getenv("PWC_GENAI_API_KEY") or os.getenv("GEMINI_API_KEY") or ""

    @property
    def api_key(self) -> str:
        """Env-backed PwC/Gemini key; same as ``_api_key()`` for agents that use ``if self.ai.api_key``."""
        return self._api_key()

    @property
    def llm_configured(self) -> bool:
        """True when the active ``LLM_PROVIDER`` has usable credentials (PwC, Ollama Cloud, or local)."""
        from agents.local_llm import is_llm_provider_configured  # noqa: PLC0415

        return is_llm_provider_configured()

    def _bearer_token(self) -> Optional[str]:
        return os.getenv("PWC_GENAI_BEARER_TOKEN")

    def _endpoint_url(self) -> str:
        return (
            os.getenv("PWC_GENAI_ENDPOINT_URL")
            or os.getenv("GEMINI_API_ENDPOINT")
            or DEFAULT_ENDPOINT
        )

    def _headers(self) -> Dict[str, str]:
        h: Dict[str, str] = {
            "accept": "application/json",
            "API-Key": self._api_key(),
            "Content-Type": "application/json",
        }
        bt = self._bearer_token()
        if bt:
            h["Authorization"] = f"Bearer {bt}"
        return h

    @staticmethod
    def _is_anthropic_model(model: str) -> bool:
        return "anthropic" in model.lower() or "claude" in model.lower()

    def _request_body(
        self,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        resolved_model = model or self.default_model
        is_anthropic = self._is_anthropic_model(resolved_model)

        body: Dict[str, Any] = {
            "model": resolved_model,
            "prompt": prompt,
            "max_tokens": max_tokens if max_tokens is not None else self.default_max_tokens,
            "presence_penalty": 0,
            "stream": False,
            "stream_options": None,
            "seed": 25,
            "stop": None,
        }

        temp = temperature if temperature is not None else self.default_temperature
        if is_anthropic:
            # Anthropic models reject requests with both temperature and top_p
            body["temperature"] = temp
        else:
            body["temperature"] = temp
            body["top_p"] = 1

        return body

    def _check_credentials(self) -> None:
        from agents.local_llm import (
            is_llm_provider_configured,
            describe_missing_llm_credentials,
        )
        if not is_llm_provider_configured():
            raise ValueError(describe_missing_llm_credentials())

    # ── Sync call (requests-based) ────────────────────────────────────

    def call_genai(
        self,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        on_stream_chunk: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Synchronous LLM call with auto-continuation.

        Dispatches to the appropriate continuation function based on ``self.transport``.
        """
        self._stamp_langfuse_context()
        self._check_credentials()
        body = self._request_body(prompt, temperature, max_tokens, model)

        if self.transport == "httpx_sync":
            from agents.llm_continuation import sync_call_with_continuation_httpx
            return sync_call_with_continuation_httpx(
                endpoint_url=self._endpoint_url(),
                headers=self._headers(),
                request_body=body,
                original_prompt=prompt,
                timeout=self.timeout,
            )

        from agents.llm_continuation import sync_call_with_continuation
        return sync_call_with_continuation(
            endpoint_url=self._endpoint_url(),
            headers=self._headers(),
            request_body=body,
            original_prompt=prompt,
            timeout=int(self.timeout),
            on_stream_chunk=on_stream_chunk,
        )

    # ── Async call ────────────────────────────────────────────────────

    async def call_genai_async(
        self,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
    ) -> str:
        """Async LLM call with auto-continuation."""
        self._stamp_langfuse_context()
        self._check_credentials()
        body = self._request_body(prompt, temperature, max_tokens, model)

        from agents.llm_continuation import async_call_with_continuation
        return await async_call_with_continuation(
            endpoint_url=self._endpoint_url(),
            headers=self._headers(),
            request_body=body,
            original_prompt=prompt,
            timeout=self.timeout,
        )

    # ── Convenience ───────────────────────────────────────────────────

    def build_prompt(self, system_message: str, user_message: str) -> str:
        return f"System: {system_message}\n\nUser: {user_message}"
