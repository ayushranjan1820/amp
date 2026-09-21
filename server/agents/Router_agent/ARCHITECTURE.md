# Router Agent Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                      RouterAgent                            │
│                   (Main Orchestrator)                       │
└────────────┬───────────────┬───────────────┬────────────────┘
             │               │               │
             │               │               │
    ┌────────▼────────┐ ┌───▼────────┐ ┌───▼────────────┐
    │  Config Module  │ │ Core Module│ │Services Module │
    └────────┬────────┘ └─────┬──────┘ └────────┬───────┘
             │                │                  │
             │                │                  │
    ┌────────▼────────┐      │         ┌────────▼────────┐
    │ CatalogLoader   │      │         │   LLMService    │
    │                 │      │         │                 │
    │ • Load catalog  │      │         │ • Call LLM API  │
    │ • Agent info    │      │         │ • Continuation  │
    │ • Guidelines    │      │         └─────────────────┘
    └─────────────────┘      │
                             │         ┌─────────────────┐
                    ┌────────▼──────┐  │  AgentLoader    │
                    │ QueryClassifier│  │                 │
                    │                │  │ • Load agents   │
                    │ • Keywords     │  │ • Cache         │
                    │ • LLM analysis │  │ • Reflection    │
                    │ • Fallback     │  └─────────────────┘
                    └────────────────┘
                             │         ┌─────────────────┐
                    ┌────────▼──────┐  │  AgentInvoker   │
                    │ContextBuilder │  │                 │
                    │                │  │ • Call agents   │
                    │ • Build context│  │ • Map params    │
                    │ • Token aware  │  │ • Normalize     │
                    └────────────────┘  └─────────────────┘
                             │
                    ┌────────▼──────┐  ┌─────────────────┐
                    │ TokenManager  │  │ResponseFormatter│
                    │                │  │                 │
                    │ • Count tokens │  │ • Normalize     │
                    │ • Manage budget│  │ • Format steps  │
                    └────────────────┘  └─────────────────┘
```

## Data Flow

```
User Query
    │
    ▼
RouterAgent.route_and_respond()
    │
    ├──> QueryClassifier.classify_query()
    │    ├──> TokenManager.count_tokens()
    │    ├──> CatalogLoader.get_agent_summaries()
    │    └──> LLMService.call_llm()
    │
    ├──> ContextBuilder.build_context_query()
    │    └──> TokenManager.count_tokens()
    │
    ├──> AgentInvoker.invoke_agent()
    │    ├──> AgentLoader.get_agent_instance()
    │    ├──> CatalogLoader.get_agent_info()
    │    └──> ResponseFormatter.normalize_thinking_steps()
    │
    ▼
Response to User
```

## Module Dependencies

```
agent.py
  ├─> config/catalog_loader.py
  ├─> services/llm_service.py (depends on: agents.llm_continuation)
  ├─> services/agent_loader.py (depends on: catalog_loader)
  ├─> services/agent_invoker.py (depends on: catalog_loader, agent_loader, context_builder, response_formatter)
  ├─> core/token_manager.py (depends on: tiktoken [optional])
  ├─> core/classifier.py (depends on: catalog_loader, llm_service, token_manager)
  └─> core/context_builder.py (depends on: token_manager)
```

## Key Design Patterns

1. **Dependency Injection**: RouterAgent receives all dependencies in __init__
2. **Single Responsibility**: Each module handles one concern
3. **Service Layer**: Services encapsulate external interactions
4. **Configuration-Driven**: Behavior driven by agents_catalog.json
5. **Strategy Pattern**: Different context building strategies per agent type
