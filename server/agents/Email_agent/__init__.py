__all__ = ["EmailAgent", "email_agent"]

def __getattr__(name):
    if name in ("EmailAgent", "email_agent"):
        from .agent import email_agent, EmailAgent
        globals()["email_agent"] = email_agent
        globals()["EmailAgent"] = EmailAgent
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
