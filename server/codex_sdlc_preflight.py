from __future__ import annotations

import argparse
import json
from pathlib import Path

from agents.Codex_sdlc_agent.services.preflight_service import run_codex_sdlc_preflight


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex SDLC deployment preflight check")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run a read-only codex exec smoke test (requires codex auth/quota)",
    )
    parser.add_argument(
        "--cwd",
        default=str(Path(__file__).resolve().parent),
        help="Working directory used by the optional codex smoke test",
    )
    args = parser.parse_args()

    payload = run_codex_sdlc_preflight(include_smoke=args.smoke, cwd=args.cwd)
    print(json.dumps(payload, indent=2))

    if payload["status"] == "ready":
        return 0
    if payload["status"] == "degraded":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
