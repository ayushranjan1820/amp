from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Dict


def run_coverage(workspace_root: str) -> Dict[str, Any]:
    root = Path(workspace_root)
    if not ((root / "pyproject.toml").exists() or (root / "requirements.txt").exists() or (root / "pytest.ini").exists()):
        return {"status": "skipped", "details": "Coverage runner only auto-detected for Python repos in this scaffold."}

    cmd = ["python", "-m", "pytest", "--cov=.", "--cov-report=term"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=workspace_root,
            capture_output=True,
            text=True,
            timeout=240,
        )
    except FileNotFoundError:
        return {"status": "skipped", "details": "pytest/pytest-cov not installed."}
    except subprocess.TimeoutExpired:
        return {"status": "failed", "details": "Coverage command timed out."}

    output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    match = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+)%", output)
    pct = int(match.group(1)) if match else None
    return {
        "status": "passed" if proc.returncode == 0 else "failed",
        "details": output[:4000],
        "coverage_pct": pct,
        "command": cmd,
    }

