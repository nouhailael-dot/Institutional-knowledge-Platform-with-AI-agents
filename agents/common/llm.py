"""LLM clients used by discovery extractors.

Production extraction uses Claude tool calls, not free-form JSON replies. Tests
and fixture dry-runs use FixtureToolClient so they do not touch the network.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from agents.common.cost import CostMeter

try:
    from src.ai.client import UsageTracker
except Exception:  # pragma: no cover - fallback only for isolated agent tests
    UsageTracker = None


@dataclass
class LLMUsage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def snapshot(self) -> dict[str, object]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
        }


class ClaudeToolClient:
    """Thin Anthropic client wrapper for structured tool output."""

    def __init__(
        self,
        model: str,
        *,
        cost_meter: Optional[CostMeter] = None,
        input_usd_per_million: float = 0.0,
        output_usd_per_million: float = 0.0,
    ):
        self.model = model
        self.cost_meter = cost_meter
        self.input_usd_per_million = float(input_usd_per_million or 0.0)
        self.output_usd_per_million = float(output_usd_per_million or 0.0)
        self.usage = LLMUsage()
        self.usage_tracker = UsageTracker(model=model) if UsageTracker is not None else None
        self._client = None

    def _get_client(self):
        if self._client is None:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise RuntimeError("ANTHROPIC_API_KEY is not set")
            from anthropic import Anthropic

            self._client = Anthropic()
        return self._client

    def extract_with_tool(
        self,
        *,
        system: str,
        user: str,
        tool_name: str,
        tool_description: str,
        input_schema: dict[str, Any],
        max_tokens: int = 2048,
        temperature: Optional[float] = 0.0,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": [
                {
                    "name": tool_name,
                    "description": tool_description,
                    "input_schema": input_schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": tool_name},
        }
        if temperature is not None:
            kwargs["temperature"] = temperature

        response = self._get_client().messages.create(**kwargs)
        self._record_usage(response)

        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_name:
                return dict(block.input)
        raise RuntimeError(f"Claude did not call required tool {tool_name!r}")

    def _record_usage(self, response) -> None:
        if self.usage_tracker is not None:
            before_cost = self.usage_tracker.cost_estimate()
            self.usage_tracker.record(response)
            after_cost = self.usage_tracker.cost_estimate()
            self.usage.calls = self.usage_tracker.calls
            self.usage.input_tokens = self.usage_tracker.input_tokens
            self.usage.output_tokens = self.usage_tracker.output_tokens
            self.usage.cost_usd = after_cost
            if self.cost_meter is not None:
                self.cost_meter.add(after_cost - before_cost, label=f"claude:{self.model}")
            return

        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        cost = (
            input_tokens * self.input_usd_per_million
            + output_tokens * self.output_usd_per_million
        ) / 1_000_000
        self.usage.calls += 1
        self.usage.input_tokens += input_tokens
        self.usage.output_tokens += output_tokens
        self.usage.cost_usd += cost
        if self.cost_meter is not None:
            self.cost_meter.add(cost, label=f"claude:{self.model}")


class FixtureToolClient:
    """Deterministic tool client for tests and offline fixture runs."""

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        self.usage = LLMUsage()

    @classmethod
    def from_path(cls, path: Path) -> "FixtureToolClient":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def extract_with_tool(self, **_: Any) -> dict[str, Any]:
        self.usage.calls += 1
        return copy.deepcopy(self.payload)
