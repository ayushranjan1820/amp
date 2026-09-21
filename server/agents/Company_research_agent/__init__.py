__all__ = ["CompanyResearchAgent"]

def __getattr__(name):
    if name == "CompanyResearchAgent":
        from .agent import CompanyResearchAgent
        return CompanyResearchAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
