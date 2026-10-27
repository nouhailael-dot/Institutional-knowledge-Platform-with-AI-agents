"""Run-level cost accounting for agents.

The meter is intentionally provider-neutral. LLM clients add observed or
estimated costs; orchestration code checks the configured ceiling before
continuing to the next unit of work.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Optional


class CostLimitExceeded(RuntimeError):
    """Raised when a run exceeds its configured USD ceiling."""


@dataclass
class CostEntry:
    label: str
    amount_usd: float


@dataclass
class CostMeter:
    max_usd: Optional[float] = None
    spent_usd: float = 0.0
    entries: list[CostEntry] = field(default_factory=list)
    # Told the new total after each cost, so a running run can show its spend.
    # A failing listener never affects the run.
    on_change: Callable[[float], None] | None = field(default=None, repr=False,
                                                      compare=False)

    def add(self, amount_usd: float, label: str = "") -> None:
        amount = float(amount_usd or 0.0)
        if amount < 0:
            raise ValueError("cost amount cannot be negative")
        if amount == 0:
            return
        self.spent_usd += amount
        self.entries.append(CostEntry(label=label, amount_usd=amount))
        if self.on_change is not None:
            try:
                self.on_change(self.spent_usd)
            except Exception:  # progress is informative only; the run goes on
                logging.getLogger(__name__).debug("cost progress listener failed",
                                                  exc_info=True)

    def enforce(self) -> None:
        if self.max_usd is not None and self.spent_usd > float(self.max_usd):
            raise CostLimitExceeded(
                f"agent run cost ${self.spent_usd:.4f} exceeded ceiling "
                f"${float(self.max_usd):.4f}"
            )

    def snapshot(self) -> dict[str, object]:
        return {
            "max_usd": self.max_usd,
            "spent_usd": round(self.spent_usd, 6),
            "entries": [entry.__dict__.copy() for entry in self.entries],
        }
