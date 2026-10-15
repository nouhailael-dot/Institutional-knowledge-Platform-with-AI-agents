"""Architecture V2 Layer 1 (Light Pull) collection contract.

The Light Pull is deliberately bounded. It materializes a fixed common schema
plus the schema for the actor's already-validated category, is scoped to one
topic, and may fetch at most three pages. Missing evidence is represented as a
collection state; it is never guessed from sector, fame, funder, or age.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

MAX_LIGHT_PULL_FETCHES = 3
RANKING_PUBLISHERS = frozenset({"QS", "THE", "U.S. News", "ARWU"})
RANKING_NAMES = {
    "QS": frozenset({"World University Rankings", "World University Rankings by Subject"}),
    "THE": frozenset({"World University Rankings", "World University Rankings by Subject"}),
    "U.S. News": frozenset({"Best Colleges", "Best Graduate Schools"}),
    "ARWU": frozenset({"Academic Ranking of World Universities"}),
}

COMMON_LIGHT_FIELDS = (
    "official_identity",
    "actor_category_type",
    "parent_connection",
    "website",
    "description",
    "location",
    "hub_assignment",
    "sector_topic",
    "why_matched",
    "recent_activity",
    "funding_signal",
    "international_connection",
    "um6p_ocp_connection",
)

# Stable ledger keys for the Light column of Architecture V2 section 5.2.
CATEGORY_LIGHT_FIELDS: dict[str, tuple[str, ...]] = {
    "university_academic": (
        "topic_unit_and_work", "institution_control", "land_grant_designation",
        "rankings", "relevant_centers_programs",
    ),
    "research_center": (
        "parent_and_center_type", "topic_research_focus", "active_recent_projects",
        "main_funders",
    ),
    "national_laboratory": (
        "sponsoring_agency", "formal_national_designation", "topic_program_area",
    ),
    "applied_facility": (
        "facility_type_operator", "testing_demonstration_scope", "current_project",
    ),
    "hospital_clinical": (
        "clinical_research_focus", "parent_academic_link", "hospital_type_scale",
        "current_initiative",
    ),
    "company": (
        "ownership_and_size", "topic_business_segment_product",
        "mapped_geography_operations",
    ),
    "startup": (
        "technology_and_problem", "founding_year_location", "published_stage_or_trl",
        "funding_stage", "pilot_customer_evidence",
    ),
    "innovation_platform": (
        "platform_type_operator", "sector_focus", "platform_offerings", "scale_indicator",
    ),
    "investor": (
        "investor_type_headquarters", "sector_stage_focus", "geographic_focus",
        "published_fund_size", "topic_investment_thesis",
    ),
    "government": (
        "jurisdiction_parent_agency", "topic_mandate_program", "visible_funding_programs",
    ),
    "foundation_nonprofit": (
        "mission_sector_focus", "geographic_focus", "relevant_program",
        "programs_grant_themes",
    ),
    "association_network": (
        "association_type", "sector_geographic_scope", "member_types",
        "current_initiative_working_group", "linked_members", "network_scope_locations",
    ),
}


@dataclass(frozen=True)
class LightDocument:
    url: str
    text: str
    date_read: datetime
    source_origin: str = "newly_found"


@dataclass(frozen=True)
class LightFact:
    field_key: str
    value: Any
    collection_state: str
    source_url: str
    source_origin: str
    date_read: datetime
    confidence: str


@dataclass(frozen=True)
class LightPullResult:
    actor_category: str
    topic_id: str | None
    schema_fields: tuple[str, ...]
    facts: tuple[LightFact, ...]
    fetched_urls: tuple[str, ...]


LightExtractor = Callable[
    [tuple[LightDocument, ...], tuple[str, ...], str | None], Mapping[str, object]
]


def light_schema(actor_category: str) -> tuple[str, ...]:
    """Return the exact common plus category Light Pull schema."""
    try:
        category_fields = CATEGORY_LIGHT_FIELDS[actor_category]
    except KeyError as exc:
        raise ValueError(f"unknown actor category {actor_category!r}") from exc
    return (*COMMON_LIGHT_FIELDS, *category_fields)


def run_light_pull(
    *,
    payload: Mapping[str, object],
    actor_category: str,
    topic_id: str | None,
    source_url: str,
    date_read: datetime | str,
    fetcher: object | None = None,
    extractor: LightExtractor | None = None,
) -> LightPullResult:
    """Build one topic-scoped Light Pull without broad crawling.

    Discovery may pass ``light_pull_urls`` and an injected robots-aware fetcher,
    but only the first three distinct absolute URLs are read. Normal promotion
    reuses the already-read staged evidence and performs zero extra requests.
    """
    read_at = _datetime(date_read)
    base_url = _absolute_url(source_url, "source_url")
    fields = light_schema(actor_category)
    documents = _documents_from_payload(payload, fallback_date=read_at)
    fetched: list[str] = []
    if fetcher is not None:
        for url in _fetch_urls(payload)[:MAX_LIGHT_PULL_FETCHES]:
            response = _fetch(fetcher, url)
            final_url = _absolute_url(str(getattr(response, "url", None) or url), "fetched URL")
            text = str(getattr(response, "text", response) or "")
            documents.append(LightDocument(final_url, text, read_at))
            fetched.append(final_url)
    extracted: Mapping[str, object] = {}
    if extractor is not None and documents:
        extracted = extractor(tuple(documents), fields, topic_id) or {}
    unknown = sorted(set(extracted).difference(fields))
    if unknown:
        raise ValueError(f"Light Pull returned fields outside its schema: {', '.join(unknown)}")

    defaults = _payload_evidence(payload, actor_category, topic_id)
    # Evidence collected BEFORE review (agents.collection.light_pull_reader,
    # stored on the candidate) fills only what the reviewed record leaves
    # empty: a reviewer's edit always wins over what the agent read. Boxes of
    # another category - the reviewer changed the category - do not apply.
    supplied = payload.get("light_pull_evidence")
    supplied_map = supplied if isinstance(supplied, Mapping) else {}
    merged = {
        key: value for key, value in supplied_map.items()
        if key in fields and (defaults.get(key) is None or key == "um6p_ocp_connection")
    }
    merged.update(dict(extracted))
    facts = tuple(
        _fact(
            field,
            merged.get(field, defaults.get(field)),
            base_url=base_url,
            date_read=read_at,
            actor_category=actor_category,
            category_type=str(payload.get("category_type") or ""),
        )
        for field in fields
    )
    return LightPullResult(
        actor_category=actor_category,
        topic_id=topic_id,
        schema_fields=fields,
        facts=facts,
        fetched_urls=tuple(fetched),
    )


def replace_light_fact(
    result: LightPullResult,
    field_key: str,
    value: object,
    *,
    confidence: str = "high",
) -> LightPullResult:
    """Replace a planned field with deterministic evidence produced later in the pipeline."""
    if field_key not in result.schema_fields:
        raise ValueError(f"field {field_key!r} is not in the Light Pull schema")
    facts = tuple(
        replace(
            fact,
            value=value,
            collection_state="found",
            confidence=confidence,
        ) if fact.field_key == field_key else fact
        for fact in result.facts
    )
    return replace(result, facts=facts)


def _payload_evidence(
    payload: Mapping[str, object], actor_category: str, topic_id: str | None
) -> dict[str, object]:
    """Translate only explicit staged evidence; never infer missing facts."""
    values: dict[str, object] = {}
    names = payload.get("other_names") or payload.get("alt_names") or []
    values["official_identity"] = _found({"name": payload.get("name"), "other_names": names})
    values["actor_category_type"] = _found({
        "actor_category": actor_category,
        "category_type": payload.get("category_type"),
        "category_note": payload.get("category_note"),
    })
    values["website"] = _maybe_found(payload.get("website"))
    values["description"] = _maybe_found(payload.get("description"))
    location = {
        key: payload.get(key) for key in (
            "country", "state", "state_code", "location_city", "city", "region",
            "region_code", "latitude", "longitude", "multi_location",
        ) if payload.get(key) not in (None, "", [], {})
    }
    values["location"] = _maybe_found(location)
    values["parent_connection"] = _maybe_found(
        payload.get("parent_connection") or payload.get("relationships")
    )
    values["hub_assignment"] = _maybe_found(
        payload.get("hub_assignment") or payload.get("hub_distances")
    )
    values["sector_topic"] = _found({
        "sector_codes": list(payload.get("sector_codes") or []), "topic_id": topic_id,
    })
    reason = payload.get("why_matched") or payload.get("match_reason")
    if reason:
        values["why_matched"] = _found({
            "strength": payload.get("match_strength") or "moderate", "reason": reason,
        })
    for field, aliases in {
        "recent_activity": ("recent_activity", "current_activity"),
        "funding_signal": ("funding_signal", "recent_funding_signal"),
        "international_connection": (
            "international_connection", "africa_connection", "morocco_connection",
        ),
        "um6p_ocp_connection": ("um6p_ocp_connection",),
    }.items():
        value = next((payload.get(alias) for alias in aliases
                      if payload.get(alias) not in (None, "", [], {})), None)
        values[field] = _maybe_found(value)
    if values["um6p_ocp_connection"] is None:
        # The controlled entity-list matcher is Phase 13. Until it runs, keep
        # the Architecture V2 check state explicit instead of implying absence.
        values["um6p_ocp_connection"] = _found({"state": "not_yet_checked"})
    for field in CATEGORY_LIGHT_FIELDS[actor_category]:
        values[field] = _maybe_found(payload.get(field))
    return values


def _fact(
    field: str,
    raw: object,
    *,
    base_url: str,
    date_read: datetime,
    actor_category: str,
    category_type: str,
) -> LightFact:
    if isinstance(raw, Mapping) and "collection_state" in raw:
        state = str(raw.get("collection_state") or "").strip()
        value = raw.get("value")
        source_url = _absolute_url(str(raw.get("source_url") or base_url), "fact source_url")
        fact_date = _datetime(raw.get("date_read") or date_read)
        confidence = str(raw.get("confidence") or "medium").strip()
        origin = str(raw.get("source_origin") or "newly_found").strip()
    elif raw is not None:
        state, value, source_url, fact_date, confidence, origin = (
            "found", raw, base_url, date_read, "medium", "newly_found"
        )
    else:
        state, value, source_url, fact_date, confidence, origin = (
            "not_found", None, base_url, date_read, "medium", "newly_found"
        )
    if state not in {"found", "not_found", "not_yet_collected"}:
        raise ValueError(f"invalid collection state for {field}: {state!r}")
    if state == "found" and value in (None, "", [], {}):
        raise ValueError(f"found Light Pull fact {field!r} requires evidence")
    if state != "found" and value is not None:
        raise ValueError(f"non-found Light Pull fact {field!r} must have a null value")
    if confidence not in {"high", "medium", "low"}:
        raise ValueError(f"invalid confidence for {field}: {confidence!r}")
    if origin not in {"imported", "newly_found", "uploaded_document", "ghus_manual"}:
        raise ValueError(f"invalid source origin for {field}: {origin!r}")
    _validate_evidence_rule(field, value, actor_category, category_type, state)
    return LightFact(field, value, state, source_url, origin, fact_date, confidence)


def _validate_evidence_rule(
    field: str, value: object, category: str, category_type: str, state: str
) -> None:
    if state != "found":
        return
    if field == "description" and not 1 <= _sentence_count(str(value)) <= 3:
        raise ValueError("Light Pull description must contain 1 to 3 factual sentences")
    if field == "why_matched":
        if not isinstance(value, Mapping):
            raise ValueError("why_matched must contain strength and reason")
        if value.get("strength") not in {"strong", "moderate"}:
            raise ValueError("why_matched strength must be strong or moderate")
        if not 1 <= _sentence_count(str(value.get("reason") or "")) <= 2:
            raise ValueError("why_matched reason must contain 1 to 2 sentences")
    if field == "recent_activity" and (
        not isinstance(value, Mapping)
        or not value.get("date")
        or not value.get("description")
    ):
        raise ValueError("recent activity requires a date and description")
    if field == "rankings":
        if category != "university_academic":
            raise ValueError("rankings are collected only for university actors")
        rankings = value if isinstance(value, Sequence) and not isinstance(value, str) else [value]
        for ranking in rankings:
            if not isinstance(ranking, Mapping):
                raise TypeError("each ranking must be structured evidence")
            required = {"publisher", "ranking_name", "year", "ranked_entity", "position"}
            if any(ranking.get(key) in (None, "") for key in required):
                raise ValueError("rankings require publisher, name, year, ranked entity, and position")
            if str(ranking["publisher"]) not in RANKING_PUBLISHERS:
                raise ValueError("ranking publisher is not allowed by Architecture V2")
            if str(ranking["ranking_name"]) not in RANKING_NAMES[str(ranking["publisher"])]:
                raise ValueError("ranking name is not allowed for its publisher")
            is_subject = "Subject" in str(ranking["ranking_name"]) or (
                str(ranking["publisher"]) == "U.S. News"
                and str(ranking["ranking_name"]) == "Best Graduate Schools"
            )
            if is_subject and not str(ranking.get("subject") or "").strip():
                raise ValueError("subject ranking requires its published subject or specialty")
            if category_type in {"college_school", "academic_department"} and not is_subject:
                raise ValueError("academic units never inherit a university-wide ranking")
    if field == "published_stage_or_trl":
        if category != "startup":
            raise ValueError("stage or TRL is collected only for startup actors")
        if not isinstance(value, Mapping) or not (
            value.get("stage") is not None or value.get("trl") is not None
        ) or not str(value.get("evidence") or "").strip():
            raise ValueError("startup stage or TRL requires explicit published evidence")


def _documents_from_payload(
    payload: Mapping[str, object], *, fallback_date: datetime
) -> list[LightDocument]:
    raw_documents = payload.get("light_pull_documents")
    if not isinstance(raw_documents, Sequence) or isinstance(raw_documents, (str, bytes)):
        return []
    documents = []
    for raw in raw_documents[:MAX_LIGHT_PULL_FETCHES]:
        if not isinstance(raw, Mapping):
            raise TypeError("light_pull_documents entries must be objects")
        documents.append(LightDocument(
            url=_absolute_url(str(raw.get("url") or ""), "document URL"),
            text=str(raw.get("text") or ""),
            date_read=_datetime(raw.get("date_read") or fallback_date),
            source_origin=str(raw.get("source_origin") or "newly_found"),
        ))
    return documents


def _fetch_urls(payload: Mapping[str, object]) -> list[str]:
    raw = payload.get("light_pull_urls")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    result = []
    for value in raw:
        url = _absolute_url(str(value), "Light Pull URL")
        if url not in result:
            result.append(url)
    return result


def _fetch(fetcher: object, url: str) -> object:
    if callable(fetcher):
        return fetcher(url)
    getter = getattr(fetcher, "get", None)
    if not callable(getter):
        raise TypeError("Light Pull fetcher must be callable or expose get(url)")
    return getter(url)


def _found(value: object) -> dict[str, object]:
    return {"collection_state": "found", "value": value}


def _maybe_found(value: object) -> dict[str, object] | None:
    return _found(value) if value not in (None, "", [], {}) else None


def _absolute_url(value: str, label: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{label} must be an absolute HTTP(S) URL")
    return value.strip()


def _datetime(value: datetime | str | object) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value))
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result


def _sentence_count(value: str) -> int:
    text = " ".join(value.split())
    if not text:
        return 0
    parts = [part for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    return len(parts)
