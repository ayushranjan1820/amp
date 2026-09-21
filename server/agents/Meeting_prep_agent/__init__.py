def __getattr__(name):
    if name == "meeting_prep_agent":
        from .agent import meeting_prep_agent
        return meeting_prep_agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
