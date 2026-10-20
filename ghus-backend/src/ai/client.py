"""
Shared Anthropic Claude client and low-level utilities for AI enrichment tasks.

Combines robust JSON extraction with cost tracking and typed-exception retries.
Extractors call structured_json() and get a plain dict, or use call_claude()
for raw text. Nothing here touches the database.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from anthropic import Anthropic, APIError, APIStatusError
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

logger = logging.getLogger(__name__)

# Pinned to current, active model IDs (verified 2026-06).
HAIKU = "claude-haiku-4-5"
SONNET = "claude-sonnet-5"
OPUS = "claude-opus-4-8"

PRICING = {
    HAIKU: {"input": 1.00, "output": 5.00},
    SONNET: {"input": 3.00, "output": 15.00},
    OPUS: {"input": 5.00, "output": 25.00},
}

_client: Optional[Anthropic] = None


def get_client() -> Anthropic:
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set — add it to your .env.")
        _client = Anthropic()
    return _client


@dataclass
class UsageTracker:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    failures: int = 0
    model: str = ""

    def record(self, response):
        self.input_tokens += response.usage.input_tokens
        self.output_tokens += response.usage.output_tokens
        self.calls += 1

    def cost_estimate(self) -> float:
        p = PRICING.get(self.model)
        if not p:
            return 0.0
        return (self.input_tokens * p["input"] + self.output_tokens * p["output"]) / 1_000_000

    def summary(self) -> str:
        return (
            f"  Model:          {self.model}\n"
            f"  Calls:          {self.calls}\n"
            f"  Failures:       {self.failures}\n"
            f"  Input tokens:   {self.input_tokens:,}\n"
            f"  Output tokens:  {self.output_tokens:,}\n"
            f"  Est. cost:      ${self.cost_estimate():.4f}"
        )


def call_claude(model: str, system: str, user: str, max_tokens: int = 500,
                tracker: Optional[UsageTracker] = None, max_retries: int = 3) -> Optional[str]:
    """Call Claude with typed-exception retries. Returns text, or None on failure."""
    for attempt in range(max_retries):
        try:
            response = get_client().messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            if tracker:
                tracker.record(response)
            return "".join(b.text for b in response.content if b.type == "text").strip()

        except APIStatusError as e:
            if e.status_code in (429, 529):  # rate limited / overloaded — retry
                wait = 2 ** attempt
                logger.warning("API status %d, attempt %d; waiting %ds",
                               e.status_code, attempt + 1, wait)
                time.sleep(wait)
                continue
            logger.error("Non-retryable API error: %s", e)  # 4xx — fail fast
            if tracker:
                tracker.failures += 1
            return None

        except APIError as e:  # network/transient — retry
            wait = 2 ** attempt
            logger.warning("API error attempt %d: %s; retrying in %ds", attempt + 1, e, wait)
            time.sleep(wait)

    if tracker:
        tracker.failures += 1
    return None


def structured_json(system: str, user: str, model: str = HAIKU, max_tokens: int = 1024,
                    tracker: Optional[UsageTracker] = None) -> Optional[dict]:
    """Call Claude and return the JSON object from its reply as a dict, or None."""
    text = call_claude(model, system, user, max_tokens, tracker)
    return parse_json_response(text)


def parse_json_response(text: Optional[str]) -> Optional[dict]:
    """Extract the first {...} object from a reply, tolerating fences and stray text."""
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) >= 2 else text
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        logger.warning("No JSON object in reply: %s", text[:200])
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        logger.warning("JSON parse failed: %s\n%s", e, text[:200])
        return None