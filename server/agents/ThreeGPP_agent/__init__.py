__all__ = ["ThreeGPPAgent"]

def __getattr__(name):
    if name == "ThreeGPPAgent":
        from .agent import ThreeGPPAgent
        return ThreeGPPAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
