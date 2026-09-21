def __getattr__(name):
    if name == "qa_automation_agent":
        from .agent import qa_automation_agent
        return qa_automation_agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
