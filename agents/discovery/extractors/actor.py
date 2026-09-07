"""Claude tool-schema extractor for actor pages."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agents.discovery.sources.base import FetchedDoc

PROMPT_VERSION = "actor_v1"

ACTOR_FIELDS = [
    "name",
    "actor_type",
    "actor_type_raw",
    "description",
    "website",
    "location_city",
    "state",
    "country",
    "primary_technical_focus",
    "technical_approach",
    "current_activities",
    "technology_ip_notes",
    "key_constraints",
    "estimated_trl",
    "primary_lifecycle_role",
    "sector_codes",
]

ACTOR_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "actors": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": ["string", "null"]},
                    "actor_type": {"type": ["string", "null"]},
                    "actor_type_raw": {"type": ["string", "null"]},
                    "description": {"type": ["string", "null"]},
                    "website": {"type": ["string", "null"]},
                    "location_city": {"type": ["string", "null"]},
                    "state": {"type": ["string", "null"]},
                    "country": {"type": ["string", "null"]},
                    "primary_technical_focus": {"type": ["string", "null"]},
                    "technical_approach": {"type": ["string", "null"]},
                    "current_activities": {"type": ["string", "null"]},
                    "technology_ip_notes": {"type": ["string", "null"]},
                    "key_constraints": {"type": ["string", "null"]},
                    "estimated_trl": {"type": ["integer", "string", "null"]},
                    "primary_lifecycle_role": {"type": ["string", "null"]},
                    "sector_codes": {
                        "type": ["array", "null"],
                        "items": {"type": "string"},
                    },
                },
                "required": ACTOR_FIELDS,
            },
        }
    },
    "required": ["actors"],
}


class ActorExtractor:
    entity_type = "actor"
    prompt_version = PROMPT_VERSION
    json_schema = ACTOR_TOOL_SCHEMA

    def __init__(self, llm_client, *, max_tokens: int = 2048):
        self.llm_client = llm_client
        self.max_tokens = max_tokens
        self.attention_reasons: list[str] = []

    def extract(self, doc: FetchedDoc) -> list[dict]:
        payload = self.llm_client.extract_with_tool(
            system=self._system_prompt(),
            user=self._user_prompt(doc),
            tool_name="record_actors",
            tool_description="Return organization actor records explicitly present in the source page.",
            input_schema=self.json_schema,
            max_tokens=self.max_tokens,
        )
        actors = payload.get("actors", []) if payload else []
        if not actors:
            return []
        extracted_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        records: list[dict] = []
        for actor in actors:
            record = {field: actor.get(field) for field in ACTOR_FIELDS}
            record["source_url"] = doc.url
            record["extracted_at"] = extracted_at
            record["prompt_version"] = self.prompt_version
            records.append(record)
        return records

    def _system_prompt(self) -> str:
        return (
            "You extract public organization records for the GHUS ecosystem database. "
            "Use only facts explicitly present in the source. Do not infer actor type, "
            "technical focus, geography, lifecycle role, TRL, or sectors. If a field is "
            "not present on the page, return null. If the page has no organizations, "
            "return an empty actors array."
        )

    def _user_prompt(self, doc: FetchedDoc) -> str:
        return (
            f"Source URL: {doc.url}\n"
            f"Content type: {doc.content_type}\n\n"
            "Extract organization actor records from this page. Any field not found in "
            "the source must be null, never guessed. Do not extract people here.\n\n"
            f"{doc.content[:12000]}"
        )
