__all__ = ["SEBICircularAgent", "sebi_agent", "SEBIAgentRequest", "SEBIAgentResponse"]

def __getattr__(name):
    if name in ("SEBICircularAgent", "sebi_agent"):
        from .agent import SEBICircularAgent, sebi_agent
        globals()["SEBICircularAgent"] = SEBICircularAgent
        globals()["sebi_agent"] = sebi_agent
        return globals()[name]
    if name in ("SEBIAgentRequest", "SEBIAgentResponse"):
        from . import models
        return getattr(models, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
