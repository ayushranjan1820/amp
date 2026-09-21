"""
Workflow components — modular sub-packages of the orchestrator.

Each module owns a single concern:
  followup      – follow-up detection & extraction
  user_input    – pending user-input futures
  catalog       – agent catalog loader (from agents_catalog.json)
  dispatch      – low-level agent invocation / dispatch
  step_helpers  – query dep resolution, KB injection, result normalisation
  llm_helpers   – LLM calls, workflow + mermaid generation
  execution     – sync & streaming workflow execution
  db            – MongoDB persistence helpers
"""
