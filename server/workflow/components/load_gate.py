"""Limit concurrent runs of expensive catalog agents during workflow execution."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Dict, FrozenSet

# Agents that are typically slow or resource-heavy (LLM + I/O bound).
_HEAVY_AGENT_IDS: FrozenSet[str] = frozenset(
    {
        "ppt_generator",
        "company_research",
        "company_solution_advisor",
        "market_research",
        "meeting_prep",
        "claude_code",
        "workspace_coding",
        "github_repo",
        "unit_test_agent",
        "web_test_agent",
        "brd_generation",
        "shannon_security",
        "code_sandbox",
        "bpmn_generator",
        "document_formatter",
        "mongodb_rag",
        "sql_db",
        "rbi_circular",
        "sebi_circular",
        "web_search_agent",
        "email_agent",
        "jira_agent",
        "basic_agent",
    },
)

_default_limit = max(1, int(os.getenv("WORKFLOW_HEAVY_AGENT_CONCURRENCY", "4")))
_semaphores: Dict[str, asyncio.Semaphore] = {}


def _semaphore_for(agent_id: str) -> asyncio.Semaphore:
    if agent_id not in _semaphores:
        _semaphores[agent_id] = asyncio.Semaphore(_default_limit)
    return _semaphores[agent_id]


@asynccontextmanager
async def heavy_agent_slot(agent_id: str):
    """Serialize excess concurrency for heavy agents; no-op for others."""
    if agent_id not in _HEAVY_AGENT_IDS:
        yield
        return
    sem = _semaphore_for(agent_id)
    await sem.acquire()
    try:
        yield
    finally:
        sem.release()
