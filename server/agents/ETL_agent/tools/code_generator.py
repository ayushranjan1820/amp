"""Layer 4 — Code Generation Agent: Generate safe, optimized Pandas code.

Constraints enforced:
- Only standard Python + Pandas imports allowed
- No external imports (no subprocess, os, sys, shutil, etc.)
- No loops unless strictly necessary
- Output must be stored in `result` variable
- Code must be minimal and deterministic
"""

from __future__ import annotations

import re
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Blocklisted imports — these indicate unsafe or unnecessary code
_BLOCKED_IMPORTS = {
    "os", "sys", "subprocess", "shutil", "pathlib", "glob", "socket",
    "http", "urllib", "requests", "pickle", "shelve", "ctypes",
    "importlib", "exec", "eval", "compile", "__import__",
    "multiprocessing", "threading", "signal", "atexit",
}

# Only these imports are allowed in generated code
_ALLOWED_IMPORTS = {"pandas", "numpy", "math", "datetime", "re", "json", "collections"}


def validate_generated_code(code: str) -> List[str]:
    """Static analysis: check generated code for safety violations.

    Returns a list of error messages. Empty list = code is safe.
    """
    errors: List[str] = []

    # Check for blocked imports
    import_pattern = re.compile(
        r"(?:^|\n)\s*(?:import|from)\s+([\w.]+)", re.MULTILINE
    )
    for match in import_pattern.finditer(code):
        module = match.group(1).split(".")[0]
        if module in _BLOCKED_IMPORTS:
            errors.append(f"Blocked import: '{module}' is not allowed in ETL code.")
        elif module not in _ALLOWED_IMPORTS and module != "pd":
            errors.append(
                f"Unapproved import: '{module}'. Allowed: {sorted(_ALLOWED_IMPORTS)}."
            )

    # Check for dangerous builtins
    dangerous_calls = re.compile(
        r"\b(exec|eval|compile|__import__|open|globals|locals|getattr|setattr|delattr)\s*\("
    )
    for match in dangerous_calls.finditer(code):
        errors.append(f"Blocked call: '{match.group(1)}()' is not allowed.")

    # Check that result variable is assigned
    if not re.search(r"\bresult\s*=", code):
        errors.append("Code must assign output to a variable named 'result'.")

    # Check for infinite loop patterns
    while_pattern = re.compile(r"\bwhile\s+True\b")
    if while_pattern.search(code):
        errors.append("Infinite loops (while True) are not allowed.")

    return errors


def build_code_generation_prompt(
    user_query: str,
    schema_text: str,
    plan: Dict[str, Any],
    tool_decision: str,
) -> str:
    """Build prompt for the Code Generation LLM to produce safe Pandas code."""
    steps_text = ""
    for i, step in enumerate(plan.get("steps", []), 1):
        steps_text += f"  {i}. {step.get('operation', 'unknown')}: {step.get('description', '')}\n"

    return f"""You are a code generation agent for a secure ETL pipeline.
Generate Python + Pandas code that transforms a DataFrame according to the user's request.

STRICT RULES — violating any rule causes rejection:
1. Only use: pandas (as pd), numpy (as np), math, datetime, re, json, collections
2. NO: os, sys, subprocess, open(), exec(), eval(), file I/O, network calls
3. NO infinite loops. Prefer vectorized Pandas operations over loops.
4. The input DataFrame is available as `df` (already loaded from extract or pasted data; do NOT read files or connect to databases). Do NOT treat `df` as catalog metadata to filter — if the user asked for table rows, `result` must preserve those row columns (e.g. pass through or transform `df`); never replace with information_schema-style outputs.
5. Store the final transformed result in a variable named `result`.
6. `result` must be a pandas DataFrame.
7. Keep code minimal — no comments, no print statements, no logging.
8. Handle NaN/None gracefully using Pandas methods (fillna, dropna, etc.).

USER REQUEST:
{user_query}

DATASET SCHEMA:
{schema_text}

TRANSFORMATION PLAN:
{steps_text}

TOOL DECISION: {tool_decision}

Generate ONLY the Python code block. No markdown fences, no explanation.
"""


def extract_code_block(raw_llm_output: str) -> str:
    """Extract clean Python code from LLM output, stripping markdown fences."""
    text = raw_llm_output.strip()

    # Remove markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```python or ```)
        lines = lines[1:]
        # Remove trailing ```
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)

    return text.strip()
