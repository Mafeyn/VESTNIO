from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..domain import RawItem, SourceConfig
from ..fetcher import Fetcher


class ParseError(Exception):
    """The response was retrieved but could not be parsed into articles."""


class MissingCredentials(Exception):
    """An API adapter needs a key that is not configured; the source is skipped."""


@dataclass(slots=True)
class CacheState:
    """HTTP validators remembered between polls for conditional GET."""

    etag: str | None = None
    last_modified: str | None = None


@dataclass(slots=True)
class AdapterResult:
    items: list[RawItem] = field(default_factory=list)
    not_modified: bool = False
    cache: CacheState = field(default_factory=CacheState)


class Adapter(Protocol):
    name: str

    async def fetch(self, source: SourceConfig, fetcher: Fetcher, cache: CacheState) -> AdapterResult: ...
