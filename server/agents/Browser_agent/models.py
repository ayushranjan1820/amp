from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ThinkingStep(BaseModel):
    type: str
    content: str
    tool_name: Optional[str] = None


class BrowserStep(BaseModel):
    step_number: int
    action: str
    description: str
    status: str = "pending"
    screenshot_path: Optional[str] = None
    error: Optional[str] = None
    code_executed: Optional[str] = None


class BrowserChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    clear_history: bool = False
    user_config: Optional[Dict[str, str]] = None
    headless: bool = True
    keep_browser_session: bool = Field(
        default=True,
        description="Reuse the same browser tab/context for this chat session across messages (smoother follow-ups).",
    )
    remember_logins: bool = Field(
        default=True,
        description=(
            "When true (and CDP is not used), store cookies and site logins in a folder on this computer "
            "so you stay signed in across runs. No Chrome flags required."
        ),
    )
    persistent_profile_dir: Optional[str] = Field(
        default=None,
        description="Optional absolute path for the saved browser profile; default is a standard app folder per OS.",
    )
    cdp_endpoint: Optional[str] = Field(
        default=None,
        description=(
            "Attach Playwright to an existing Chrome/Edge via CDP, e.g. http://127.0.0.1:9222 "
            "(start browser with --remote-debugging-port=9222). Uses your real profile cookies. "
            "Overrides headless to false. Env fallback: PLAYWRIGHT_CDP_URL."
        ),
    )
    enable_step_critic: bool = Field(
        default=False,
        description="Run an extra LLM validation after each successful step (higher cost).",
    )
    use_vision: bool = Field(
        default=True,
        description="Send a viewport screenshot with each DSL step so the model can see the UI (requires multimodal API support; falls back to text-only if rejected).",
    )
    use_grounded_verifier: bool = Field(
        default=True,
        description="After each step, check expected_outcome against page text (no extra LLM). Disable if too strict for your site.",
    )
    rerun_standalone_script: Optional[str] = Field(
        default=None,
        description="When set, skip planning and run this exported Playwright Python in a subprocess (stdout/stderr in reply).",
    )
    replay_steps_executed: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="When re-running from the UI, pass prior steps_executed (with dsl_bundle) to replay in-browser with screenshots + HTML report.",
    )


class BrowserChatResponse(BaseModel):
    success: bool
    response: str
    query: str = ""
    thinking_steps: List[ThinkingStep] = []
    timestamp: str = ""
    steps_executed: List[Dict[str, Any]] = []
    generated_script: Optional[str] = None
    execution_log: Optional[str] = None
    html_report: Optional[str] = Field(
        None,
        description="Server path to the HTML report; UI should use html_report_file + download API.",
    )
    html_report_file: Optional[str] = Field(
        None,
        description="Report basename only; GET /api/browser-agent/html-report?file=…",
    )
    session_id: Optional[str] = None
    session_history_preview: Optional[str] = Field(
        None,
        description="Text of recent turns stored for the next planner (multi-turn browser tasks).",
    )
