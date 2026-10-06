"""Verified-only Architecture V2 Layer 2 and explicit Layer 3 collection."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text

from agents.common.facts import ActorFactWrite
from agents.enrichment.decisions import append_actor_fact

DEEP_FIELDS: dict[str, tuple[str, ...]] = {
    "university_academic": ("topic_research_units", "topic_education_programs", "applied_facilities", "funded_projects", "industry_international_collaborations", "commercialization_units", "exchange_programs", "recurring_events", "topic_specific_programs"),
    "research_center": ("research_themes", "recent_projects_outputs", "validation_facilities", "funded_initiatives", "collaborations", "fellowships", "spinouts", "scale", "events"),
    "national_laboratory": ("programs_flagship_projects", "user_facilities", "funded_initiatives", "collaborations", "workforce_training", "technology_transfer", "international_programs"),
    "applied_facility": ("testing_methods", "scale", "deployments_partners", "monitoring_capabilities", "public_events", "funding"),
    "hospital_clinical": ("clinical_programs", "research_programs", "digital_health_ai_units", "medical_education", "partnerships", "funded_initiatives", "global_health_programs"),
    "company": ("relevant_products", "rd_innovation", "industrial_sites", "collaborations", "topic_funding", "public_sustainability_commitments", "corporate_training"),
    "startup": ("technical_approach_maturity", "pilots_deployments", "funding_rounds_investors", "partnerships", "public_ip_when_needed"),
    "innovation_platform": ("programs_cohorts", "linked_supported_startups", "corporate_investor_connections", "facilities_offered", "funding", "events"),
    "investor": ("linked_selected_investments", "university_accelerator_relationships", "programs_run"),
    "government": ("programs_funding_opportunities", "public_initiatives", "operated_facilities", "relevant_policy_context"),
    "foundation_nonprofit": ("selected_grants", "linked_supported_organizations", "international_activity"),
    "association_network": ("working_groups_standards", "recurring_events", "key_reports"),
}


@dataclass(frozen=True)
class DeepPullRequest:
    actor_id: str
    topic_id: str
    actor_category: str
    selected_fields: tuple[str, ...]
    requested_by: str
    request_id: str


@dataclass(frozen=True)
class CollectedValue:
    field_key: str
    value: Any
    collection_state: str
    source_url: str
    source_origin: str
    date_read: datetime
    confidence: str


def validate_deep_request(request: DeepPullRequest) -> DeepPullRequest:
    _uuid(request.actor_id, "actor_id")
    _uuid(request.topic_id, "topic_id")
    _uuid(request.request_id, "request_id")
    if not request.requested_by.strip():
        raise ValueError("Deep Pull requires requested_by for its audit trail")
    try:
        allowed = DEEP_FIELDS[request.actor_category]
    except KeyError as exc:
        raise ValueError("unknown actor category") from exc
    if not request.selected_fields:
        raise ValueError("Deep Pull requires a selected, non-exhaustive field set")
    if len(request.selected_fields) != len(set(request.selected_fields)):
        raise ValueError("Deep Pull fields must be unique")
    unknown = set(request.selected_fields).difference(allowed)
    if unknown:
        raise ValueError(f"fields outside category Deep schema: {', '.join(sorted(unknown))}")
    # A Deep Pull must be selected rather than automatically exhausting the row.
    if len(allowed) > 1 and len(request.selected_fields) >= len(allowed):
        raise ValueError("Deep Pull must be selected and non-exhaustive")
    return request


def actor_is_verified_for_topic(session, *, actor_id: str, topic_id: str) -> bool:
    """Require an explicit GHUS decision for this exact actor/topic pair.

    Actor-level status, including the Phase 12 existing-canonical bootstrap,
    never authorizes Deep Pull for an arbitrary topic.
    """
    has_v2_events = session.execute(
        text("SELECT to_regclass('public.actor_verification_event') IS NOT NULL")
    ).scalar_one()
    if has_v2_events:
        decision = session.execute(
            text(
                "SELECT decision FROM actor_verification_event "
                "WHERE actor_id=CAST(:actor_id AS uuid) "
                "AND topic_id=CAST(:topic_id AS uuid) "
                "AND COALESCE(decision_origin,'ghus_review')='ghus_review' "
                "ORDER BY decided_at DESC NULLS LAST,recorded_at DESC,"
                "actor_verification_event_id DESC LIMIT 1"
            ),
            {"actor_id": actor_id, "topic_id": topic_id},
        ).scalar_one_or_none()
    else:
        decision = session.execute(
            text(
                "SELECT decision FROM record_verification WHERE entity_type='actor' "
                "AND entity_id=CAST(:actor_id AS uuid) "
                "AND topic_id=CAST(:topic_id AS uuid) "
                "ORDER BY decided_at DESC,verification_id DESC LIMIT 1"
            ),
            {"actor_id": actor_id, "topic_id": topic_id},
        ).scalar_one_or_none()
    return decision == "verified"


def append_deep_pull(
    session,
    request: DeepPullRequest,
    values: Mapping[str, CollectedValue],
    *,
    live: bool = False,
) -> list[str]:
    """Append selected Layer 2 facts after the authoritative verification gate."""
    request = validate_deep_request(request)
    if set(values) != set(request.selected_fields):
        raise ValueError("Deep Pull values must exactly match selected_fields")
    if not actor_is_verified_for_topic(
        session, actor_id=request.actor_id, topic_id=request.topic_id
    ):
        raise PermissionError("Deep Pull requires the latest GHUS decision to be verified")
    return [
        append_actor_fact(
            session,
            ActorFactWrite(
                actor_id=request.actor_id,
                topic_id=request.topic_id,
                field_key=field,
                fact_type="deep_pull",
                layer=2,
                value=values[field].value,
                collection_state=values[field].collection_state,
                source_url=values[field].source_url,
                source_origin=values[field].source_origin,
                date_read=values[field].date_read,
                confidence=values[field].confidence,
                created_by=request.requested_by,
                request_id=request.request_id,
            ),
            live=live,
        )
        for field in request.selected_fields
    ]


def append_specific_ask(
    session,
    *,
    actor_id: str,
    topic_id: str,
    requested_by: str,
    request_text: str,
    request_id: str,
    values: Sequence[CollectedValue],
    live: bool = False,
) -> list[str]:
    """Append Layer 3 facts only from an explicit, auditable GHUS request."""
    if not requested_by.strip() or not request_text.strip():
        raise ValueError("Layer 3 requires an explicit requester and request text")
    if not values:
        raise ValueError("Layer 3 requires explicitly requested values")
    return [
        append_actor_fact(
            session,
            ActorFactWrite(
                actor_id=actor_id, topic_id=topic_id, field_key=value.field_key,
                fact_type="specific_ask", layer=3, value={
                    "request": request_text, "result": value.value,
                } if value.collection_state == "found" else None,
                collection_state=value.collection_state, source_url=value.source_url,
                source_origin=value.source_origin, date_read=value.date_read,
                confidence=value.confidence, created_by=requested_by, request_id=request_id,
            ),
            live=live,
        )
        for value in values
    ]


def map_linked_subentities(
    candidates: Sequence[Mapping[str, object]],
    *,
    parent_actor_id: str,
    mapper: Callable[[dict[str, object]], object],
    maximum: int = 5,
) -> list[object]:
    """Route selected sub-entities through map_new_actor-compatible inputs."""
    if len(candidates) > maximum:
        raise ValueError("linked sub-entity cap exceeded")
    results = []
    for candidate in candidates:
        payload = dict(candidate)
        payload["parent_connection"] = {
            "relationship_type": str(payload.pop("parent_relationship", "unit_of")),
            "actor_id": parent_actor_id,
            "confidence": str(payload.pop("relationship_confidence", "high")),
        }
        results.append(mapper(payload))
    return results


def _uuid(value: str, label: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"{label} must be a UUID") from exc
