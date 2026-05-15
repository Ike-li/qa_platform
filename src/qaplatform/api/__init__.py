def __getattr__(name: str):
    if name == "create_app":
        from qaplatform.main import create_app
        return create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
