__all__ = ["PPTGeneratorAgent"]

def __getattr__(name):
    if name == "PPTGeneratorAgent":
        from .agent import PPTGeneratorAgent
        return PPTGeneratorAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
