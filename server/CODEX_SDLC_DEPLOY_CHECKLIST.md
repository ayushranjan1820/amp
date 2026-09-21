# Codex SDLC Deploy Checklist

Use this checklist before enabling the Codex SDLC agent in production.

## 1. Host prerequisites

- Install Python 3.11+.
- Install Git and ensure `git --version` works.
- Install Node.js if JavaScript/TypeScript repos will be validated (`npm`, `npx`).
- Install Codex CLI and ensure `codex --version` works for the same user running the API server.

## 2. Codex runtime setup

- Authenticate Codex CLI on the host account used by the API process.
- Verify Codex usage quota for the deployment account.
- Set optional runtime env vars in `server/.env`:
  - `CODEX_CLI_PATH`
  - `CODEX_MODEL`
  - `CODEX_PROFILE`
  - `CODEX_SANDBOX`
  - `CODEX_SDLC_ISOLATED_WORKSPACE=true`
  - `CODEX_SDLC_WORKSPACE_BASE` (optional custom path)

## 3. Validation toolchain

Install scanners/test tooling needed by your repos:

- Python repos: `pytest`, `pytest-cov`, `ruff`, `bandit`, `pip-audit`
- JS repos: test and lint scripts in `package.json`
- Security scan: `semgrep` (recommended)

## 4. Run preflight locally on server

From `server/`:

```bash
python codex_sdlc_preflight.py
```

Optional smoke test (checks live codex exec capability):

```bash
python codex_sdlc_preflight.py --smoke
```

Exit codes:

- `0`: ready
- `1`: degraded (warnings)
- `2`: blocked (required checks failed)

## 5. Run preflight via API

Without smoke:

```http
GET /api/codex-sdlc/preflight
```

With smoke:

```http
GET /api/codex-sdlc/preflight?include_smoke=true
```

## 6. Go-live gates

- Preflight status is `ready`.
- `codex_smoke` is `passed` in production.
- Isolated workspace path is writable.
- First non-destructive run (`dry_run=true`) completes successfully.
- First write run on a test repository passes tests/lint/coverage gates.
