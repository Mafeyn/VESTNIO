"""Source Manager: loads the registry, syncs it to the DB, decides what is due,
and derives each source's operational status."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from pydantic import ValidationError

from .db.models import Source
from .domain import SourceConfig, SourceStatus

DEGRADED_AFTER = 1
FAILING_AFTER = 3
MAX_BACKOFF_FACTOR = 8  # a failing source is polled at most 8x less often


class RegistryError(ValueError):
    pass


def load_registry(path: Path) -> list[SourceConfig]:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise RegistryError(f"cannot read source registry {path}: {exc}") from exc

    defaults = data.get("defaults") or {}
    entries = data.get("sources") or []
    if not isinstance(entries, list):
        raise RegistryError("'sources' must be a list")

    configs: list[SourceConfig] = []
    seen: set[str] = set()
    errors: list[str] = []
    for i, entry in enumerate(entries):
        merged = {**defaults, **(entry or {})}
        try:
            cfg = SourceConfig.model_validate(merged)
        except ValidationError as exc:
            errors.append(f"sources[{i}] ({merged.get('id', '?')}): {exc.errors()[0]['msg']}")
            continue
        if cfg.id in seen:
            errors.append(f"duplicate source id {cfg.id!r}")
            continue
        seen.add(cfg.id)
        configs.append(cfg)
    if errors:
        raise RegistryError("invalid source registry:\n  " + "\n  ".join(errors))
    return configs


def status_after_failure(consecutive_failures: int) -> SourceStatus:
    """Status to store once a poll has failed (`consecutive_failures` includes this one)."""
    return SourceStatus.FAILING if consecutive_failures >= FAILING_AFTER else SourceStatus.DEGRADED


def next_poll_at(source: Source) -> datetime | None:
    """When the source is next due. Failing sources back off exponentially so a
    dead feed doesn't waste requests, while still being retried."""
    if source.last_polled_at is None:
        return None  # due now
    factor = 1
    if source.consecutive_failures >= FAILING_AFTER:
        factor = min(2 ** (source.consecutive_failures - FAILING_AFTER + 1), MAX_BACKOFF_FACTOR)
    return source.last_polled_at + timedelta(minutes=source.poll_minutes * factor)


def is_due(source: Source, now: datetime | None = None) -> bool:
    if not source.enabled or not source.in_registry:
        return False
    nxt = next_poll_at(source)
    return nxt is None or nxt <= (now or datetime.now(timezone.utc))
