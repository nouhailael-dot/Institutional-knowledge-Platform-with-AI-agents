"""Source adapter contracts for discovery."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterator, Protocol


@dataclass(frozen=True)
class FetchedDoc:
    url: str
    content: str
    content_type: str
    fetched_at: str
    content_hash: str
    meta: dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_content(
        cls,
        *,
        url: str,
        content: str,
        content_type: str = "text/html",
        fetched_at: str | None = None,
        meta: dict[str, object] | None = None,
    ) -> "FetchedDoc":
        fetched = fetched_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        # PostgreSQL text cannot hold NUL bytes (seen in some PDFs and reports).
        content = content.replace("\x00", "")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return cls(
            url=url,
            content=content,
            content_type=content_type,
            fetched_at=fetched,
            content_hash=digest,
            meta=meta or {},
        )


class SourceAdapter(Protocol):
    name: str
    entity_types: tuple[str, ...]
    rate_limit_s: float

    def discover(self) -> Iterator[str]:
        ...

    def fetch(self, url: str) -> FetchedDoc:
        ...
