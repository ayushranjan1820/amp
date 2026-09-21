"""BRD Generation Agent package initialization."""
__all__ = ["BRDGenerationAgent", "BRDAgentRequest", "BRDAgentResponse", "ThinkingStep"]

def __getattr__(name):
    if name == "BRDGenerationAgent":
        from .agent import BRDGenerationAgent
        return BRDGenerationAgent
    if name in ("BRDAgentRequest", "BRDAgentResponse", "ThinkingStep"):
        from . import models
        return getattr(models, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
