"""Parser Adapters: turn a source's raw response into RawItem records."""

from ..domain import IngestionMethod, SourceConfig
from .api import GuardianAdapter, HackerNewsAdapter
from .base import Adapter, AdapterResult, CacheState, MissingCredentials, ParseError
from .html import CssHtmlAdapter
from .rss import RssAdapter
from .telegram import TelegramChannelAdapter

_REGISTRY: dict[str, Adapter] = {
    a.name: a
    for a in (RssAdapter(), HackerNewsAdapter(), GuardianAdapter(), CssHtmlAdapter(), TelegramChannelAdapter())
}

_ALLOWED_METHODS = {
    "rss": IngestionMethod.RSS,
    "hackernews": IngestionMethod.API,
    "guardian": IngestionMethod.API,
    "html_css": IngestionMethod.HTML,
    "telegram": IngestionMethod.TELEGRAM,
}


_DEFAULT_ADAPTER = {
    IngestionMethod.RSS: "rss",
    IngestionMethod.HTML: "html_css",
    IngestionMethod.TELEGRAM: "telegram",
}


def get_adapter(source: SourceConfig) -> Adapter:
    name = source.adapter or _DEFAULT_ADAPTER.get(source.method)
    if name is None:
        raise KeyError(f"source {source.id} uses method {source.method.value!r} but names no adapter")
    adapter = _REGISTRY.get(name)
    if adapter is None:
        raise KeyError(f"unknown adapter {name!r} for source {source.id}")
    if _ALLOWED_METHODS[name] != source.method:
        raise ValueError(f"adapter {name!r} cannot serve method {source.method.value!r} ({source.id})")
    return adapter


__all__ = [
    "Adapter",
    "AdapterResult",
    "CacheState",
    "MissingCredentials",
    "ParseError",
    "get_adapter",
]
