"""Inspect a Zoho MCP connection: what it publishes, and how it maps.

Run from the ``server`` directory::

    python -m agents.Zoho_workflow_agents.discover_mcp
    python -m agents.Zoho_workflow_agents.discover_mcp --url https://.../message
    python -m agents.Zoho_workflow_agents.discover_mcp --schemas

It prints every published tool, then, for each of the three workflow agents,
which capabilities resolve and which are still missing. Use it after adding
services in the Zoho MCP console to confirm the agents can run, and to copy the
``ZOHO_MCP_TOOL_*`` override lines for any capability you want to pin.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import List

from .zoho_mcp import (
    AGENT_CAPABILITIES,
    CAPABILITIES,
    ZohoMCPClient,
    ZohoMCPError,
)


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    here = Path(__file__).resolve().parents[2]  # the server directory
    load_dotenv(here / ".env")
    load_dotenv(here.parent / ".env")


def _redact(url: str) -> str:
    """Hide the connection key in printed output; it is a credential."""
    parts = url.split("/")
    return "/".join(p if len(p) < 24 else p[:6] + "..." + p[-4:] for p in parts)


async def run(url: str, show_schemas: bool) -> int:
    async with ZohoMCPClient(url) as client:
        try:
            info = await client.initialize()
        except ZohoMCPError as exc:
            print(f"Could not connect: {exc}")
            return 1

        server = info.get("serverInfo") or {}
        print(f"Connected to {server.get('name', '?')} {server.get('version', '')} at {_redact(url)}")
        print(f"Protocol: {info.get('protocolVersion', '?')}")

        tools = await client.list_tools()
        print(f"\nPublished tools: {len(tools)}")
        if not tools:
            print(
                "\n  The connection publishes no tools.\n"
                "  Open the Zoho MCP console, add the Zoho services these agents need\n"
                "  (Mail, Calendar, Projects, Desk), save, then run this again."
            )
        for tool in tools:
            print(f"  - {tool.get('name')}")
            desc = (tool.get("description") or "").strip().splitlines()
            if desc:
                print(f"      {desc[0][:140]}")
            if show_schemas:
                schema = tool.get("inputSchema") or {}
                props = (schema.get("properties") or {}) if isinstance(schema, dict) else {}
                required = schema.get("required") or []
                if props:
                    print(f"      args: {', '.join(sorted(props))}")
                if required:
                    print(f"      required: {', '.join(required)}")

        print("\nCapability resolution per agent:")
        overall_ok = True
        for agent_id, groups in AGENT_CAPABILITIES.items():
            print(f"\n  {agent_id}")
            for label in ("required", "optional"):
                for key in groups.get(label, []):
                    cap = CAPABILITIES[key]
                    try:
                        name, _schema = await client.resolve(key)
                        print(f"    [ok]      {key:26} -> {name}   ({label})")
                    except ZohoMCPError:
                        marker = "[MISSING]" if label == "required" else "[absent] "
                        print(f"    {marker} {key:26} -> none   ({cap.service}: {cap.summary})")
                        if label == "required":
                            overall_ok = False

        print("\nOverride keys (set one only if auto-resolution picks the wrong tool):")
        for key, cap in CAPABILITIES.items():
            print(f"  {cap.env_key}=<tool name>   # {key}")

        if overall_ok and tools:
            print("\nAll required capabilities resolve. The agents can run over MCP.")
        else:
            print("\nSome required capabilities are unresolved; those workflow steps will fail.")
        return 0 if overall_ok else 2


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="", help="MCP /message URL (default: ZOHO_MCP_URL from the environment)")
    parser.add_argument("--schemas", action="store_true", help="Also print each tool's argument names")
    args = parser.parse_args(argv)

    _load_env()
    url = args.url or os.environ.get("ZOHO_MCP_URL") or os.environ.get("ZOHO_MCP_SERVER_URL") or ""
    if not url:
        print("No MCP URL. Pass --url, or set ZOHO_MCP_URL in server/.env.", file=sys.stderr)
        return 1
    return asyncio.run(run(url, args.schemas))


if __name__ == "__main__":
    raise SystemExit(main())
