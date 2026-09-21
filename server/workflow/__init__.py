"""
Workflow package - Multi-agent workflow orchestration.
Re-exports all public symbols from orchestrator for backward compatibility.
"""

from .orchestrator import (
    # Core functions
    generate_workflow,
    generate_mermaid,
    execute_workflow,
    execute_workflow_streaming,
    call_llm,

    # User input handling
    needs_followup,
    extract_followup_question,
    wait_for_user_input,
    submit_user_input,

    # Database operations
    init_workflow_db,
    save_workflow,
    list_workflows,
    get_workflow,
    delete_workflow,
    create_execution,
    save_execution_step,
    complete_execution,
    list_executions,
    get_execution_detail,
    get_execution_summary,
    get_execution_step,

    # Constants / registry
    AGENT_REGISTRY,
    reload_agent_catalog,

    # Internal
    _pending_inputs,
    _build_agent_descriptions,
)

__all__ = [
    "generate_workflow",
    "generate_mermaid",
    "execute_workflow",
    "execute_workflow_streaming",
    "call_llm",
    "needs_followup",
    "extract_followup_question",
    "wait_for_user_input",
    "submit_user_input",
    "init_workflow_db",
    "save_workflow",
    "list_workflows",
    "get_workflow",
    "delete_workflow",
    "create_execution",
    "save_execution_step",
    "complete_execution",
    "list_executions",
    "get_execution_detail",
    "get_execution_summary",
    "get_execution_step",
    "AGENT_REGISTRY",
    "reload_agent_catalog",
    "_pending_inputs",
    "_build_agent_descriptions",
]
