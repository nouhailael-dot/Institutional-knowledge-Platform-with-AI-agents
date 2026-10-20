"""Retired legacy actor-type mutation entry point.

Architecture V2 category/type proposals must be staged and accepted through
``agents.enrichment.decisions``. This module keeps the old import contract only
so scheduled callers fail loudly instead of mutating canonical actors.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session


@dataclass
class RunStats:
    total_others_found: int = 0

    def summary(self) -> str:
        return "legacy reclassifier retired; no canonical records changed"


class _RetiredTracker:
    @staticmethod
    def summary() -> str:
        return "no model usage"


class OtherReclassifier:
    """Compatibility shell that prevents the former direct canonical writes."""

    def __init__(
        self,
        project_root: Path,
        session: Session,
        limit: int | None = None,
    ) -> None:
        self.project_root = project_root
        self.session = session
        self.limit = limit
        self.stats = RunStats()
        self.tracker = _RetiredTracker()

    def run(self) -> RunStats:
        raise RuntimeError(
            "legacy direct reclassification is retired; submit Architecture V2 "
            "category/type proposals through staged records and decisions.py"
        )
