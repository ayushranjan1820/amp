"""
Workflow Orchestrator — thin re-export facade.

All logic lives in ``workflow.components.*`` sub-modules:
  catalog       – agent registry / dispatch table loaded from agents_catalog.json
  followup      – follow-up detection & extraction
  user_input    – pending user-input futures
  dispatch      – low-level agent invocation & routing
  step_helpers  – query dependency resolution, KB injection, result normalisation
  llm_helpers   – LLM calls, workflow + mermaid generation
  execution     – sync & streaming workflow execution
  db            – MongoDB persistence helpers

This file exists purely for backward compatibility so that
``from workflow.orchestrator import X`` continues to work.
"""

# --- Catalog / registry ---------------------------------------------------
from .components.catalog import (                    # noqa: F401
    AGENT_REGISTRY,
    AGENT_PROGRESS_PHASES,
    reload_agent_catalog,
)

# --- Follow-up detection ---------------------------------------------------
from .components.followup import (                   # noqa: F401
    needs_followup,
    extract_followup_question,
)

# --- User-input management -------------------------------------------------
from .components.user_input import (                 # noqa: F401
    _pending_inputs,
    wait_for_user_input,
    submit_user_input,
)

# --- LLM / workflow generation ---------------------------------------------
from .components.llm_helpers import (                # noqa: F401
    call_llm,
    generate_workflow,
    generate_mermaid,
    _build_agent_descriptions,
)

# --- Execution -------------------------------------------------------------
from .components.execution import (                  # noqa: F401
    execute_workflow,
    execute_workflow_streaming,
)

# --- Database helpers ------------------------------------------------------
from .components.db import (                         # noqa: F401
    init_workflow_db,
    save_workflow,
    list_workflows,
    get_workflow,
    delete_workflow,
    create_execution,
    save_execution_step,
    complete_execution,
    list_executions,
    list_workflow_run_user_ids,
    get_execution_detail,
    get_execution_summary,
    get_execution_step,
    get_execution_owner_user_id,
    get_execution_workflow_id,
    delete_execution,
)
