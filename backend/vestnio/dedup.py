"""Duplicate Filter: canonical URL computation and in-batch de-duplication.

Three rules, applied in order:
  1. GUID      — (source_id, external_id) unique constraint in PostgreSQL
  2. URL       — url_hash = sha256(canonical URL) unique constraint, across all sources
  3. Fallback  — title fingerprint: the same normalized headline (>= MIN_FP_WORDS words)
                 seen within FINGERPRINT_WINDOW is treated as a duplicate. This catches
                 feeds that re-issue an item with a new GUID and a changed URL
                 (e.g. a slug edit, or syndicated wire copy published by two outlets).
Inserts use ON CONFLICT DO NOTHING, so re-polling a feed is idempotent.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable
from datetime import timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .domain import NormalizedArticle

TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "igshid", "yclid",
    "ref", "ref_src", "referrer", "cmpid", "cmp", "ocid", "taid", "ito", "rss",
    "at_medium", "at_campaign", "at_custom1", "at_custom2", "at_custom3", "at_custom4",
    "_ga", "spm", "smid", "smtyp", "guccounter",
}  # fmt: skip
TRACKING_PREFIXES = ("utm_", "at_", "pk_", "mtm_", "itm_")


def canonicalize_url(url: str) -> str:
    """Reduce equivalent article URLs to one form for duplicate detection.

    - scheme forced to https, host lower-cased, leading "www." and default ports removed
    - fragment dropped, tracking parameters dropped, remaining params sorted
    - trailing slash removed (except for the root path)
    """
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    port = parts.port
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"

    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith(TRACKING_PREFIXES)
    ]
    query.sort()
    return urlunsplit(("https", netloc, path, urlencode(query), ""))


def url_hash(canonical_url: str) -> str:
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()


MIN_FP_WORDS = 5
FINGERPRINT_WINDOW = timedelta(hours=72)
_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")


def title_fingerprint(title: str) -> str | None:
    """Normalized-headline hash, or None when the title is too short to be distinctive
    ("Live updates", "Today's Wordle") — short titles never match on this rule."""
    text = unicodedata.normalize("NFKC", title).casefold()
    text = text.replace("’", "'").replace("‘", "'")
    text = _NON_WORD.sub(" ", text)
    words = _SPACES.sub(" ", text).strip().split(" ")
    if len(words) < MIN_FP_WORDS:
        return None
    return hashlib.sha1(" ".join(words).encode("utf-8")).hexdigest()


def dedupe_batch(articles: Iterable[NormalizedArticle]) -> list[NormalizedArticle]:
    """Drop duplicates inside a single batch (same feed id, canonical URL or title
    fingerprint). The first occurrence wins, matching feed order."""
    seen_ids: set[tuple[str, str]] = set()
    seen_urls: set[str] = set()
    seen_fps: set[str] = set()
    out: list[NormalizedArticle] = []
    for a in articles:
        key = (a.source_id, a.external_id)
        if key in seen_ids or a.url_hash in seen_urls or (a.title_fp and a.title_fp in seen_fps):
            continue
        seen_ids.add(key)
        seen_urls.add(a.url_hash)
        if a.title_fp:
            seen_fps.add(a.title_fp)
        out.append(a)
    return out
