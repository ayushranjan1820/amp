__all__ = ["TraceDebuggerAgent", "trace_debugger_agent"]


def __getattr__(name):
    if name in ("TraceDebuggerAgent", "trace_debugger_agent"):
        from .agent import TraceDebuggerAgent, trace_debugger_agent

        globals()["TraceDebuggerAgent"] = TraceDebuggerAgent
        globals()["trace_debugger_agent"] = trace_debugger_agent
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
