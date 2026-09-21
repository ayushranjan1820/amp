# Langfuse Agent

Full-capability Langfuse observability agent. Ask anything about your LLM traces, sessions, scores, prompts, datasets, and metrics.

## What it does

The agent interprets any open-ended query and automatically decides which Langfuse operations to run:

- **Search traces** — filter by name, user, session, tags, time range
- **Inspect a trace** — get full details with observations, scores, token usage
- **Debug a trace** — root cause analysis, failure classification, concrete fixes
- **Explore sessions** — list sessions, get all traces in a session, analyze patterns
- **View scores** — evaluations and quality metrics with aggregates
- **Get observations** — spans, generations, tool calls for any trace
- **Compare traces** — side-by-side comparison of multiple traces
- **Compute metrics** — token usage, latency, cost, error rates across traces
- **Browse logs** — latest traces, recent activity overview
- **Manage prompts** — list and retrieve prompts from Langfuse prompt management
- **Inspect datasets** — list and retrieve dataset details

## How it works

1. **Orchestrator LLM** interprets user intent and plans which operations to run
2. **Langfuse client** executes operations: fetch traces, list sessions, get scores, etc.
3. **Normalizer** structures raw trace data into a rich analysis schema
4. **Analyzer LLM** inspects or debugs trace data based on context
5. **Response LLM** formats the final answer naturally — no fixed output format

## API

```
POST /api/debug-trace
POST /debug-trace
```

### Request

```json
{
  "query": "Show me the latest traces with errors",
  "session_id": "optional-session-id"
}
```

Or pass a trace ID directly:

```json
{
  "trace_id": "trc_abc123"
}
```

Or even send no parameters — the agent will show you recent activity.

### Response

The response format adapts to the query. The agent returns whatever is most useful.

## Example queries

```
Show me the latest traces
Debug trace trc_xyz — what went wrong?
Search traces for session abc123
What are the token usage stats for my recent runs?
Compare the last 5 traces
List all sessions from today
Show me scores and evaluations
Explore session xyz — give me the full picture
What prompts are configured in my project?
Get the observations for trace trc_abc
Which traces have errors in the last 24 hours?
Show me the cost breakdown of recent traces
```

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LANGFUSE_PUBLIC_KEY` | Yes | — | Langfuse API public key |
| `LANGFUSE_SECRET_KEY` | Yes | — | Langfuse API secret key |
| `LANGFUSE_HOST` | No | `https://cloud.langfuse.com` | Langfuse host URL |
| `PWC_GENAI_API_KEY` | Yes* | — | PwC GenAI API key (*required in pwc_genai mode) |
| `PWC_GENAI_BEARER_TOKEN` | No | — | PwC Bearer token |
| `PWC_GENAI_ENDPOINT_URL` | No | PwC shared service | PwC GenAI endpoint |
| `TRACE_DEBUGGER_MODEL` | No | `` | Model for analysis |
| `LLM_PROVIDER` | No | `pwc_genai` | `pwc_genai`, `local_llm`, or `ollama_cloud` |

## Install

```bash
pip install -r agents/Trace_debugger_agent/requirements.txt
```
