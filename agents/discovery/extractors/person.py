"""Claude tool-schema extractor for public professional person records."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agents.discovery.sources.base import FetchedDoc

PROMPT_VERSION = "person_v1"

PERSON_FIELDS = [
    "name",
    "affiliation",
    "role",
    "public_profile_url",
    "research_area",
]

PERSON_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "people": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": ["string", "null"]},
                    "affiliation": {"type": ["string", "null"]},
                    "role": {"type": ["string", "null"]},
                    "public_profile_url": {"type": ["string", "null"]},
                    "research_area": {"type": ["string", "null"]},
                },
                "required": PERSON_FIELDS,
            },
        }
    },
    "required": ["people"],
}


class PersonExtractor:
    entity_type = "person"
    prompt_version = PROMPT_VERSION
    json_schema = PERSON_TOOL_SCHEMA

    def __init__(
        self,
        llm_client,
        *,
        max_tokens: int = 2048,
        people_enabled: bool = False,
    ):
        self.llm_client = llm_client
        self.max_tokens = max_tokens
        self.people_enabled = people_enabled
        self.attention_reasons: list[str] = []

    def extract(self, doc: FetchedDoc) -> list[dict]:
        if not self.people_enabled:
            raise RuntimeError(
                "person extraction is disabled pending TARGETING_POLICY.md section 6 approval"
            )
        payload = self.llm_client.extract_with_tool(
            system=self._system_prompt(),
            user=self._user_prompt(doc),
            tool_name="record_people",
            tool_description=(
                "Return public professional person records explicitly present in the source page."
            ),
            input_schema=self.json_schema,
            max_tokens=self.max_tokens,
        )
        people = payload.get("people", []) if payload else []
        if not people:
            return []
        extracted_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        records: list[dict] = []
        for person in people:
            record = {field: person.get(field) for field in PERSON_FIELDS}
            record["source_url"] = doc.url
            record["extracted_at"] = extracted_at
            record["prompt_version"] = self.prompt_version
            records.append(record)
        return records

    def _system_prompt(self) -> str:
        return (
            "You extract public professional person records for GHUS review. "
            "Use only facts explicitly present in the source. Return only name, "
            "affiliation, professional role, public profile URL, and research area. "
            "Do not extract contact details, private information, or biographical "
            "detail beyond the professional role. If a field is not present, return null. "
            "If the page has no people, return an empty people array."
        )

    def _user_prompt(self, doc: FetchedDoc) -> str:
        return (
            f"Source URL: {doc.url}\n"
            f"Content type: {doc.content_type}\n\n"
            "Extract public professional person records from this page. Any field "
            "not found in the source must be null, never guessed. Do not include "
            "email addresses, phone numbers, private details, or long biographies.\n\n"
            f"{doc.content[:12000]}"
        )
