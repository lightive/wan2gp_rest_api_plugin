"""Wan2GP REST API Plugin — exposes image/video generation via local REST API."""

__all__ = ["RestApiPlugin"]


def __getattr__(name: str):
    # Lazy import so merely importing the package (e.g. during test collection)
    # does not pull in plugin.py -> the Wan2GP-only `shared` host package.
    if name == "RestApiPlugin":
        from .plugin import RestApiPlugin

        return RestApiPlugin
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    # Keep RestApiPlugin discoverable via dir()/inspect despite the lazy import.
    return sorted({*globals(), *__all__})
