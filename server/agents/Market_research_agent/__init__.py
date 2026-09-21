__all__ = ["MarketResearchAgent"]

def __getattr__(name):
    if name == "MarketResearchAgent":
        from .agent import MarketResearchAgent
        return MarketResearchAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
