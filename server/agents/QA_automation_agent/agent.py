"""QA Automation Agent — Claude Code CLI driven.

Workflow on every prompt:

1. Use the LLM to extract a GitHub Pull Request URL from the user's message
   (regex fast-path first).
2. Call the GitHub REST API for PR metadata: head repo / branch / changed
   files / title / body.
3. Clone (or refresh) the PR head repo at the head branch into the agent's
   workspace.
4. Run the Claude Code CLI inside the cloned repo with a prompt that:
     * describes the PR (title + body + summarised diff),
     * tells Claude to discover the existing automation-test folder
       (`automation_tests/`, `tests/`, `e2e/`, `cypress/`, `playwright/`,
       etc.) and learn the project's test framework + conventions,
     * generates working automation scripts for the PR's new feature,
       extending existing files where natural and creating new ones where
       not.
5. Commit Claude Code's edits and push them onto the PR head branch (so they
   appear as additional commits on the open PR).

Required configuration (UI ``user_config`` or env):
* ``ANTHROPIC_API_KEY`` — to drive the Claude Code CLI.
* ``GITHUB_TOKEN`` (or ``GITHUB_PAT``) — to clone, push, and read PR
  metadata. Needs ``repo`` scope and write access to the PR head repo.
"""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from . import git_service
from .ai_service import ai_service

# Reuse the Claude Code CLI runner from the Claude Code Agent so we don't
# duplicate the streaming / kill-tree / change-detection plumbing.
from agents.Claude_code_agent.claude_service import run_claude_code


GITHUB_API = "https://api.github.com"
MAX_FILE_BYTES = 60_000
MAX_CHANGED_FILES = 30

REPOS_DIR = Path(__file__).parent.parent.parent.parent / "repos" / "qa_automation_agent"
REPOS_DIR.mkdir(parents=True, exist_ok=True)

PR_URL_RE = re.compile(
    r"https?://github\.com/([\w.\-]+)/([\w.\-]+)/pull/(\d+)",
    re.IGNORECASE,
)


# ── helpers ─────────────────────────────────────────────────────────────────

def _resolve(name: str, explicit: Optional[str], user_config: Optional[Dict[str, str]]) -> str:
    if explicit:
        return explicit.strip()
    if user_config and user_config.get(name):
        return str(user_config[name]).strip()
    val = os.environ.get(name) or ""
    return val.strip()


def _gh_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _gh_get(url: str, token: str, params: Optional[Dict[str, Any]] = None) -> Any:
    r = requests.get(url, headers=_gh_headers(token), params=params, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"GitHub API {r.status_code} on GET {url}: {r.text[:300]}")
    return r.json()


def _push_step(
    steps: List[Dict[str, Any]],
    step: Dict[str, Any],
    on_thinking_step: Optional[Callable[[Dict[str, Any]], None]],
) -> None:
    steps.append(step)
    if on_thinking_step:
        try:
            on_thinking_step(step)
        except Exception:
            pass


# ── agent ───────────────────────────────────────────────────────────────────

