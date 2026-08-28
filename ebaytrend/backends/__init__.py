from .base import Backend, SearchResult
from .html_backend import HtmlBackend

__all__ = ["Backend", "SearchResult", "HtmlBackend", "get_backend"]


def get_backend(name: str, **kwargs):
    """Фабрика бэкендов: 'html' — скрейпер выдачи, 'api' — официальный Browse API."""
    if name == "html":
        return HtmlBackend(**kwargs)
    if name in ("api", "browse", "browse_api"):
        from .browse_api import BrowseApiBackend

        return BrowseApiBackend(**kwargs)
    raise ValueError(f"неизвестный бэкенд: {name}")
