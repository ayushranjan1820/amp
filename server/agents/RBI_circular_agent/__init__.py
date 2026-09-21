__all__ = ["RBICircularAgent", "rbi_agent", "RBIAgentRequest", "RBIAgentResponse"]

def __getattr__(name):
    if name in ("RBICircularAgent", "rbi_agent"):
        from .agent import RBICircularAgent, rbi_agent
        globals()["RBICircularAgent"] = RBICircularAgent
        globals()["rbi_agent"] = rbi_agent
        return globals()[name]
    if name in ("RBIAgentRequest", "RBIAgentResponse"):
        from . import models
        return getattr(models, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
