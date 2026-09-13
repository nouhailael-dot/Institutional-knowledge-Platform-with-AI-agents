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
from typing import Any

from agents.common.cost import CostMeter

try:
    from src.ai.client import UsageTracker
except ImportError:  # pragma: no cover - fallback only for isolated agent tests
    UsageTracker = None


# Anthropic prompt-caching multipliers on the input rate.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10


@dataclass
class LLMUsage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0

    def snapshot(self) -> dict[str, object]:
        cached_total = self.cache_write_tokens + self.cache_read_tokens
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_hit_rate": (
                round(self.cache_read_tokens / cached_total, 3) if cached_total else 0.0
            ),
            "cost_usd": round(self.cost_usd, 6),
        }


class ClaudeToolClient:
    """Thin Anthropic client wrapper for structured tool output."""

    def __init__(
        self,
        model: str,
        *,
        cost_meter: CostMeter | None = None,
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
        cached_user: str | None = None,
    ) -> dict[str, Any]:
        kwargs = build_messages_create_kwargs(
            model=self.model,
            system=system,
            user=user,
            tool_name=tool_name,
            tool_description=tool_description,
            input_schema=input_schema,
            max_tokens=max_tokens,
            cached_user=cached_user,
        )
        response = self._get_client().messages.create(**kwargs)
        self._record_usage(response)

        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_name:
                return dict(block.input)
        raise RuntimeError(f"Claude did not call required tool {tool_name!r}")

    def _record_usage(self, response) -> None:
        usage_obj = getattr(response, "usage", None)
        has_cache_tokens = bool(
            int(getattr(usage_obj, "cache_creation_input_tokens", 0) or 0)
            or int(getattr(usage_obj, "cache_read_input_tokens", 0) or 0)
        )
        # UsageTracker predates prompt caching and does not price cached tokens,
        # so fall through to the manual path whenever caching is in play.
        if self.usage_tracker is not None and not has_cache_tokens:
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
        cache_write = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        cost = (
            input_tokens * self.input_usd_per_million
            + cache_write * self.input_usd_per_million * CACHE_WRITE_MULTIPLIER
            + cache_read * self.input_usd_per_million * CACHE_READ_MULTIPLIER
            + output_tokens * self.output_usd_per_million
        ) / 1_000_000
        self.usage.calls += 1
        self.usage.input_tokens += input_tokens
        self.usage.output_tokens += output_tokens
        self.usage.cache_write_tokens += cache_write
        self.usage.cache_read_tokens += cache_read
        self.usage.cost_usd += cost
        if self.cost_meter is not None:
            self.cost_meter.add(cost, label=f"claude:{self.model}")


class FixtureToolClient:
    """Deterministic tool client for tests and offline fixture runs."""

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        self.usage = LLMUsage()

    @classmethod
    def from_path(cls, path: Path) -> FixtureToolClient:
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def extract_with_tool(self, **_: Any) -> dict[str, Any]:
        self.usage.calls += 1
        return copy.deepcopy(self.payload)


def build_messages_create_kwargs(
    *,
    model: str,
    system: str,
    user: str,
    tool_name: str,
    tool_description: str,
    input_schema: dict[str, Any],
    max_tokens: int = 2048,
    cached_user: str | None = None,
) -> dict[str, Any]:
    """Build the Anthropic Messages.create request for tool-schema extraction.

    When ``cached_user`` is supplied the request is split so the stable prefix --
    system prompt, tool schema, and shared context -- is marked for prompt
    caching, and only ``user`` varies between calls. Cache reads are billed at a
    tenth of the input rate, which is the dominant cost saving on batched triage
    where the shared prefix is most of every request.
    """
    cache_marker = {"type": "ephemeral"}
    tool: dict[str, Any] = {
        "name": tool_name,
        "description": tool_description,
        "input_schema": input_schema,
    }

    if cached_user is None:
        return {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": [tool],
            "tool_choice": {"type": "tool", "name": tool_name},
        }

    tool["cache_control"] = cache_marker
    return {
        "model": model,
        "max_tokens": max_tokens,
        "system": [
            {"type": "text", "text": system, "cache_control": cache_marker}
        ],
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": cached_user,
                        "cache_control": cache_marker,
                    },
                    {"type": "text", "text": user},
                ],
            }
        ],
        "tools": [tool],
        "tool_choice": {"type": "tool", "name": tool_name},
    }