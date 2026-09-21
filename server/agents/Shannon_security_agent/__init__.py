__all__ = ["ShannonSecurityAgent", "shannon_security_agent"]

def __getattr__(name):
    if name in ("ShannonSecurityAgent", "shannon_security_agent"):
        from .agent import ShannonSecurityAgent, shannon_security_agent
        globals()["ShannonSecurityAgent"] = ShannonSecurityAgent
        globals()["shannon_security_agent"] = shannon_security_agent
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
