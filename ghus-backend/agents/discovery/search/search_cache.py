"""Paid web searches, reused for a short time - events and people only.

Measured 2026-10-23: a retried event request paid again for the same twelve
searches ($0.27), and 146 of 505 event queries were exact repeats of an earlier
run's query. A search answered in the last ``search_cache_ttl_hours`` (default
72) is answered from disk instead of paid for again.

Why this cannot change what a run finds:
  * the weekly automatic run is seven days apart - longer than the TTL - so it
    always searches fresh; only retries, re-runs and overlapping requests reuse;
  * the cached answer is the provider's own result list, unchanged, for the
    exact same query and result count;
  * nothing else is cached here: every page is still fetched (or recognised as
    unchanged) and judged by the same gates.

The actor pipeline does not use this (Actor Discovery is unchanged).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agents.discovery.search.models import SearchResult

logger = logging.getLogger(__name__)
DEFAULT_TTL_HOURS = 72


class CachedSearchProvider:
    """Wraps a search provider; same interface, answers repeats from disk."""

    def __init__(self, provider, cache_dir: Path, *, ttl_hours: float = DEFAULT_TTL_HOURS,
                 stats: dict | None = None, now=None):
        self.provider = provider
        self.cache_dir = Path(cache_dir)
        self.ttl = timedelta(hours=float(ttl_hours))
        self.stats = stats if stats is not None else {}
        self._now = now or (lambda: datetime.now(UTC))
        # Anything the wrapped provider exposes (name, cost settings) stays visible.
        self.name = getattr(provider, "name", "search")

    def __getattr__(self, item):
        return getattr(self.provider, item)

    def _path(self, query: str, count: int, domains=None) -> Path:
        key = json.dumps([self.name, " ".join(query.split()).casefold(), int(count),
                          *([sorted(domains)] if domains else [])])
        return self.cache_dir / f"{hashlib.sha256(key.encode()).hexdigest()}.json"

    def search(self, query: str, count: int = 10,
               allowed_domains: list[str] | None = None) -> list[SearchResult]:
        path = self._path(query, count, allowed_domains)
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            stored = datetime.fromisoformat(cached["stored_at"])
            if self._now() - stored <= self.ttl:
                self.stats["searches_from_cache"] = int(
                    self.stats.get("searches_from_cache", 0) or 0) + 1
                return [SearchResult(**row) for row in cached["results"]]
        except FileNotFoundError:
            pass
        except (KeyError, TypeError, ValueError) as exc:  # a damaged entry is searched again
            logger.info("search cache entry %s ignored: %s", path.name, exc)
        results = (self.provider.search(query, count=count, allowed_domains=allowed_domains)
                   if allowed_domains else self.provider.search(query, count=count))
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "stored_at": self._now().isoformat(), "query": query, "count": int(count),
                "results": [asdict(r) for r in results]}, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:  # caching is a saving, never a reason to fail
            logger.info("search cache entry %s not written: %s", path.name, exc)
        return results
