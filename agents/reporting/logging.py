"""Trace logging for reporting-agent tool calls."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import text


@dataclass(frozen=True)
class ToolLogEntry:
    request_id: str
    question: str
    tool_name: str
    phase: str
    iteration: int
    payload: dict[str, Any]


class QueryLogToolLogger:
    """Write each tool call/result into query_log using its existing JSON fields."""

    def __init__(self, session):
        self.session = session

    def log(self, entry: ToolLogEntry) -> None:
        found_by = {
            "request_id": entry.request_id,
            "tool_name": entry.tool_name,
            "phase": entry.phase,
            "iteration": entry.iteration,
            "payload": _compact(entry.payload),
        }
        self.session.execute(
            text(
                "INSERT INTO query_log (query_id, question, route, found_by, answer) "
                "VALUES (CAST(:query_id AS uuid), :question, :route, "
                "CAST(:found_by AS jsonb), :answer)"
            ),
            {
                "query_id": str(uuid.uuid4()),
                "question": entry.question,
                "route": "reporting_agent_tool",
                "found_by": json.dumps(found_by, sort_keys=True, default=str),
                "answer": _answer_preview(entry.payload),
            },
        )
        self.session.commit()


class InMemoryToolLogger:
    def __init__(self):
        self.entries: list[ToolLogEntry] = []

    def log(self, entry: ToolLogEntry) -> None:
        self.entries.append(entry)


def _compact(value: Any, *, max_chars: int = 4000) -> Any:
    text_value = json.dumps(value, sort_keys=True, default=str)
    if len(text_value) <= max_chars:
        return value
    return {"truncated": True, "preview": text_value[:max_chars]}


def _answer_preview(value: Any) -> Optional[str]:
    text_value = json.dumps(value, sort_keys=True, default=str)
    if not text_value:
        return None
    return text_value[:2000]
