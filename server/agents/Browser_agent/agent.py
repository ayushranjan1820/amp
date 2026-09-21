"""Browser Automation Agent — natural-language → real browser execution.

Flow:
1. User describes tasks in plain English.
2. LLM planner → validated JSON steps (schema).
3. Shared browser pool provides a Playwright page per session (optional reuse).
4. Per step: LLM emits **JSON DSL only**; a deterministic executor maps DSL → Playwright
   (no exec()).  Context = accessibility snapshot + visible text + counts.
5. Optional critic LLM rechecks outcome; retries refresh the DSL on failure.
6. Exported script is generated from executed DSL bundles + logs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# (event, data) for SSE: "thinking" | "progress"
BrowserSSEEmit = Optional[Callable[[str, Dict[str, Any]], None]]

from .ai_service import ai_service
from .session_memory import session_memory
from .tools.step_planner import plan_roadmap
from .tools.step_validator import validate_planner_steps
from .tools.browser_executor import BrowserExecutor
from .tools.browser_pool import BrowserPool

logger = logging.getLogger(__name__)

LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# Keep SSE/UI alive during long blocking calls (planner LLM, Chromium launch, steps).
_LONG_WAIT_PROGRESS_SEC = 12.0
_BROWSER_PROGRESS_SEC = 15.0


def _start_progress_pulse_thread(
    emit: Callable[[str, Dict[str, Any]], None],
    *,
    stage: str,
    interval_sec: float,
    message_prefix: str,
) -> tuple[threading.Event, threading.Thread]:
    stop = threading.Event()

    def _loop() -> None:
        n = 0
        while not stop.wait(timeout=interval_sec):
            n += 1
            try:
                emit(
                    "progress",
                    {
                        "stage": stage,
                        "message": f"{message_prefix} ({int(n * interval_sec)}s)",
                    },
                )
            except Exception:
                logger.debug("progress pulse failed", exc_info=True)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    return stop, t


async def _async_progress_pulse(
    stop: asyncio.Event,
    emit: Callable[[str, Dict[str, Any]], None],
    *,
    stage: str,
    interval_sec: float,
    message_prefix: str,
) -> None:
    n = 0
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_sec)
            return
        except asyncio.TimeoutError:
            n += 1
            try:
                emit(
                    "progress",
                    {
                        "stage": stage,
                        "message": f"{message_prefix} ({int(n * interval_sec)}s)",
                    },
                )
            except Exception:
                logger.debug("async progress pulse failed", exc_info=True)


def _resolve_cdp_endpoint(request: Dict[str, Any]) -> Optional[str]:
    raw = (request.get("cdp_endpoint") or os.environ.get("PLAYWRIGHT_CDP_URL") or "").strip()
    return raw or None


def _default_persistent_profile_dir() -> Path:
    """Stable per-user folder for saved cookies (no user configuration)."""
    home = Path.home()
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else home / "AppData" / "Local"
        return base / "AgentsBrowserProfile"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "AgentsBrowserProfile"
    return home / ".local" / "share" / "agents-browser-profile"


def _browser_storage_paths(request: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """(cdp_url, persistent_profile_dir). CDP wins; disk profile is skipped when CDP is set."""
    cdp_url = _resolve_cdp_endpoint(request)
    if cdp_url:
        return cdp_url, None
    if not request.get("remember_logins", True):
        return None, None
    custom = (request.get("persistent_profile_dir") or "").strip()
    try:
        path = Path(custom).expanduser().resolve() if custom else _default_persistent_profile_dir()
        path.mkdir(parents=True, exist_ok=True)
        return None, str(path)
    except OSError as exc:
        logger.warning("Could not use persistent browser profile (%s): %s", custom or "default", exc)
        return None, None

_STANDALONE_SCRIPT_MAX_BYTES = 500_000
_STANDALONE_RUN_TIMEOUT_SEC = 900
_OUTPUT_TRUNCATE = 48_000


class BrowserAgent:
    """Orchestrates planning → browser execution → logging."""

    def __init__(self):
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._config_errors: List[str] = []
        self._check_dependencies()

    # ── dependency check ────────────────────────────────────────────

    def _check_dependencies(self):
        try:
            import playwright  # noqa: F401
        except ImportError:
            self._config_errors.append(
                "Playwright is not installed. Run: pip install playwright && python -m playwright install chromium"
            )

    # ── public entry point ──────────────────────────────────────────

    def process_chat(self, request: Dict[str, Any]) -> Dict[str, Any]:
        query: str = request.get("query", "").strip()
        session_id: str = request.get("session_id") or str(uuid.uuid4())
        clear_history: bool = request.get("clear_history", False)
        headless: bool = request.get("headless", True)
        cdp_url, persistent_profile_dir = _browser_storage_paths(request)
        if cdp_url:
            headless = False
        keep_browser_session: bool = request.get("keep_browser_session", True)
        enable_step_critic: bool = request.get("enable_step_critic", False)
        use_vision: bool = request.get("use_vision", True)
        use_grounded_verifier: bool = request.get("use_grounded_verifier", True)
        thinking: List[Dict[str, Any]] = []

        if clear_history:
            self._sessions.pop(session_id, None)
            session_memory.clear(session_id)
            BrowserPool.release_session(
                session_id,
                headless,
                close_context=True,
                cdp_url=cdp_url,
                persistent_profile_dir=persistent_profile_dir,
            )
            try:
                asyncio.run(
                    BrowserPool.async_release_session(
                        session_id,
                        headless,
                        close_context=True,
                        cdp_url=cdp_url,
                        persistent_profile_dir=persistent_profile_dir,
                    )
                )
            except RuntimeError:
                pass

        if self._config_errors:
            return {
                "success": False,
                "response": "**Configuration errors:**\n- " + "\n- ".join(self._config_errors),
                "query": query,
                "thinking_steps": [],
                "timestamp": datetime.now().isoformat(),
                "session_id": session_id,
            }

        script_rerun = (request.get("rerun_standalone_script") or "").strip()
        replay_steps = self._normalize_replay_steps(request.get("replay_steps_executed"))
        if script_rerun or replay_steps:
            try:
                return self._handle_script_rerun(
                    script_rerun,
                    replay_steps,
                    session_id,
                    headless,
                    thinking,
                    cdp_url=cdp_url,
                    persistent_profile_dir=persistent_profile_dir,
                    keep_browser_session=keep_browser_session,
                    enable_step_critic=enable_step_critic,
                    use_vision=use_vision,
                    use_grounded_verifier=use_grounded_verifier,
                    stream_emit=request.get("_sse_emit"),
                    label_query=query or "(Re-run exported Playwright script)",
                )
            except Exception as exc:
                logger.exception("BrowserAgent script re-run error")
                return {
                    "success": False,
                    "response": f"**Error running script:** {exc}",
                    "query": query,
                    "thinking_steps": thinking,
                    "timestamp": datetime.now().isoformat(),
                    "session_id": session_id,
                }

        if not query:
            return self._welcome()

        try:
            return self._run(
                query,
                session_id,
                headless,
                thinking,
                cdp_url=cdp_url,
                persistent_profile_dir=persistent_profile_dir,
                keep_browser_session=keep_browser_session,
                enable_step_critic=enable_step_critic,
                use_vision=use_vision,
                use_grounded_verifier=use_grounded_verifier,
                stream_emit=request.get("_sse_emit"),
            )
        except Exception as exc:
            logger.exception("BrowserAgent error")
            return {
                "success": False,
                "response": f"**Error:** {exc}",
                "query": query,
                "thinking_steps": thinking,
                "timestamp": datetime.now().isoformat(),
                "session_id": session_id,
            }

    def _validate_standalone_script_for_rerun(self, script: str) -> Optional[str]:
        if len(script.encode("utf-8")) > _STANDALONE_SCRIPT_MAX_BYTES:
            return f"Script exceeds maximum size ({_STANDALONE_SCRIPT_MAX_BYTES // 1000}KB)."
        if "Auto-generated Playwright script" not in script:
            return "Only exported Browser Automation Playwright scripts can be run from the UI."
        if "sync_playwright" not in script or "def main():" not in script:
            return "Script is missing expected Playwright export structure."
        return None

    def _run_standalone_script(
        self,
        script: str,
        session_id: str,
        thinking: List[Dict[str, Any]],
        stream_emit: BrowserSSEEmit = None,
        label_query: str = "",
    ) -> Dict[str, Any]:
        def _emit(ev: str, data: Dict[str, Any]) -> None:
            if stream_emit:
                try:
                    stream_emit(ev, data)
                except Exception:
                    logger.debug("stream_emit failed", exc_info=True)

        def _think(entry: Dict[str, Any]) -> None:
            thinking.append(entry)
            _emit("thinking", entry)

        bad = self._validate_standalone_script_for_rerun(script)
        if bad:
            return {
                "success": False,
                "response": f"**Cannot run script:** {bad}",
                "query": label_query,
                "thinking_steps": thinking,
                "timestamp": datetime.now().isoformat(),
                "session_id": session_id,
            }

        _think({
            "type": "execution",
            "content": "Re-running exported Playwright script in a server subprocess…",
        })
        _emit("progress", {"stage": "script", "message": "Writing script to a temporary file…"})

        safe_slug = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)[:48]
        script_path = LOGS_DIR / f"rerun_{safe_slug}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py"

        try:
            script_path.write_text(script, encoding="utf-8")
        except OSError as exc:
            return {
                "success": False,
                "response": f"**Could not write script file:** {exc}",
                "query": label_query,
                "thinking_steps": thinking,
                "timestamp": datetime.now().isoformat(),
                "session_id": session_id,
            }

        _emit("progress", {"stage": "script", "message": "Executing script (Playwright / Chromium)…"})

        env = os.environ.copy()
        proc: subprocess.CompletedProcess[str]
        try:
            proc = subprocess.run(
                [sys.executable, str(script_path)],
                capture_output=True,
                text=True,
                timeout=_STANDALONE_RUN_TIMEOUT_SEC,
                cwd=str(LOGS_DIR.parent),
                env=env,
            )
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "response": (
                    f"**Script timed out** after {_STANDALONE_RUN_TIMEOUT_SEC // 60} minutes.\n\n"
                    "Try a shorter flow or run the script manually on your machine."
                ),
                "query": label_query,
                "thinking_steps": thinking,
                "timestamp": datetime.now().isoformat(),
                "session_id": session_id,
            }
        finally:
            try:
                script_path.unlink(missing_ok=True)
            except OSError:
                pass

        def _trunc(s: str) -> str:
            if len(s) <= _OUTPUT_TRUNCATE:
                return s
            return s[:_OUTPUT_TRUNCATE] + "\n\n… [truncated]"

        out = _trunc((proc.stdout or "").strip() or "(no stdout)")
        err = _trunc((proc.stderr or "").strip() or "(no stderr)")
        ok = proc.returncode == 0

        _think({
            "type": "logging",
            "content": f"Subprocess finished with exit code {proc.returncode}.",
        })
        _emit("progress", {"stage": "script", "message": "Script subprocess finished."})

        response_md = "\n".join(
            [
                "# Playwright script re-run",
                "",
                f"**Request:** {label_query}",
                f"**Exit code:** `{proc.returncode}`",
                "",
                "---",
                "",
                "## stdout",
                "",
                f"```text\n{out}\n```",
                "",
                "---",
                "",
                "## stderr",
                "",
                f"```text\n{err}\n```",
                "",
            ]
        )

        return {
            "success": ok,
            "response": response_md,
            "query": label_query,
            "thinking_steps": thinking,
            "timestamp": datetime.now().isoformat(),
            "steps_executed": [],
            "generated_script": None,
            "execution_log": None,
            "html_report": None,
            "session_id": session_id,
            "session_history_preview": None,
        }

    def _normalize_replay_steps(self, raw: Any) -> List[Dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        out: List[Dict[str, Any]] = []
        for item in raw[:200]:
            if isinstance(item, dict):
                out.append(item)
        return out

    @staticmethod
    def _replay_steps_have_dsl(steps: List[Dict[str, Any]]) -> bool:
        for s in steps:
            b = s.get("dsl_bundle")
            if isinstance(b, dict) and b.get("actions"):
                return True
        return False

    def _handle_script_rerun(
        self,
        script_rerun: str,
        replay_steps: List[Dict[str, Any]],
        session_id: str,
        headless: bool,
        thinking: List[Dict[str, Any]],
        cdp_url: Optional[str],
        persistent_profile_dir: Optional[str],
        keep_browser_session: bool,
        enable_step_critic: bool,
        use_vision: bool,
        use_grounded_verifier: bool,
        stream_emit: BrowserSSEEmit,
        label_query: str,
    ) -> Dict[str, Any]:
        if not script_rerun.strip():
            return {
                "success": False,
                "response": "**Cannot run script:** No script body was sent.",
                "query": label_query,
                "thinking_steps": thinking,
                "timestamp": datetime.now().isoformat(),
                "session_id": session_id,
            }

        bad = self._validate_standalone_script_for_rerun(script_rerun)
        if bad:
            return {
                "success": False,
                "response": f"**Cannot run script:** {bad}",
                "query": label_query,
                "thinking_steps": thinking,
                "timestamp": datetime.now().isoformat(),
                "session_id": session_id,
            }

        if self._replay_steps_have_dsl(replay_steps):
            return self._replay_recorded_dsl_flow(
                replay_steps,
                label_query,
                session_id,
                headless,
                thinking,
                cdp_url=cdp_url,
                persistent_profile_dir=persistent_profile_dir,
                keep_browser_session=keep_browser_session,
                enable_step_critic=enable_step_critic,
                use_vision=use_vision,
                use_grounded_verifier=use_grounded_verifier,
                stream_emit=stream_emit,
            )

        return self._run_standalone_script(
            script_rerun,
            session_id,
            thinking,
            stream_emit=stream_emit,
            label_query=label_query,
        )

    def _replay_recorded_dsl_flow(
        self,
        replay_steps: List[Dict[str, Any]],
        query: str,
        session_id: str,
        headless: bool,
        thinking: List[Dict[str, Any]],
        cdp_url: Optional[str] = None,
        persistent_profile_dir: Optional[str] = None,
        keep_browser_session: bool = False,
        enable_step_critic: bool = False,
        use_vision: bool = True,
        use_grounded_verifier: bool = True,
        stream_emit: BrowserSSEEmit = None,
    ) -> Dict[str, Any]:
        def _emit(ev: str, data: Dict[str, Any]) -> None:
            if stream_emit:
                try:
                    stream_emit(ev, data)
                except Exception:
                    logger.debug("stream_emit failed", exc_info=True)

        def _think(entry: Dict[str, Any]) -> None:
            thinking.append(entry)
            _emit("thinking", entry)

        _think({
            "type": "execution",
            "content": f"Replaying {len(replay_steps)} recorded DSL step(s) in the browser (screenshots + report)…",
        })
        _emit(
            "progress",
            {
                "stage": "browser",
                "message": f"Opening browser — replaying up to {len(replay_steps)} recorded step(s)…",
            },
        )

        async def _browser_replay_workflow():
            stop_pulse = asyncio.Event()
            pulse_task = asyncio.create_task(
                _async_progress_pulse(
                    stop_pulse,
                    _emit,
                    stage="browser",
                    interval_sec=_BROWSER_PROGRESS_SEC,
                    message_prefix="Still replaying browser steps",
                )
            )
            try:
                page = await BrowserPool.async_acquire_page(
                    session_id,
                    headless=headless,
                    slow_mo=300,
                    cdp_url=cdp_url,
                    persistent_profile_dir=persistent_profile_dir,
                )
                ex = BrowserExecutor(
                    page,
                    use_step_critic=enable_step_critic,
                    use_vision=use_vision,
                    use_grounded_verifier=use_grounded_verifier,
                    on_sse=stream_emit,
                )
                try:
                    res = await ex.replay_recorded_bundles_async(replay_steps)
                    return res, ex
                finally:
                    await BrowserPool.async_release_session(
                        session_id,
                        headless,
                        close_context=not keep_browser_session,
                        cdp_url=cdp_url,
                        persistent_profile_dir=persistent_profile_dir,
                    )
            finally:
                stop_pulse.set()
                pulse_task.cancel()
                try:
                    await pulse_task
                except asyncio.CancelledError:
                    pass

        try:
            results, executor = asyncio.run(_browser_replay_workflow())
        except RuntimeError as exc:
            if "asyncio.run()" in str(exc) or "running event loop" in str(exc).lower():
                logger.warning("Falling back to sync browser pool for DSL replay: %s", exc)
                _hb_stop, _hb_thr = _start_progress_pulse_thread(
                    _emit,
                    stage="browser",
                    interval_sec=_BROWSER_PROGRESS_SEC,
                    message_prefix="Still replaying browser steps",
                )
                try:
                    page = BrowserPool.acquire_page(
                        session_id,
                        headless=headless,
                        slow_mo=300,
                        cdp_url=cdp_url,
                        persistent_profile_dir=persistent_profile_dir,
                    )
                    executor = BrowserExecutor(
                        page,
                        use_step_critic=enable_step_critic,
                        use_vision=use_vision,
                        use_grounded_verifier=use_grounded_verifier,
                        on_sse=stream_emit,
                    )
                    try:
                        results = executor.replay_recorded_bundles(replay_steps)
                    finally:
                        BrowserPool.release_session(
                            session_id,
                            headless,
                            close_context=not keep_browser_session,
                            cdp_url=cdp_url,
                            persistent_profile_dir=persistent_profile_dir,
                        )
                finally:
                    _hb_stop.set()
                    _hb_thr.join(timeout=2.0)
            else:
                raise

        steps_for_log = [
            {
                "step_number": r.get("step_number"),
                "action": r.get("action", ""),
                "description": r.get("description", ""),
            }
            for r in results
        ]

        _emit("progress", {"stage": "post", "message": "Replay finished — generating Playwright script export…"})
        standalone_script = executor.build_standalone_script(results, headless=headless)
        execution_log = self._build_execution_log(query, steps_for_log, results)

        log_file = LOGS_DIR / f"replay_{session_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        log_file.write_text(execution_log, encoding="utf-8")
        _think({"type": "logging", "content": f"Replay execution log saved to {log_file.name}"})

        _emit("progress", {"stage": "post", "message": "Building HTML report (screenshots embedded)…"})
        html_report_path = executor.build_html_report(query, results, session_id=session_id)
        _think({"type": "reporting", "content": f"HTML report saved to {Path(html_report_path).name}"})

        succeeded = sum(1 for r in results if r.get("status") == "success")
        failed = sum(1 for r in results if r.get("status") == "error")
        response_md = self._build_response_markdown(
            query, steps_for_log, results, standalone_script, succeeded, failed,
            html_report_path=html_report_path,
        )

        self._sessions[session_id] = {
            "query": query,
            "steps": steps_for_log,
            "results": results,
            "script": standalone_script,
        }
        final_url = ""
        if results:
            obs = results[-1].get("observation") or {}
            if isinstance(obs, dict):
                final_url = obs.get("url_after") or ""
        _emit("progress", {"stage": "post", "message": "Recording session memory for follow-up turns…"})
        session_memory.record(session_id, query, results, final_url=final_url)
        memory_preview = session_memory.format_for_planner(session_id, max_entries=2)
        if len(memory_preview) > 1200:
            memory_preview = memory_preview[:1200] + "…"

        return {
            "success": failed == 0,
            "response": response_md,
            "query": query,
            "thinking_steps": thinking,
            "timestamp": datetime.now().isoformat(),
            "steps_executed": results,
            "generated_script": standalone_script,
            "execution_log": execution_log,
            "html_report": html_report_path,
            "session_id": session_id,
            "session_history_preview": memory_preview or None,
        }

    # ── core pipeline ───────────────────────────────────────────────

    def _run(
        self,
        query: str,
        session_id: str,
        headless: bool,
        thinking: List[Dict[str, Any]],
        cdp_url: Optional[str] = None,
        persistent_profile_dir: Optional[str] = None,
        keep_browser_session: bool = False,
        enable_step_critic: bool = False,
        use_vision: bool = True,
        use_grounded_verifier: bool = True,
        stream_emit: BrowserSSEEmit = None,
    ) -> Dict[str, Any]:

        def _emit(ev: str, data: Dict[str, Any]) -> None:
            if stream_emit:
                try:
                    stream_emit(ev, data)
                except Exception:
                    logger.debug("stream_emit failed", exc_info=True)

        def _think(entry: Dict[str, Any]) -> None:
            thinking.append(entry)
            _emit("thinking", entry)

        # STEP 1 — Plan + validate (session memory gives multi-turn context)
        _think({"type": "planning", "content": "Breaking your request into browser steps…"})
        _emit("progress", {"stage": "plan", "message": "Loading session memory for multi-turn context…"})
        history_ctx = session_memory.format_for_planner(session_id, max_entries=3)
        _emit("progress", {"stage": "plan", "message": "Calling planner LLM to decompose your task into steps…"})
        _hb_stop, _hb_thr = _start_progress_pulse_thread(
            _emit,
            stage="plan",
            interval_sec=_LONG_WAIT_PROGRESS_SEC,
            message_prefix="Still waiting on planner LLM",
        )
        try:
            raw_steps = plan_roadmap(ai_service, query, session_history=history_ctx)
        finally:
            _hb_stop.set()
            _hb_thr.join(timeout=2.0)
        _emit("progress", {"stage": "plan", "message": "Planner returned — validating step schema…"})
        try:
            steps = validate_planner_steps(raw_steps)
        except ValueError as exc:
            return {
                "success": False,
                "response": f"**Invalid automation plan:** {exc}\n\nPlease simplify or rephrase your task.",
                "query": query,
                "thinking_steps": thinking,
                "timestamp": datetime.now().isoformat(),
                "session_id": session_id,
            }

        if not steps:
            return {
                "success": False,
                "response": "I could not break your request into actionable browser steps. Please rephrase with clearer instructions.",
                "query": query,
                "thinking_steps": thinking,
                "timestamp": datetime.now().isoformat(),
                "session_id": session_id,
            }

        _think({
            "type": "plan_ready",
            "content": f"Planned {len(steps)} steps:\n" + "\n".join(
                f"  {s.get('step_number', i+1)}. [{s.get('action')}] {s.get('description')}"
                for i, s in enumerate(steps)
            ),
        })

        # STEP 2 — Page from pool + DSL execution
        _think({
            "type": "execution",
            "content": "Acquiring browser (async Playwright) and running plan–act–observe loop…",
        })
        _emit("progress", {"stage": "browser", "message": f"Opening browser — {len(steps)} step(s) to run…"})

        async def _browser_workflow():
            stop_pulse = asyncio.Event()
            pulse_task = asyncio.create_task(
                _async_progress_pulse(
                    stop_pulse,
                    _emit,
                    stage="browser",
                    interval_sec=_BROWSER_PROGRESS_SEC,
                    message_prefix="Still running browser automation",
                )
            )
            try:
                page = await BrowserPool.async_acquire_page(
                    session_id,
                    headless=headless,
                    slow_mo=300,
                    cdp_url=cdp_url,
                    persistent_profile_dir=persistent_profile_dir,
                )
                ex = BrowserExecutor(
                    page,
                    use_step_critic=enable_step_critic,
                    use_vision=use_vision,
                    use_grounded_verifier=use_grounded_verifier,
                    on_sse=stream_emit,
                )
                try:
                    res = await ex.run_all_async(
                        ai_service, steps, original_query=query, max_replans=2,
                    )
                    return res, ex
                finally:
                    await BrowserPool.async_release_session(
                        session_id,
                        headless,
                        close_context=not keep_browser_session,
                        cdp_url=cdp_url,
                        persistent_profile_dir=persistent_profile_dir,
                    )
            finally:
                stop_pulse.set()
                pulse_task.cancel()
                try:
                    await pulse_task
                except asyncio.CancelledError:
                    pass

        try:
            results, executor = asyncio.run(_browser_workflow())
        except RuntimeError as exc:
            if "asyncio.run()" in str(exc) or "running event loop" in str(exc).lower():
                logger.warning("Falling back to sync browser pool: %s", exc)
                _hb_stop, _hb_thr = _start_progress_pulse_thread(
                    _emit,
                    stage="browser",
                    interval_sec=_BROWSER_PROGRESS_SEC,
                    message_prefix="Still running browser automation",
                )
                try:
                    page = BrowserPool.acquire_page(
                        session_id,
                        headless=headless,
                        slow_mo=300,
                        cdp_url=cdp_url,
                        persistent_profile_dir=persistent_profile_dir,
                    )
                    executor = BrowserExecutor(
                        page,
                        use_step_critic=enable_step_critic,
                        use_vision=use_vision,
                        use_grounded_verifier=use_grounded_verifier,
                        on_sse=stream_emit,
                    )
                    try:
                        results = executor.run_all(
                            ai_service, steps, original_query=query, max_replans=2,
                        )
                    finally:
                        BrowserPool.release_session(
                            session_id,
                            headless,
                            close_context=not keep_browser_session,
                            cdp_url=cdp_url,
                            persistent_profile_dir=persistent_profile_dir,
                        )
                finally:
                    _hb_stop.set()
                    _hb_thr.join(timeout=2.0)
            else:
                raise

        _emit("progress", {"stage": "post", "message": "Browser run finished — generating Playwright script export…"})
        # STEP 3 — Build standalone script
        standalone_script = executor.build_standalone_script(results, headless=headless)

        # STEP 4 — Build execution log
        execution_log = self._build_execution_log(query, steps, results)

        # Save log to file
        log_file = LOGS_DIR / f"run_{session_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        log_file.write_text(execution_log, encoding="utf-8")
        _think({"type": "logging", "content": f"Execution log saved to {log_file.name}"})

        # STEP 4b — Build HTML report with per-action screenshots
        _emit("progress", {"stage": "post", "message": "Building HTML report (screenshots embedded)…"})
        html_report_path = executor.build_html_report(query, results, session_id=session_id)
        _think({"type": "reporting", "content": f"HTML report saved to {Path(html_report_path).name}"})

        # STEP 5 — Build response
        succeeded = sum(1 for r in results if r.get("status") == "success")
        failed = sum(1 for r in results if r.get("status") == "error")

        response_md = self._build_response_markdown(
            query, steps, results, standalone_script, succeeded, failed,
            html_report_path=html_report_path,
        )

        # Store session + cross-turn memory (include extracted data)
        extracted_data = executor.data_store
        self._sessions[session_id] = {
            "query": query,
            "steps": steps,
            "results": results,
            "script": standalone_script,
            "extracted_data": extracted_data,
        }
        final_url = ""
        if results:
            obs = results[-1].get("observation") or {}
            if isinstance(obs, dict):
                final_url = obs.get("url_after") or ""
        _emit("progress", {"stage": "post", "message": "Recording session memory for follow-up turns…"})
        session_memory.record(session_id, query, results, final_url=final_url)
        memory_preview = session_memory.format_for_planner(session_id, max_entries=2)
        if len(memory_preview) > 1200:
            memory_preview = memory_preview[:1200] + "…"

        if extracted_data:
            _think({
                "type": "data_extraction",
                "content": f"Extracted {len(extracted_data)} variable(s): "
                + ", ".join(f"{k} ({len(v)} chars)" for k, v in extracted_data.items()),
            })

        return {
            "success": failed == 0,
            "response": response_md,
            "query": query,
            "thinking_steps": thinking,
            "timestamp": datetime.now().isoformat(),
            "steps_executed": results,
            "generated_script": standalone_script,
            "execution_log": execution_log,
            "html_report": html_report_path,
            "session_id": session_id,
            "session_history_preview": memory_preview or None,
            "extracted_data": {k: v[:500] for k, v in extracted_data.items()} if extracted_data else None,
        }

    # ── markdown response builder ───────────────────────────────────

    def _build_response_markdown(
        self,
        query: str,
        steps: List[Dict],
        results: List[Dict],
        script: str,
        succeeded: int,
        failed: int,
        html_report_path: str = "",
    ) -> str:
        parts: List[str] = []

        # Header
        parts.append("# Browser Automation Report\n")
        parts.append(f"**Task:** {query}\n")
        parts.append(f"**Result:** {succeeded}/{len(results)} steps succeeded")
        if failed:
            parts.append(f" ({failed} failed)")
        parts.append(f"  \n**Executed at:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        if html_report_path:
            report_name = Path(html_report_path).name
            parts.append(f"**Visual Report:** [Open HTML Report](file://{html_report_path}) (`{report_name}`)\n")

        # Step-by-step results
        parts.append("---\n## Execution Log\n")
        for r in results:
            status_icon = "\u2705" if r.get("status") == "success" else "\u274c"
            parts.append(
                f"### Step {r.get('step_number', '?')}: {r.get('description', '')}\n"
            )
            parts.append(f"- **Status:** {status_icon} {r.get('status', 'unknown')}\n")
            parts.append(f"- **Action:** `{r.get('action', '')}`\n")
            if r.get("error"):
                parts.append(f"- **Error:** `{r['error']}`\n")
            if r.get("condition_met") is not None:
                parts.append(f"- **Condition met:** {r['condition_met']}\n")
            if r.get("dsl_bundle"):
                parts.append(
                    "\n<details><summary>DSL bundle</summary>\n\n```json\n"
                    f"{json.dumps(r['dsl_bundle'], indent=2)[:12000]}\n```\n</details>\n"
                )
            parts.append("")

        # Generated script
        parts.append("---\n## Generated Playwright Script\n")
        parts.append(
            "You can save the script below and re-run it anytime with "
            "`python script.py`.\n"
        )
        parts.append(f"```python\n{script}\n```\n")

        return "\n".join(parts)

    # ── execution log builder ───────────────────────────────────────

    def _build_execution_log(
        self, query: str, steps: List[Dict], results: List[Dict]
    ) -> str:
        lines = [
            f"# Execution Log — {datetime.now().isoformat()}",
            f"**Query:** {query}",
            f"**Total steps:** {len(steps)}",
            "",
        ]
        for r in results:
            lines.append(f"## Step {r.get('step_number')}: {r.get('description')}")
            lines.append(f"- Action: {r.get('action')}")
            lines.append(f"- Status: {r.get('status')}")
            if r.get("started_at"):
                lines.append(f"- Started: {r['started_at']}")
            if r.get("finished_at"):
                lines.append(f"- Finished: {r['finished_at']}")
            if r.get("error"):
                lines.append(f"- Error: {r['error']}")
            if r.get("screenshot"):
                lines.append(f"- Screenshot: {r['screenshot']}")
            if r.get("dsl_bundle"):
                lines.append(f"\n```json\n{json.dumps(r['dsl_bundle'], indent=2)}\n```\n")
            lines.append("")
        return "\n".join(lines)

    # ── welcome message ─────────────────────────────────────────────

    def _welcome(self) -> Dict[str, Any]:
        return {
            "success": True,
            "response": (
                "# Browser Automation Agent\n\n"
                "I can automate browser tasks from natural language.\n\n"
                "**How to use:** Describe what you want to do in a browser, for example:\n\n"
                '> *"Go to amazon.in, search for iPhone 17, if available add to cart, '
                'then search for a mattress under ₹10,000, add to cart"*\n\n'
                "I will:\n"
                "1. Plan validated browser steps\n"
                "2. Use a **shared browser pool** (visible Chrome unless headless)\n"
                "3. Run **safe JSON actions** (no arbitrary code) with screenshots\n"
                "4. **Remember logins by default** — cookies are saved in a folder on this computer (`remember_logins`; optional `persistent_profile_dir`). Sign in once in the browser window; later tasks reuse that session without Chrome flags\n"
                "5. **Keep this chat’s tab open** across messages (`keep_browser_session`, on by default) for smoother follow-ups\n"
                "6. **Advanced — reuse desktop Chrome:** `cdp_endpoint` or env **`PLAYWRIGHT_CDP_URL`** (e.g. `http://127.0.0.1:9222` with `--remote-debugging-port=9222`)\n"
                "7. **Vision enabled by default** — viewport screenshots per DSL step (disable with `use_vision: false` if your API doesn’t support images)\n"
                "8. Export a Playwright script derived from the DSL\n\n"
                "**Limitations:** Sites may show **CAPTCHA** or block automation. "
                "Saved profile + same chat session covers most “stay logged in” needs without CDP. "
                "Amazon’s UI and anti-bot rules can still prevent adds to cart.\n\n"
                "**Paste your task below to get started!**"
            ),
            "query": "",
            "thinking_steps": [],
            "timestamp": datetime.now().isoformat(),
            "session_id": None,
        }


browser_agent = BrowserAgent()
