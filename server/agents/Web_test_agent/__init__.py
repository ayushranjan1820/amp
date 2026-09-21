__all__ = ["WebTestAgent", "web_test_agent"]


def __getattr__(name):
    if name in ("WebTestAgent", "web_test_agent"):
        from .agent import WebTestAgent, web_test_agent

        globals()["WebTestAgent"] = WebTestAgent
        globals()["web_test_agent"] = web_test_agent
        return globals()[name]
    if name == "Settings":
        from .core.config import Settings

        globals()["Settings"] = Settings
        return Settings
    if name == "get_settings":
        from .core.config import get_settings

        globals()["get_settings"] = get_settings
        return get_settings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
