"""Repository analysis using Claude Code CLI.

The CLI gets Read + Bash access to the cloned repo so it can explore
the codebase, read files, run `find`/`grep`, and produce analysis.
"""

from typing import Dict, Any
from ..claude_service import run_claude_cli, ANALYZE_SYSTEM_PROMPT


async def analyze_repository(
    repo_path: str,
    repo_name: str,
    query: str,
    cli_session_id: str = None,
) -> Dict[str, Any]:
    """Analyze a cloned repository using Claude Code CLI."""

    prompt = (
        f"Analyze the repository '{repo_name}' and answer the following:\n\n"
        f"{query}\n\n"
        f"Use the Read tool to examine source files. "
        f"Provide a thorough analysis."
    )

    result = await run_claude_cli(
        prompt=prompt,
        cwd=repo_path,
        system_prompt=ANALYZE_SYSTEM_PROMPT,
        allowed_tools="Read",
        max_budget_usd=1.0,
        session_id=cli_session_id,
    )

    return {
        "success": result["success"],
        "response": result["result"],
        "cost": result.get("cost", 0),
        "cli_session_id": result.get("session_id"),
    }
