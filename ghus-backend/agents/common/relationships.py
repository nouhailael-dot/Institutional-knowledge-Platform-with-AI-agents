"""Architecture V2 typed relationship contract.

This module is deliberately storage-free.  It validates the exact endpoint
pairs used by the database proposal and turns explicit actor payload evidence
into edge requests.  Absence of a request means a complete standalone actor;
no parent is ever inferred from names, domains, hubs, sectors, or location.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

FAMILY_RELATIONSHIP_TYPES = frozenset({"unit_of", "operated_by"})

RELATIONSHIP_ENDPOINTS: dict[str, frozenset[tuple[str, str]]] = {
    "unit_of": frozenset({("actor", "actor")}),
    "operated_by": frozenset({("actor", "actor")}),
    "affiliated_with": frozenset({("person", "actor")}),
    "member_of": frozenset({("actor", "actor")}),
    "portfolio_of": frozenset({("actor", "actor")}),
    "spinout_of": frozenset({("actor", "actor")}),
    "funded_by": frozenset({("actor", "actor")}),
    "collaborates_with": frozenset({("actor", "actor")}),
    "organizes": frozenset({("actor", "event")}),
    "participates_in": frozenset({("actor", "event"), ("person", "event")}),
    "connected_to_um6p_ocp": frozenset({
        ("actor", "strategic_entity"),
        ("person", "strategic_entity"),
        ("event", "strategic_entity"),
    }),
}


@dataclass(frozen=True)
class EntityEdgeRequest:
    subject_type: str
    subject_id: str
    relationship_type: str
    object_type: str
    object_id: str
    source_id: str
    topic_id: str | None = None
    confidence: str = "high"


def _uuid(value: Any, field: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{field} must be a UUID") from exc


def validate_entity_edge(request: EntityEdgeRequest) -> EntityEdgeRequest:
    endpoints = RELATIONSHIP_ENDPOINTS.get(request.relationship_type)
    if endpoints is None:
        raise ValueError(f"unsupported relationship_type {request.relationship_type!r}")
    pair = (request.subject_type, request.object_type)
    if pair not in endpoints:
        raise ValueError(
            f"{request.relationship_type} does not allow "
            f"{request.subject_type}->{request.object_type}"
        )
    if request.confidence not in {"high", "medium", "low"}:
        raise ValueError("edge confidence must be high, medium, or low")
    subject_id = _uuid(request.subject_id, "subject_id")
    object_id = _uuid(request.object_id, "object_id")
    if request.subject_type == request.object_type and subject_id == object_id:
        raise ValueError("an entity cannot have a relationship to itself")
    return EntityEdgeRequest(
        subject_type=request.subject_type,
        subject_id=subject_id,
        relationship_type=request.relationship_type,
        object_type=request.object_type,
        object_id=object_id,
        source_id=_uuid(request.source_id, "source_id"),
        topic_id=_uuid(request.topic_id, "topic_id") if request.topic_id else None,
        confidence=request.confidence,
    )


def actor_relationship_requests(
    *,
    actor_id: str,
    payload: dict[str, Any],
    source_id: str,
    topic_id: str | None,
) -> tuple[EntityEdgeRequest, ...]:
    """Return only explicitly supplied outgoing relationships for a new actor."""
    raw: list[dict[str, Any]] = []
    parent = payload.get("parent_connection")
    if parent is not None:
        if not isinstance(parent, dict):
            raise ValueError("parent_connection must be an object")
        relationship = str(parent.get("relationship_type") or "")
        if relationship not in {"unit_of", "operated_by"}:
            raise ValueError("parent_connection must use unit_of or operated_by")
        raw.append({
            "relationship_type": relationship,
            "object_type": "actor",
            "object_id": parent.get("actor_id") or parent.get("object_id"),
            "confidence": parent.get("confidence", "high"),
        })
    relationships = payload.get("relationships") or []
    if not isinstance(relationships, list):
        raise TypeError("relationships must be a list")
    if not all(isinstance(item, dict) for item in relationships):
        raise ValueError("every relationship must be an object")
    raw.extend(relationships)

    requests = []
    for item in raw:
        requests.append(validate_entity_edge(EntityEdgeRequest(
            subject_type="actor",
            subject_id=actor_id,
            relationship_type=str(item.get("relationship_type") or ""),
            object_type=str(item.get("object_type") or "actor"),
            object_id=str(item.get("object_id") or ""),
            source_id=source_id,
            topic_id=topic_id,
            confidence=str(item.get("confidence") or "high"),
        )))
    return tuple(requests)


def network_location_requests(
    *, parent_actor_id: str, location_actor_ids: Iterable[str], source_id: str,
    topic_id: str | None = None,
) -> tuple[EntityEdgeRequest, ...]:
    """Link physical location actors under one network parent without copying reach."""
    return tuple(
        validate_entity_edge(EntityEdgeRequest(
            subject_type="actor",
            subject_id=location_id,
            relationship_type="unit_of",
            object_type="actor",
            object_id=parent_actor_id,
            source_id=source_id,
            topic_id=topic_id,
            confidence="high",
        ))
        for location_id in dict.fromkeys(str(value) for value in location_actor_ids)
    )
