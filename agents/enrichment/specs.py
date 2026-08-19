"""Canonical entity specifications used by enrichment and index refresh."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional


@dataclass(frozen=True)
class EntitySpec:
    entity_type: str
    table_name: str
    id_column: str
    name_column: str
    fields: tuple[str, ...]
    updated_at_column: Optional[str]
    source_id_column: Optional[str] = "source_id"
    verification_status_column: Optional[str] = "verification_status"
    confidence_column: Optional[str] = "confidence"
    source_url_columns: tuple[str, ...] = ()
    doc_builder: Optional[Callable[[dict[str, object]], str]] = None


def _clean(value: object) -> str:
    return " ".join(str(value or "").replace("\n", " ").split())


def _append(lines: list[str], label: str, value: object) -> None:
    cleaned = _clean(value)
    if cleaned:
        lines.append(f"{label}: {cleaned}")


def _build_actor_doc(row: dict[str, object]) -> str:
    lines: list[str] = []
    _append(lines, "Name", row.get("name"))
    _append(lines, "Type", row.get("actor_type"))
    _append(lines, "Website", row.get("website"))
    location = ", ".join(
        part
        for part in (
            _clean(row.get("location_city")),
            _clean(row.get("state")),
            _clean(row.get("country")),
        )
        if part
    )
    _append(lines, "Location", location)
    _append(lines, "Description", row.get("description"))
    _append(lines, "Primary technical focus", row.get("primary_technical_focus"))
    _append(lines, "Technical approach", row.get("technical_approach"))
    _append(lines, "Current activities", row.get("current_activities"))
    _append(lines, "Technology/IP notes", row.get("technology_ip_notes"))
    _append(lines, "Key constraints", row.get("key_constraints"))
    _append(lines, "Funding summary", row.get("funding_summary"))
    _append(lines, "Lifecycle role", row.get("primary_lifecycle_role"))
    return "\n".join(lines)


def _build_hub_doc(row: dict[str, object]) -> str:
    lines: list[str] = []
    _append(lines, "Name", row.get("name"))
    location = ", ".join(
        part
        for part in (
            _clean(row.get("primary_city")),
            _clean(row.get("state")),
            _clean(row.get("country")),
        )
        if part
    )
    _append(lines, "Location", location)
    _append(lines, "Websites", row.get("official_websites"))
    _append(lines, "Description", row.get("description"))
    _append(lines, "Strategic value", row.get("strategic_value_summary"))
    _append(lines, "Core topic strengths", row.get("core_topic_strengths"))
    _append(lines, "Funding summary", row.get("funding_summary"))
    return "\n".join(lines)


def _build_person_doc(row: dict[str, object]) -> str:
    lines: list[str] = []
    _append(lines, "Name", row.get("full_name"))
    _append(lines, "Title", row.get("title"))
    _append(lines, "LinkedIn", row.get("linkedin_url"))
    _append(lines, "ORCID", row.get("orcid"))
    _append(lines, "Country code", row.get("country_code"))
    _append(lines, "Bio", row.get("bio"))
    return "\n".join(lines)


def _build_event_doc(row: dict[str, object]) -> str:
    lines: list[str] = []
    _append(lines, "Name", row.get("name"))
    _append(lines, "Type", row.get("event_type"))
    _append(lines, "Website", row.get("website"))
    _append(lines, "Location", row.get("location"))
    _append(lines, "Next date", row.get("next_date"))
    _append(lines, "Description", row.get("description"))
    _append(lines, "Thematic focus", row.get("thematic_focus"))
    _append(lines, "Expected attendance", row.get("expected_attendance"))
    _append(lines, "Access type", row.get("access_type"))
    _append(lines, "Recurring pattern", row.get("recurring_pattern"))
    _append(lines, "Sponsoring organizations", row.get("sponsoring_orgs"))
    return "\n".join(lines)


ENTITY_SPECS: dict[str, EntitySpec] = {
    "actor": EntitySpec(
        entity_type="actor",
        table_name="actor",
        id_column="actor_id",
        name_column="name",
        fields=(
            "name",
            "actor_type",
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
            "funding_summary",
            "estimated_trl",
            "primary_lifecycle_role",
        ),
        updated_at_column="updated_at",
        source_url_columns=("website",),
        doc_builder=_build_actor_doc,
    ),
    "hub": EntitySpec(
        entity_type="hub",
        table_name="hub",
        id_column="hub_id",
        name_column="name",
        fields=(
            "name",
            "primary_city",
            "state",
            "country",
            "description",
            "official_websites",
            "strategic_value_summary",
            "core_topic_strengths",
            "funding_summary",
        ),
        updated_at_column="updated_at",
        source_url_columns=("official_websites",),
        doc_builder=_build_hub_doc,
    ),
    "person": EntitySpec(
        entity_type="person",
        table_name="person",
        id_column="person_id",
        name_column="full_name",
        fields=(
            "full_name",
            "title",
            "email",
            "orcid",
            "bio",
            "tel_num",
            "country_code",
            "linkedin_url",
        ),
        updated_at_column="updated_at",
        source_url_columns=("linkedin_url",),
        doc_builder=_build_person_doc,
    ),
    "event": EntitySpec(
        entity_type="event",
        table_name="event",
        id_column="event_id",
        name_column="name",
        fields=(
            "name",
            "event_type",
            "description",
            "location",
            "website",
            "thematic_focus",
            "expected_attendance",
            "access_type",
            "recurring_pattern",
            "next_date",
            "sponsoring_orgs",
        ),
        updated_at_column=None,
        verification_status_column=None,
        confidence_column=None,
        source_url_columns=("website",),
        doc_builder=_build_event_doc,
    ),
}


def get_entity_spec(entity_type: str) -> EntitySpec:
    try:
        return ENTITY_SPECS[entity_type]
    except KeyError as exc:
        valid = ", ".join(sorted(ENTITY_SPECS))
        raise ValueError(f"unknown entity {entity_type!r}; valid: {valid}") from exc


def assert_known_fields(spec: EntitySpec, fields: Iterable[str]) -> None:
    unknown = [field for field in fields if field not in spec.fields]
    if unknown:
        raise ValueError(f"{spec.entity_type} fields do not exist: {', '.join(unknown)}")
