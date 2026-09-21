__all__ = ["CompanySolutionAgent"]


def __getattr__(name):
    if name == "CompanySolutionAgent":
        from .agent import CompanySolutionAgent

        return CompanySolutionAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
