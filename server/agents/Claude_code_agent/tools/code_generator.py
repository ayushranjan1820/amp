"""Standalone code generation using Claude Code CLI."""

import os
import re
import tempfile
from typing import Dict, Any, List
from ..claude_service import run_claude_cli, GENERATE_SYSTEM_PROMPT


async def generate_code(query: str, working_dir: str = None) -> Dict[str, Any]:
    """Generate standalone code files using Claude Code CLI.

    The CLI runs in a temp directory and creates files directly using its
    Write tool. We collect what was created and return it.
    """
    output_dir = working_dir or tempfile.mkdtemp(prefix="claude_gen_")
    os.makedirs(output_dir, exist_ok=True)

    prompt = (
        f"{query}\n\n"
        f"Write the complete code files to the current directory. "
        f"Use the Write tool to create each file."
    )

    result = await run_claude_cli(
        prompt=prompt,
        cwd=output_dir,
        system_prompt=GENERATE_SYSTEM_PROMPT,
        allowed_tools="Read Write",
        max_budget_usd=1.0,
    )

    generated_files = _discover_created_files(output_dir)

    response = result["result"]
    if generated_files:
        file_list = "\n".join(f"  - `{f}`" for f in generated_files)
        response += f"\n\n**Generated files:**\n{file_list}"

    return {
        "success": result["success"],
        "response": response,
        "generated_files": generated_files,
        "output_dir": output_dir,
        "cost": result.get("cost", 0),
    }


def _discover_created_files(directory: str) -> List[str]:
    """Walk the output directory and find all created files."""
    files = []
    skip = {'.git', '__pycache__', 'node_modules', '.claude'}
    for root, dirs, filenames in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in filenames:
            rel = os.path.relpath(os.path.join(root, f), directory)
            if not rel.startswith('.'):
                files.append(rel)
    return files
