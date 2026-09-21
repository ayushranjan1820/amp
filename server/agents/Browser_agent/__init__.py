__all__ = ["BrowserAgent", "browser_agent"]


def __getattr__(name):
    if name in ("BrowserAgent", "browser_agent"):
        from .agent import BrowserAgent, browser_agent
        globals()["BrowserAgent"] = BrowserAgent
        globals()["browser_agent"] = browser_agent
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
