"""Execute a Web Test Agent Playwright TypeScript spec on the server.

Runs ``npm install`` in a temp folder so ``import from '@playwright/test'`` resolves, then
``node_modules/.bin/playwright test``. Requires Node.js (npm) and network for the install.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

_MAX_SPEC_BYTES = 500_000
_PW_PKG = os.getenv("WEB_TEST_PLAYWRIGHT_VERSION", "1.49.1")
_NPM_INSTALL_TIMEOUT = int(os.getenv("WEB_TEST_NPM_INSTALL_TIMEOUT_SEC", "480"))

# Plain CommonJS config — must NOT import '@playwright/test' here: the temp dir has no
# node_modules; resolution runs from this file and would fail (MODULE_NOT_FOUND).
_PLAYWRIGHT_CONFIG_CJS = """module.exports = {
  testDir: '.',
  timeout: 120000,
  retries: 0,
  workers: 1,
  reporter: [['line']],
  use: {
    trace: 'off',
    viewport: { width: 1280, height: 720 },
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
};
"""


def _npm_executable() -> Optional[str]:
    if sys.platform == "win32":
        return shutil.which("npm.cmd") or shutil.which("npm")
    return shutil.which("npm")


def _playwright_cli_bin(root: Path) -> Optional[Path]:
    """Local CLI after ``npm install`` (resolves ``import '@playwright/test'`` from *root*)."""
    if sys.platform == "win32":
        p = root / "node_modules" / ".bin" / "playwright.cmd"
    else:
        p = root / "node_modules" / ".bin" / "playwright"
    return p if p.is_file() else None


def _validate_spec(source: str) -> Optional[str]:
    raw = (source or "").strip()
    if not raw:
        return "Spec is empty."
    if len(raw.encode("utf-8")) > _MAX_SPEC_BYTES:
        return f"Spec exceeds maximum size ({_MAX_SPEC_BYTES // 1000}KB)."
    if "@playwright/test" not in raw:
        return "Spec must import from '@playwright/test' (Web Test Agent Playwright output)."
    if "test(" not in raw and "test.describe" not in raw:
        return "Spec must contain Playwright tests (e.g. test(...) or test.describe(...))."
    return None


def run_playwright_typescript_spec(
    spec_source: str,
    *,
    headed: bool = True,
    timeout_sec: int = 600,
) -> Dict[str, Any]:
    """Write spec + minimal Playwright project to a temp dir and run ``playwright test``.

    Returns a dict with keys: success, exit_code, stdout, stderr, message (optional).
    """
    err = _validate_spec(spec_source)
    if err:
        return {"success": False, "exit_code": None, "stdout": "", "stderr": "", "message": err}

    npm = _npm_executable()
    if not npm:
        return {
            "success": False,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "message": "``npm`` was not found on PATH. Install Node.js LTS (includes npm), then retry.",
        }

    tmp: Optional[str] = None
    try:
        tmp = tempfile.mkdtemp(prefix="webtest_pw_")
        root = Path(tmp)
        (root / "playwright.config.cjs").write_text(_PLAYWRIGHT_CONFIG_CJS, encoding="utf-8")
        pkg = {
            "name": "web-test-run",
            "private": True,
            "version": "0.0.0",
            "devDependencies": {"@playwright/test": _PW_PKG},
        }
        (root / "package.json").write_text(json.dumps(pkg, indent=2) + "\n", encoding="utf-8")
        (root / "test.spec.ts").write_text(spec_source.strip() + "\n", encoding="utf-8")

        env = os.environ.copy()
        env.setdefault("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", "0")

        install_to = max(120, min(_NPM_INSTALL_TIMEOUT, 3600))
        inst = subprocess.run(
            [npm, "install", "--no-fund", "--no-audit"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=install_to,
            env=env,
            shell=False,
        )
        if inst.returncode != 0:
            out_i = (inst.stdout or "").strip()
            err_i = (inst.stderr or "").strip()
            return {
                "success": False,
                "exit_code": inst.returncode,
                "stdout": out_i or "(no stdout)",
                "stderr": err_i or "(no stderr)",
                "message": "npm install failed in the temp project (see stderr). Check network and npm registry access.",
            }

        pw_bin = _playwright_cli_bin(root)
        if not pw_bin:
            return {
                "success": False,
                "exit_code": None,
                "stdout": "",
                "stderr": "",
                "message": "After npm install, playwright CLI was not found under node_modules/.bin.",
            }

        cmd = [str(pw_bin), "test", "test.spec.ts", "--reporter=line"]
        if headed:
            cmd.append("--headed")

        run_timeout = max(60, int(timeout_sec))
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=run_timeout,
            env=env,
            shell=False,
        )
        out = (proc.stdout or "").strip()
        err_txt = (proc.stderr or "").strip()
        ok = proc.returncode == 0
        combined = f"{out}\n{err_txt}"
        hints: list[str] = []
        if not ok and ("Executable doesn't exist" in combined or "browserType.launch" in combined):
            hints.append("Tip: install browsers once: `npx playwright install chromium`")
        if not ok and "Cannot find module '@playwright/test'" in combined:
            hints.append(
                "If @playwright/test still fails after npm install, try `npm cache verify` or "
                "`npm cache clean --force`, then retry."
            )
        hint = "\n".join(hints) if hints else None
        return {
            "success": ok,
            "exit_code": proc.returncode,
            "stdout": out or "(no stdout)",
            "stderr": err_txt or "(no stderr)",
            "message": None if ok else hint,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "message": f"Timed out after {max(60, int(timeout_sec))}s. Try a shorter spec or increase timeout.",
        }
    except OSError as exc:
        return {
            "success": False,
            "exit_code": None,
            "stdout": "",
            "stderr": str(exc),
            "message": "Failed to start Playwright subprocess.",
        }
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