class QAAutomationAgent:
    def __init__(self) -> None:
        self.sessions: Dict[str, Dict[str, Any]] = {}
        print("QA Automation Agent initialized (Claude Code CLI mode)")

    # ── PR URL extraction ──────────────────────────────────────────────

    def _extract_pr_url_with_llm(self, query: str) -> Optional[str]:
        regex_hit = PR_URL_RE.search(query or "")
        if regex_hit:
            return regex_hit.group(0)

        prompt = (
            "Extract the GitHub Pull Request URL from the user's message. "
            "Return ONLY a JSON object: {\"pr_url\": \"<url or empty string>\"}. "
            "A valid PR URL looks like https://github.com/<owner>/<repo>/pull/<number>.\n\n"
            f"Message:\n{query}"
        )
        try:
            raw = ai_service.call_genai(prompt, temperature=0.0, max_tokens=200) or ""
            m = PR_URL_RE.search(raw)
            if m:
                return m.group(0)
        except Exception as exc:
            print(f"⚠️ PR URL LLM extraction failed: {exc}")
        return None

    @staticmethod
    def _parse_pr_url(pr_url: str) -> Optional[Tuple[str, str, int]]:
        m = PR_URL_RE.search(pr_url)
        if not m:
            return None
        return m.group(1), m.group(2), int(m.group(3))

    # ── PR metadata + diff ─────────────────────────────────────────────

    def _fetch_pr(self, owner: str, repo: str, number: int, token: str) -> Dict[str, Any]:
        return _gh_get(f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{number}", token)

    def _fetch_pr_files(
        self, owner: str, repo: str, number: int, token: str
    ) -> List[Dict[str, Any]]:
        files: List[Dict[str, Any]] = []
        page = 1
        while True:
            chunk = _gh_get(
                f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{number}/files",
                token,
                params={"per_page": 100, "page": page},
            )
            if not chunk:
                break
            files.extend(chunk)
            if len(chunk) < 100:
                break
            page += 1
            if page > 10:
                break
        return files

    # ── prompt construction ────────────────────────────────────────────

    def _build_diff_summary(self, files: List[Dict[str, Any]]) -> str:
        parts: List[str] = []
        for f in files[:MAX_CHANGED_FILES]:
            path = f.get("filename", "")
            status = f.get("status", "modified")
            patch = (f.get("patch") or "")[:4000]
            parts.append(f"### {path} ({status})\n```diff\n{patch}\n```")
        if len(files) > MAX_CHANGED_FILES:
            parts.append(f"_…and {len(files) - MAX_CHANGED_FILES} more changed files (omitted)._")
        return "\n\n".join(parts) or "(no diff)"

    def _build_claude_prompt(
        self,
        pr_meta: Dict[str, Any],
        pr_url: str,
        files: List[Dict[str, Any]],
    ) -> str:
        title = (pr_meta.get("title") or "").strip()
        body = (pr_meta.get("body") or "").strip()[:2000]
        diff_summary = self._build_diff_summary(files)
        changed_paths = "\n".join(
            f"- `{f.get('filename','')}` ({f.get('status','modified')})"
            for f in files[:MAX_CHANGED_FILES]
        ) or "_(no files)_"

        return f"""You are a senior QA automation engineer. You are working **inside** an
already-cloned repository checked out at the head branch of an open Pull
Request. Your job is to add or extend automation tests so they cover the
new behaviour introduced by this PR — and ONLY that.

You DO NOT have a Bash tool. You will NOT run the tests. The bar for
"done" is therefore: every test you write must be obviously correct on
careful static reading — its imports resolve, every helper/fixture it
calls actually exists in this repo, every selector it uses matches the
existing tests, and the framework APIs are used correctly.

## Pull Request
- URL: {pr_url}
- Title: {title or '(no title)'}
- Description:
{body or '(no description)'}

## Changed files
{changed_paths}

## Diff snippets
{diff_summary}

## What to do (in order)

### Phase 1 — Learn the suite (DO NOT skip; DO NOT skim)
1. Use Glob/Grep/Read to find the automation folder. Priority:
   `automation_tests/`, `tests/automation/`, `e2e/`, `cypress/`,
   `playwright/`, `tests/`, `__tests__/`, `spec/`, `test/`. Inspect the
   matching config — `playwright.config.*`, `cypress.config.*`,
   `jest.config.*`, `pytest.ini`, `pyproject.toml`, `package.json` —
   to identify the framework, runner, base URL, projects, and any
   `globalSetup` / `setup` / fixtures.
2. **Read EVERY shared/test-utility module end-to-end** — anything under
   names like `fixtures/`, `helpers/`, `utils/`, `support/`, `pages/`,
   `pageObjects/`, `factories/`, `apiClient*`, `auth*`, `seed*`,
   `testData*`, plus the project's `*.config.*` for the test runner.
   These tell you HOW the suite logs in, seeds data, builds API
   payloads, and selects elements.
3. **Read 2–4 existing test files** end-to-end. Match the patterns you
   see exactly: imports, fixture usage, login/seed flow, naming,
   file layout, assertion style, selector strategy, setup/teardown.

### Phase 2 — Reuse, never reinvent
- If the suite already has a helper for what you need (login, create
  user, create bid, seed assignment, mock API, log in as role X) —
  USE IT. Do **not** write your own `apiContext.post(...)` /
  `createBid` / `loginAsOwner` /etc. on top.
- If you genuinely cannot find a helper for something you need, prefer
  using the UI through the same selectors the existing tests use, or
  copy the pattern from the closest existing test verbatim.
- Never invent endpoint paths, request payloads, or auth headers from
  the diff. If the existing suite hits the API a certain way, do the
  same; if it doesn't hit the API at all, drive your tests through the
  UI like the rest of the suite.

### Phase 3 — Pick what to cover
- Identify the *user-visible* behaviour change in this PR. Pick a
  small focused set of tests: happy path, 1–2 important edge cases,
  1 negative path. Quality > quantity. **Three solid passing tests
  are infinitely better than fifty failing ones.**

### Phase 4 — Write the tests
- Prefer EXTENDING the most appropriate existing test file when the
  new cases belong with sibling tests.
- Otherwise CREATE a new test file in the SAME folder, named like
  the siblings.
- Use the same imports, fixtures, selectors, and assertions as the
  rest of the suite.
- Real assertions only — no `expect(true).toBe(true)`, no TODO
  placeholders, no `.skip` / `.only`, no commented-out steps.
- Pay attention to API surface details. For Playwright in particular:
  `response.status()` is a **method**, not a property. So
  `${{response.status()}}` (call it) — never `${{response.status}}`.
  `response.ok()` is also a method. Always check the imports of an
  existing test before writing yours.

### Phase 5 — Static code-check (NO test execution)
Do NOT run the tests. Instead, do a careful static review of every
file you wrote/edited and fix issues yourself before finishing:
- Re-Read each file you touched end-to-end.
- Confirm imports actually exist in the project (Grep for the symbol
  in `node_modules`/source if unsure) and resolve correctly.
- Confirm every helper / fixture / page-object you reference exists
  with the exact name and signature you used (Grep to verify).
- Confirm every selector you used matches a real one in the existing
  tests or app source.
- Confirm framework API correctness — e.g. for Playwright,
  `response.status()` and `response.ok()` are **methods**, not
  properties; `page.locator(...)` returns a Locator (not a
  Promise); `expect(...).toBeVisible()` is async (`await`).
- Remove any `.only` / `.skip`, dead code, `console.log`, TODO,
  filler assertions like `expect(true).toBe(true)`.
- If any issue you spot can't be fixed without running things or
  changing production code, DELETE that specific test rather than
  leave a broken one behind.

### Constraints
- Only edit/create files inside the automation-test folder you
  identified. Do NOT modify production source, CI config, lockfiles,
  or `package.json`.
- You only have Read / Glob / Grep / Edit / Write. No Bash, no
  shell commands, no test execution.

## Final summary (at the end)
List:
- Automation folder + framework/language detected.
- Each test file you created or extended, plus which behaviour each
  new test covers.
- Static review: any issues you found and fixed during Phase 5.
"""

    # ── public entry ───────────────────────────────────────────────────

    async def process_query(
        self,
        query: str,
        session_id: str = "default",
        github_token: Optional[str] = None,
        anthropic_api_key: Optional[str] = None,
        user_config: Optional[Dict[str, str]] = None,
        on_thinking_step: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        thinking_steps: List[Dict[str, Any]] = []
        cfg = user_config or {}

        token = (
            _resolve("GITHUB_TOKEN", github_token, cfg)
            or _resolve("GITHUB_PAT", None, cfg)
            or _resolve("GITHUB_PERSONAL_ACCESS_TOKEN", None, cfg)
        )
        api_key = _resolve("ANTHROPIC_API_KEY", anthropic_api_key, cfg)

        missing: List[str] = []
        if not token:
            missing.append("GITHUB_TOKEN")
        if not api_key:
            missing.append("ANTHROPIC_API_KEY")
        if missing:
            return {
                "success": False,
                "response": (
                    "Missing required configuration: "
                    + ", ".join(missing)
                    + ". Add them to the QA Automation Agent configuration "
                    "(UI) or the server environment."
                ),
                "thinking_steps": thinking_steps,
                "requires_token": "GITHUB_TOKEN" in missing,
            }

        _push_step(thinking_steps, {
            "type": "thinking",
            "content": "Extracting GitHub PR URL from the prompt.",
        }, on_thinking_step)
        pr_url = self._extract_pr_url_with_llm(query)
        if not pr_url:
            return {
                "success": False,
                "response": (
                    "I couldn't find a GitHub Pull Request URL in your message. "
                    "Please include a link like "
                    "`https://github.com/<owner>/<repo>/pull/<number>`."
                ),
                "thinking_steps": thinking_steps,
            }
        parsed = self._parse_pr_url(pr_url)
        if not parsed:
            return {
                "success": False,
                "response": f"Couldn't parse `{pr_url}` as a GitHub PR URL.",
                "thinking_steps": thinking_steps,
            }
        owner, repo, pr_number = parsed
        _push_step(thinking_steps, {
            "type": "tool_result",
            "tool_name": "extract_pr_url",
            "content": f"PR identified: {owner}/{repo}#{pr_number}",
        }, on_thinking_step)

        try:
            # ── 1. PR metadata + diff
            _push_step(thinking_steps, {
                "type": "tool_call",
                "tool_name": "github_pr_fetch",
                "content": f"Fetching PR metadata: {owner}/{repo}#{pr_number}",
            }, on_thinking_step)
            pr = self._fetch_pr(owner, repo, pr_number, token)
            head = pr.get("head", {}) or {}
            head_branch = head.get("ref")
            head_repo = head.get("repo", {}) or {}
            target_owner = ((head_repo.get("owner") or {}).get("login") or owner)
            target_repo = (head_repo.get("name") or repo)
            if not head_branch:
                return {
                    "success": False,
                    "response": (
                        "PR head branch not found. Is the PR closed, or is "
                        "the head from a fork without access?"
                    ),
                    "thinking_steps": thinking_steps,
                }
            _push_step(thinking_steps, {
                "type": "tool_result",
                "tool_name": "github_pr_fetch",
                "content": f"PR head: {target_owner}/{target_repo}@{head_branch}",
            }, on_thinking_step)

            files = self._fetch_pr_files(owner, repo, pr_number, token)
            changed_paths = [f.get("filename", "") for f in files]
            _push_step(thinking_steps, {
                "type": "tool_result",
                "tool_name": "github_pr_files",
                "content": f"Detected {len(files)} changed file(s) in PR.",
            }, on_thinking_step)

            # ── 2. Clone / refresh + checkout PR branch
            _push_step(thinking_steps, {
                "type": "tool_call",
                "tool_name": "git_clone_pr",
                "content": (
                    f"Cloning {target_owner}/{target_repo} and checking out "
                    f"`{head_branch}`."
                ),
            }, on_thinking_step)
            clone = await git_service.clone_pr_branch(
                owner=target_owner,
                repo=target_repo,
                branch=head_branch,
                dest_dir=REPOS_DIR,
                token=token,
                anthropic_api_key=api_key,
                emit=on_thinking_step,
            )
            if not clone.get("success"):
                return {
                    "success": False,
                    "response": f"Clone/checkout failed: {clone.get('error')}",
                    "thinking_steps": thinking_steps,
                    "pr_url": pr_url,
                    "branch": head_branch,
                }
            repo_path = clone["path"]
            recovered = clone.get("recovered_via")
            _push_step(thinking_steps, {
                "type": "tool_result",
                "tool_name": "git_clone_pr",
                "content": (
                    f"{'Refreshed' if clone.get('reused') else 'Cloned'} into "
                    f"`{repo_path}` at `{head_branch}`"
                    + (f" (recovered via {recovered})" if recovered else "")
                    + "."
                ),
            }, on_thinking_step)

            # ── 3. Run Claude Code CLI on the PR branch
            prompt = self._build_claude_prompt(pr, pr_url, files)
            _push_step(thinking_steps, {
                "type": "tool_call",
                "tool_name": "claude_code_cli",
                "content": (
                    "Running Claude Code CLI to discover the automation suite "
                    "and generate test scripts for this PR."
                ),
            }, on_thinking_step)
            cli = await run_claude_code(
                prompt=prompt,
                repo_path=repo_path,
                anthropic_api_key=api_key,
                emit=on_thinking_step,
                # Static-only: no Bash. Claude reads existing tests/helpers,
                # writes the new tests, and self-reviews — but never runs
                # them. Test execution is left for CI / the developer.
                allowed_tools="Read,Write,Edit,Glob,Grep",
            )
            thinking_steps.extend(cli.get("thinking_steps", []))

            if not cli.get("success"):
                return {
                    "success": False,
                    "response": (
                        f"Claude Code run failed: {cli.get('error')}\n\n"
                        f"Summary so far:\n{cli.get('summary','')[:1000]}"
                    ),
                    "thinking_steps": thinking_steps,
                    "pr_url": pr_url,
                    "branch": head_branch,
                    "files_changed": changed_paths,
                }

            changed = cli.get("changed_files", []) or []
            summary = (cli.get("summary") or "").strip()
            cost_usd = float(cli.get("cost_usd", 0.0) or 0.0)
            duration_s = float(cli.get("duration_seconds", 0.0) or 0.0)
            _push_step(thinking_steps, {
                "type": "tool_result",
                "tool_name": "claude_code_cli",
                "content": (
                    f"Claude Code finished — {len(changed)} file(s) changed, "
                    f"cost ${cost_usd:.4f}, {duration_s:.1f}s."
                ),
            }, on_thinking_step)

            if not changed:
                msg = (
                    "Claude Code did not produce any test-script changes. "
                    "This usually means it could not confidently identify the "
                    "automation suite (none of the standard folders / config "
                    "files were present), or it judged the PR diff to be "
                    "non-test-relevant.\n\n"
                    f"**Claude Code summary:**\n{summary or '(no summary)'}"
                )
                return {
                    "success": False,
                    "response": msg,
                    "thinking_steps": thinking_steps,
                    "pr_url": pr_url,
                    "branch": head_branch,
                    "files_changed": changed_paths,
                }

            # ── 4. Push to the PR head branch
            commit_message = (
                f"qa-automation: add tests for PR #{pr_number}"
                if pr_number else
                "qa-automation: add tests"
            )
            _push_step(thinking_steps, {
                "type": "tool_call",
                "tool_name": "github_push",
                "content": f"Pushing {len(changed)} file(s) to `{head_branch}`.",
            }, on_thinking_step)
            push = await git_service.push_to_pr_branch(
                repo_path=repo_path,
                owner=target_owner,
                repo=target_repo,
                branch=head_branch,
                token=token,
                commit_message=commit_message,
                anthropic_api_key=api_key,
                emit=on_thinking_step,
            )
            if not push.get("success"):
                return {
                    "success": False,
                    "response": f"Push failed: {push.get('error')}",
                    "thinking_steps": thinking_steps,
                    "pr_url": pr_url,
                    "branch": head_branch,
                    "files_changed": changed_paths,
                }
            pushed_files: List[str] = push.get("files_pushed") or [
                c.get("file_path", "") for c in changed
            ]
            _push_step(thinking_steps, {
                "type": "tool_result",
                "tool_name": "github_push",
                "content": (
                    f"Pushed {len(pushed_files)} file(s) to `{head_branch}`."
                    if not push.get("skipped")
                    else "Nothing to push."
                ),
            }, on_thinking_step)

            self.sessions[session_id] = {
                "pr_url": pr_url,
                "branch": head_branch,
                "repo_path": repo_path,
                "last_pushed": pushed_files,
            }

            files_md = "\n".join(f"- `{p}`" for p in pushed_files[:30])
            response = (
                f"## QA Automation Run\n\n"
                f"**PR:** [{owner}/{repo}#{pr_number}]({pr_url})\n"
                f"**Target repo:** `{target_owner}/{target_repo}`\n"
                f"**Branch:** `{head_branch}`\n"
                f"**Files changed in PR:** {len(files)}\n\n"
                f"### Test files generated/updated ({len(pushed_files)})\n"
                f"{files_md or '_(none)_'}\n\n"
                f"### Claude Code summary\n"
                f"{summary or '_(no summary)_'}\n\n"
                f"**Cost:** ${cost_usd:.4f} · **Duration:** {duration_s:.1f}s\n\n"
                f"View the PR commits: "
                f"https://github.com/{owner}/{repo}/pull/{pr_number}/commits\n"
            )

            return {
                "success": True,
                "response": response,
                "thinking_steps": thinking_steps,
                "pr_url": pr_url,
                "branch": head_branch,
                "pushed_files": pushed_files,
                "files_changed": changed_paths,
                "summary": summary,
                "cost_usd": cost_usd,
                "duration_seconds": duration_s,
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as exc:
            import traceback
            traceback.print_exc()
            _push_step(thinking_steps, {
                "type": "tool_result",
                "content": f"❌ Error: {exc}",
            }, on_thinking_step)
            return {
                "success": False,
                "response": f"QA automation run failed: {exc}",
                "thinking_steps": thinking_steps,
                "pr_url": pr_url,
            }


qa_automation_agent = QAAutomationAgent()
