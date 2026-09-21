__all__ = ["DocumentFormatterAgent"]

def __getattr__(name):
    if name == "DocumentFormatterAgent":
        from .agent import DocumentFormatterAgent
        return DocumentFormatterAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
