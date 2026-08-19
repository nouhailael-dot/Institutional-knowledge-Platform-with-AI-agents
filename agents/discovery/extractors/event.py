"""Claude tool-schema extractor for event pages."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agents.discovery.sources.base import FetchedDoc

PROMPT_VERSION = "event_v1"

EVENT_FIELDS = [
    "title",
    "start_date",
    "end_date",
    "description",
    "location",
    "country",
    "website",
    "thematic_focus",
    "event_type",
    "expected_attendance",
    "access_type",
    "recurring_pattern",
    "sponsoring_orgs",
    "sector_codes",
]

EVENT_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": ["string", "null"]},
                    "start_date": {"type": ["string", "null"]},
                    "end_date": {"type": ["string", "null"]},
                    "description": {"type": ["string", "null"]},
                    "location": {"type": ["string", "null"]},
                    "country": {"type": ["string", "null"]},
                    "website": {"type": ["string", "null"]},
                    "thematic_focus": {"type": ["string", "null"]},
                    "event_type": {"type": ["string", "null"]},
                    "expected_attendance": {"type": ["string", "null"]},
                    "access_type": {"type": ["string", "null"]},
                    "recurring_pattern": {"type": ["string", "null"]},
                    "sponsoring_orgs": {"type": ["string", "null"]},
                    "sector_codes": {
                        "type": ["array", "null"],
                        "items": {"type": "string"},
                    },
                },
                "required": EVENT_FIELDS,
            },
        }
    },
    "required": ["events"],
}


class EventExtractor:
    entity_type = "event"
    prompt_version = PROMPT_VERSION
    json_schema = EVENT_TOOL_SCHEMA

    def __init__(self, llm_client, *, max_tokens: int = 2048):
        self.llm_client = llm_client
        self.max_tokens = max_tokens

    def extract(self, doc: FetchedDoc) -> list[dict]:
        payload = self.llm_client.extract_with_tool(
            system=self._system_prompt(),
            user=self._user_prompt(doc),
            tool_name="record_events",
            tool_description="Return events explicitly present in the source page.",
            input_schema=self.json_schema,
            max_tokens=self.max_tokens,
            temperature=0.0,
        )
        events = payload.get("events", []) if payload else []
        if not events:
            return []
        extracted_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        records: list[dict] = []
        for event in events:
            record = {field: event.get(field) for field in EVENT_FIELDS}
            record["source_url"] = doc.url
            record["extracted_at"] = extracted_at
            record["prompt_version"] = self.prompt_version
            records.append(record)
        return records

    def _system_prompt(self) -> str:
        return (
            "You extract public event records for the GHUS ecosystem database. "
            "Use only facts explicitly present in the source. Do not infer, guess, "
            "or fill missing fields. If the page has no events, return an empty "
            "events array."
        )

    def _user_prompt(self, doc: FetchedDoc) -> str:
        return (
            f"Source URL: {doc.url}\n"
            f"Content type: {doc.content_type}\n\n"
            "Extract event records from this page. Any field not found in the "
            "source must be null, never guessed.\n\n"
            f"{doc.content[:12000]}"
        )
