__all__ = ["RouterAgent", "router_agent"]

def __getattr__(name):
    if name in ("RouterAgent", "router_agent"):
        from .agent import RouterAgent, router_agent
        globals()["RouterAgent"] = RouterAgent
        globals()["router_agent"] = router_agent
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
