"""Canonical promotion path for agent-staged records.

This module is intentionally one of the only agents modules that inserts or
updates canonical entity tables. The Phase 1 slice supports event
create/absorb/review. Event review rows use an agent-owned queue because the
existing review_queue table is actor-specific.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlparse

from sqlalchemy import text

from agents.common.provenance import insert_source
from agents.common.resolve_route import RouteDecision
from agents.discovery.stage import StagedRecord
from src.ML.entity_resolution.resolve_or_create import INHERITABLE_FIELDS as ACTOR_FIELDS

EVENT_CREATE_FIELDS = [
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
]

EVENT_ABSORB_FIELDS = EVENT_CREATE_FIELDS.copy()
DISCOVERED_DOMAIN_PAYLOAD_KEY = "_discovered_domain"
ACTOR_CREATE_FIELDS = [*ACTOR_FIELDS, "funding_summary"]
ACTOR_ABSORB_FIELDS = list(ACTOR_FIELDS)
ACTOR_ABSORB_CONNECTOR_RE = re.compile(
    r"\b(?:in collaboration with|in partnership with|in cooperation with|"
    r"in association with|together with|co-hosted by|hosted by|supported by|"
    r"with support from|and)\b",
    flags=re.IGNORECASE,
)
ACTOR_ROLE_PREFIX_RE = re.compile(
    r"^\s*(?:(?:executive\s+)?office|permanent mission|president|chair|co-chair|"
    r"minister|secretary-general|director|dean|"
    r"professor|representative|ambassador|mayor|governor|prime minister|head)\s+"
    r"(?:of|for|to)\b",
    flags=re.IGNORECASE,
)
ACTOR_LIST_DELIMITER_RE = re.compile(r"\s*(?:;|,|\band\b)\s*", flags=re.IGNORECASE)
ACTOR_ORG_MARKERS = {
    "academy",
    "agency",
    "alliance",
    "association",
    "bank",
    "center",
    "centre",
    "coalition",
    "commission",
    "committee",
    "compact",
    "council",
    "department",
    "foundation",
    "fund",
    "group",
    "institute",
    "initiative",
    "lab",
    "labs",
    "ministry",
    "network",
    "nations",
    "organization",
    "organisation",
    "programme",
    "program",
    "project",
    "university",
    "union",
}
ACTOR_LIST_SUFFIXES = {
    "corp",
    "corp.",
    "gmbh",
    "inc",
    "inc.",
    "llc",
    "ltd",
    "ltd.",
    "plc",
    "s.a.",
    "sarl",
}


@dataclass
class PromotionResult:
    action: str
    entity_type: str
    zone: str
    entity_id: str | None = None
    dry_run: bool = True
    fields_absorbed: list[str] = field(default_factory=list)
    review_id: str | None = None


def guard_actor_absorb_route(staged: StagedRecord, route: RouteDecision) -> RouteDecision:
    if staged.entity_type != "actor" or route.zone != "absorb":
        return route
    reason = _unsafe_actor_absorb_reason(staged.normalized_payload.get("name"))
    if not reason:
        return route
    if not route.target_entity_id:
        raise ValueError("actor absorb route requires target_entity_id")
    metadata = dict(route.metadata or {})
    metadata["actor_absorb_guard_reason"] = reason
    return RouteDecision(
        zone="review",
        score=route.score,
        target_entity_id=route.target_entity_id,
        candidate_ids=route.candidate_ids,
        metadata=metadata,
    )


def guard_discovered_domain_route(
    staged: StagedRecord, route: RouteDecision
) -> RouteDecision:
    domain = str(staged.normalized_payload.get(DISCOVERED_DOMAIN_PAYLOAD_KEY) or "").strip()
    if not domain:
        return route
    if route.zone == "absorb":
        raise RuntimeError(
            "records from discovered domains must not use the absorb route; "
            f"domain={domain!r}"
        )
    if route.zone not in {"create", "review", "skip"}:
        raise RuntimeError(
            "records from discovered domains may route only to create, review, or skip; "
            f"got {route.zone!r}"
        )
    return route


def promote(
    staged: StagedRecord,
    route: RouteDecision,
    session=None,
    *,
    live: bool = False,
    person_create_preview: bool = False,
    people_enabled: bool = False,
    manage_transaction: bool = True,
) -> PromotionResult:
    if staged.sector_match == "out_of_sector":
        raise RuntimeError("out_of_sector staged records must not be promoted")
    route = guard_discovered_domain_route(staged, route)
    if staged.entity_type == "actor":
        return _promote_actor(
            staged,
            route,
            session=session,
            live=live,
            manage_transaction=manage_transaction,
        )
    if staged.entity_type == "person":
        if not people_enabled:
            raise RuntimeError(
                "person promotion is disabled pending TARGETING_POLICY.md section 6 approval"
            )
        return _promote_person(
            staged,
            route,
            session=session,
            live=live,
            create_preview=person_create_preview,
            manage_transaction=manage_transaction,
        )
    if staged.entity_type != "event":
        raise NotImplementedError(
            "promotion supports only entity_type='event', entity_type='actor', "
            "or entity_type='person'"
        )

    if session is None:
        if live:
            raise ValueError("live promotion requires a database session")
        return _dry_run_preview(staged, route)

    transaction = session.begin() if manage_transaction else None
    try:
        if route.zone == "create":
            source_id = insert_source(
                session,
                source_url=staged.source_url,
                fetched_at=staged.extracted_at,
                description="agent discovery event create",
            )
            event_id = _insert_event(session, staged.normalized_payload, source_id)
            _mark_index_dirty(session, entity_type="event", entity_id=event_id)
            result = PromotionResult(
                action="created",
                entity_type="event",
                zone="create",
                entity_id=event_id,
                dry_run=False,
            )
        elif route.zone == "absorb":
            if not route.target_entity_id:
                raise ValueError("absorb route requires target_entity_id")
            fields = _absorb_event_fields(session, route.target_entity_id, staged)
            if fields:
                _mark_index_dirty(session, entity_type="event", entity_id=route.target_entity_id)
            result = PromotionResult(
                action="absorbed" if fields else "no_op",
                entity_type="event",
                zone="absorb",
                entity_id=route.target_entity_id,
                dry_run=False,
                fields_absorbed=fields,
            )
        elif route.zone == "review":
            review_kind = str(dict(route.metadata or {}).get("review_kind") or "fuzzy_match")
            if review_kind != "rubric_band" and not route.target_entity_id:
                raise ValueError("event review route requires target_entity_id")
            review_id = _insert_event_review(session, staged, route)
            result = PromotionResult(
                action="queued_for_review",
                entity_type="event",
                zone="review",
                entity_id=route.target_entity_id,
                dry_run=False,
                review_id=review_id,
            )
        else:
            raise ValueError(f"unknown route zone {route.zone!r}")
    except Exception:
        if transaction is not None:
            transaction.rollback()
        raise

    if live and transaction is not None:
        transaction.commit()
        return result
    if live:
        return result
    if transaction is not None:
        transaction.rollback()
    return _dry_run_result(result, route)


def _dry_run_preview(staged: StagedRecord, route: RouteDecision) -> PromotionResult:
    return PromotionResult(
        action=f"would_{route.zone}",
        entity_type=staged.entity_type,
        zone=route.zone,
        entity_id=route.target_entity_id,
        dry_run=True,
    )


def _dry_run_result(result: PromotionResult, route: RouteDecision) -> PromotionResult:
    result.action = f"would_{route.zone}"
    result.dry_run = True
    return result


def _insert_event(session, payload: dict[str, object], source_id: str) -> str:
    name = payload.get("name") or payload.get("title")
    if not name:
        raise ValueError("cannot create event without name")
    event_id = str(uuid.uuid4())
    cols: dict[str, object] = {"event_id": event_id, "name": name, "source_id": source_id}
    for field_name in EVENT_CREATE_FIELDS:
        value = payload.get(field_name)
        if _has_value(value):
            cols[field_name] = value
    names = ", ".join(cols)
    binds = ", ".join(
        f"CAST(:{name} AS uuid)" if name in {"event_id", "source_id"} else f":{name}"
        for name in cols
    )
    session.execute(text(f"INSERT INTO event ({names}) VALUES ({binds})"), cols)
    return event_id


def _absorb_event_fields(session, event_id: str, staged: StagedRecord) -> list[str]:
    row = (
        session.execute(
            text(
                "SELECT event_type, description, location, website, thematic_focus, "
                "expected_attendance, access_type, recurring_pattern, next_date, "
                "sponsoring_orgs, source_id FROM event WHERE event_id = CAST(:event_id AS uuid)"
            ),
            {"event_id": event_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise RuntimeError(f"event {event_id} no longer exists")

    updates: dict[str, object] = {}
    for field_name in EVENT_ABSORB_FIELDS:
        incoming = staged.normalized_payload.get(field_name)
        if _is_empty(row.get(field_name)) and _has_value(incoming):
            updates[field_name] = incoming
    if not updates:
        return []

    source_id = insert_source(
        session,
        source_url=staged.source_url,
        fetched_at=staged.extracted_at,
        description="agent discovery event absorb",
    )
    if _is_empty(row.get("source_id")):
        updates["source_id"] = source_id
    updates["event_id"] = event_id
    set_clause = ", ".join(
        f"{field_name} = :{field_name}" for field_name in updates if field_name != "event_id"
    )
    session.execute(
        text(f"UPDATE event SET {set_clause} WHERE event_id = CAST(:event_id AS uuid)"), updates
    )
    return [field_name for field_name in updates if field_name not in {"event_id", "source_id"}]


def _mark_index_dirty(session, *, entity_type: str, entity_id: str) -> None:
    session.execute(
        text(
            "INSERT INTO index_dirty (entity_type, entity_id, marked_at) "
            "VALUES (:entity_type, CAST(:entity_id AS uuid), CURRENT_TIMESTAMP) "
            "ON CONFLICT (entity_type, entity_id) DO UPDATE SET "
            "marked_at = EXCLUDED.marked_at"
        ),
        {"entity_type": entity_type, "entity_id": entity_id},
    )


def _insert_event_review(session, staged: StagedRecord, route: RouteDecision) -> str:
    metadata = dict(route.metadata or {})
    if metadata.get("review_kind") == "rubric_band":
        return _insert_event_rubric_review(session, staged, route, metadata)
    staged_title = str(metadata.get("staged_title") or staged.normalized_payload.get("name") or "")
    candidate_title = str(metadata.get("candidate_title") or "")
    shared_start_date = (
        metadata.get("shared_start_date")
        or staged.normalized_payload.get("start_date")
        or staged.normalized_payload.get("next_date")
    )
    if not candidate_title:
        raise ValueError("event review route metadata must include candidate_title")
    if not shared_start_date:
        raise ValueError("event review route metadata must include shared_start_date")

    event_review_id = str(uuid.uuid4())
    session.execute(
        text(
            "INSERT INTO event_review_queue (event_review_id, staged_record_id, candidate_event_id, "
            "similarity_score, staged_title, candidate_title, shared_start_date, status, reviewer) "
            "VALUES (CAST(:event_review_id AS uuid), CAST(:staged_record_id AS uuid), "
            "CAST(:candidate_event_id AS uuid), :similarity_score, :staged_title, :candidate_title, "
            "CAST(:shared_start_date AS date), 'pending', NULL) "
            "ON CONFLICT (staged_record_id, candidate_event_id) DO UPDATE SET "
            "similarity_score = EXCLUDED.similarity_score, staged_title = EXCLUDED.staged_title, "
            "candidate_title = EXCLUDED.candidate_title, shared_start_date = EXCLUDED.shared_start_date, "
            "updated_at = now()"
        ),
        {
            "event_review_id": event_review_id,
            "staged_record_id": staged.staged_record_id,
            "candidate_event_id": route.target_entity_id,
            "similarity_score": route.score,
            "staged_title": staged_title,
            "candidate_title": candidate_title,
            "shared_start_date": shared_start_date,
        },
    )
    return event_review_id


def _insert_event_rubric_review(
    session,
    staged: StagedRecord,
    route: RouteDecision,
    metadata: dict[str, object],
) -> str:
    staged_title = str(
        metadata.get("staged_title") or staged.normalized_payload.get("name") or ""
    ).strip()
    if not staged_title:
        raise ValueError("event rubric review requires a staged title")
    rubric = metadata.get("rubric")
    if not isinstance(rubric, dict):
        raise TypeError("event rubric review requires rubric evidence")
    event_review_id = str(uuid.uuid4())
    session.execute(
        text(
            "INSERT INTO event_review_queue (event_review_id, staged_record_id, "
            "candidate_event_id, similarity_score, staged_title, candidate_title, "
            "shared_start_date, status, reviewer, review_kind, search_candidate_id, rubric, "
            "score_breakdown, qualification_paths, rerank_position, rerank_reason) "
            "VALUES (CAST(:event_review_id AS uuid), CAST(:staged_record_id AS uuid), "
            "CAST(:candidate_event_id AS uuid), :similarity_score, :staged_title, "
            ":candidate_title, CAST(:shared_start_date AS date), 'pending', NULL, "
            "'rubric_band', CAST(:search_candidate_id AS uuid), CAST(:rubric AS jsonb), "
            "CAST(:score_breakdown AS jsonb), CAST(:qualification_paths AS jsonb), "
            ":rerank_position, :rerank_reason)"
        ),
        {
            "event_review_id": event_review_id,
            "staged_record_id": staged.staged_record_id,
            "candidate_event_id": route.target_entity_id,
            "similarity_score": route.score,
            "staged_title": staged_title,
            "candidate_title": metadata.get("candidate_title"),
            "shared_start_date": metadata.get("shared_start_date"),
            "search_candidate_id": metadata.get("search_candidate_id"),
            "rubric": json.dumps(rubric, sort_keys=True),
            "score_breakdown": json.dumps(
                metadata.get("score_breakdown") or {}, sort_keys=True
            ),
            "qualification_paths": json.dumps(
                metadata.get("qualification_paths") or [], sort_keys=True
            ),
            "rerank_position": metadata.get("rerank_position"),
            "rerank_reason": metadata.get("rerank_reason"),
        },
    )
    return event_review_id


def _promote_actor(
    staged: StagedRecord,
    route: RouteDecision,
    session=None,
    *,
    live: bool = False,
    manage_transaction: bool = True,
) -> PromotionResult:
    route = guard_actor_absorb_route(staged, route)
    if session is None:
        if live:
            raise ValueError("live promotion requires a database session")
        return _dry_run_preview(staged, route)

    transaction = session.begin() if manage_transaction else None
    try:
        if route.zone == "create":
            source_id = insert_source(
                session,
                source_url=staged.source_url,
                fetched_at=staged.extracted_at,
                description="agent discovery actor create",
            )
            actor_id = _insert_actor(session, staged.normalized_payload, source_id)
            _assign_actor_hubs(session, actor_id, route.metadata.get("hub_ids") or [])
            _mark_index_dirty(session, entity_type="actor", entity_id=actor_id)
            result = PromotionResult(
                action="created",
                entity_type="actor",
                zone="create",
                entity_id=actor_id,
                dry_run=False,
            )
        elif route.zone == "absorb":
            if not route.target_entity_id:
                raise ValueError("actor absorb route requires target_entity_id")
            fields = _absorb_actor_fields(session, route.target_entity_id, staged)
            _assign_actor_hubs(
                session, route.target_entity_id, route.metadata.get("hub_ids") or []
            )
            if fields:
                _mark_index_dirty(session, entity_type="actor", entity_id=route.target_entity_id)
            result = PromotionResult(
                action="absorbed" if fields else "no_op",
                entity_type="actor",
                zone="absorb",
                entity_id=route.target_entity_id,
                dry_run=False,
                fields_absorbed=fields,
            )
        elif route.zone == "review":
            if not route.target_entity_id:
                raise ValueError("actor review route requires target_entity_id")
            source_id = insert_source(
                session,
                source_url=staged.source_url,
                fetched_at=staged.extracted_at,
                description="agent discovery actor review candidate",
            )
            actor_id = _insert_actor(session, staged.normalized_payload, source_id)
            review_id = _insert_actor_review(session, actor_id, route.target_entity_id, route)
            _mark_index_dirty(session, entity_type="actor", entity_id=actor_id)
            result = PromotionResult(
                action="queued_for_review",
                entity_type="actor",
                zone="review",
                entity_id=actor_id,
                dry_run=False,
            )
            result.review_id = review_id
        else:
            raise ValueError(f"unknown route zone {route.zone!r}")
    except Exception:
        if transaction is not None:
            transaction.rollback()
        raise

    if live and transaction is not None:
        transaction.commit()
        return result
    if live:
        return result
    if transaction is not None:
        transaction.rollback()
    return _dry_run_result(result, route)


def _insert_actor(session, payload: dict[str, object], source_id: str) -> str:
    name = payload.get("name")
    if not name:
        raise ValueError("cannot create actor without name")
    actor_id = str(uuid.uuid4())
    cols: dict[str, object] = {
        "actor_id": actor_id,
        "name": name,
        "slug": _actor_slug(str(name), actor_id),
        "verification_status": "needs_review",
        "source_id": source_id,
    }
    for field_name in ACTOR_CREATE_FIELDS:
        value = payload.get(field_name)
        if _has_value(value):
            cols[field_name] = value
    names = ", ".join(cols)
    binds = ", ".join(
        f"CAST(:{name} AS uuid)" if name in {"actor_id", "source_id"} else f":{name}"
        for name in cols
    )
    session.execute(text(f"INSERT INTO actor ({names}) VALUES ({binds})"), cols)
    return actor_id


def _assign_actor_hubs(session, actor_id: str, hub_ids: object) -> None:
    """Attach reviewer-selected hubs while keeping canonical writes in this module."""
    if not isinstance(hub_ids, (list, tuple, set)):
        raise ValueError("hub_ids must be a list")
    for hub_id in dict.fromkeys(str(value).strip() for value in hub_ids):
        if not hub_id:
            continue
        exists = session.execute(
            text("SELECT 1 FROM hub WHERE hub_id = CAST(:hub_id AS uuid)"),
            {"hub_id": hub_id},
        ).scalar_one_or_none()
        if exists is None:
            raise ValueError(f"unknown hub_id {hub_id}")
        session.execute(
            text(
                "INSERT INTO hub_actor (hub_id, actor_id, relationship_type, is_primary) "
                "VALUES (CAST(:hub_id AS uuid), CAST(:actor_id AS uuid), "
                "'reviewed_assignment', FALSE) "
                "ON CONFLICT (hub_id, actor_id) DO NOTHING"
            ),
            {"hub_id": hub_id, "actor_id": actor_id},
        )


def _absorb_actor_fields(session, actor_id: str, staged: StagedRecord) -> list[str]:
    selected_fields = [*ACTOR_ABSORB_FIELDS, "source_id", "verification_status"]
    row = (
        session.execute(
            text(
                "SELECT "
                + ", ".join(selected_fields)
                + " FROM actor WHERE actor_id = CAST(:actor_id AS uuid)"
            ),
            {"actor_id": actor_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise RuntimeError(f"actor {actor_id} no longer exists")

    updates: dict[str, object] = {}
    gap_conditions: list[str] = []
    for field_name in ACTOR_ABSORB_FIELDS:
        incoming = staged.normalized_payload.get(field_name)
        if _is_empty(row.get(field_name)) and _has_value(incoming):
            updates[field_name] = incoming
            gap_conditions.append(_gap_sql(field_name))
    if not updates:
        return []

    source_id = insert_source(
        session,
        source_url=staged.source_url,
        fetched_at=staged.extracted_at,
        description="agent discovery actor absorb",
    )
    if _is_empty(row.get("source_id")):
        updates["source_id"] = source_id
        gap_conditions.append("source_id IS NULL")
    updates["verification_status"] = "needs_review"
    updates["actor_id"] = actor_id
    set_clause = ", ".join(
        f"{field_name} = :{field_name}" for field_name in updates if field_name != "actor_id"
    )
    where_clause = " AND ".join(gap_conditions)
    result = session.execute(
        text(
            f"UPDATE actor SET {set_clause}, updated_at = now() "
            f"WHERE actor_id = CAST(:actor_id AS uuid) AND {where_clause}"
        ),
        updates,
    )
    if result.rowcount != 1:
        raise RuntimeError("actor absorb gap guard matched zero rows")
    return [
        field_name
        for field_name in updates
        if field_name not in {"actor_id", "source_id", "verification_status"}
    ]


def _insert_actor_review(session, actor_id_a: str, actor_id_b: str, route: RouteDecision) -> str:
    left, right = sorted([str(actor_id_a), str(actor_id_b)])
    review_id = str(uuid.uuid4())
    session.execute(
        text(
            "INSERT INTO review_queue (review_id, actor_id_a, actor_id_b, score, model, status) "
            "VALUES (CAST(:review_id AS uuid), CAST(:actor_id_a AS uuid), "
            "CAST(:actor_id_b AS uuid), :score, :model, 'pending') "
            "ON CONFLICT ON CONSTRAINT uq_review_pair DO NOTHING"
        ),
        {
            "review_id": review_id,
            "actor_id_a": left,
            "actor_id_b": right,
            "score": float(route.score),
            "model": str(route.metadata.get("model") or "combiner"),
        },
    )
    return review_id


def _promote_person(
    staged: StagedRecord,
    route: RouteDecision,
    session=None,
    *,
    live: bool = False,
    create_preview: bool = False,
    manage_transaction: bool = True,
) -> PromotionResult:
    metadata = dict(route.metadata or {})
    if route.zone == "skip":
        if (
            route.target_entity_id is None
            or metadata.get("identity_outcome") != "already_held"
            or metadata.get("clean_identity_key") is not True
        ):
            raise RuntimeError(
                "person skip requires an already-held clean deterministic identity"
            )
        return PromotionResult(
            action="already_held",
            entity_type="person",
            zone="skip",
            entity_id=route.target_entity_id,
            dry_run=True,
        )
    if route.zone == "create":
        if live and create_preview:
            raise RuntimeError("person create preview cannot be used with live writes")
        _guard_person_create(staged, route)
    if route.zone not in {"create", "review", "link_existing"}:
        raise RuntimeError(f"unknown person route zone {route.zone!r}")
    if session is None:
        if live:
            raise ValueError("live promotion requires a database session")
        return _dry_run_preview(staged, route)

    transaction = session.begin() if manage_transaction else None
    try:
        if route.zone == "create":
            source_id = insert_source(
                session,
                source_url=staged.source_url,
                fetched_at=staged.extracted_at,
                description="agent discovery person create",
            )
            actor_id = str(metadata.get("affiliation_actor_id") or "").strip()
            created_affiliation_stub = metadata.get("create_affiliation_stub") is True
            if created_affiliation_stub:
                actor_id = _insert_actor(
                    session,
                    {"name": str(metadata["affiliation_stub_name"]).strip()},
                    source_id,
                )
                _mark_index_dirty(session, entity_type="actor", entity_id=actor_id)
            person_id = _insert_person(
                session,
                staged.normalized_payload,
                source_id,
                confidence=float(route.score),
            )
            role = str(staged.normalized_payload["role"]).strip()
            _insert_person_affiliation(
                session,
                person_id=person_id,
                actor_id=actor_id,
                role=role,
            )
            _insert_person_discovery_profile(
                session,
                staged=staged,
                person_id=person_id,
                actor_id=actor_id,
                source_id=source_id,
                needs_actor_enrichment=created_affiliation_stub,
            )
            _mark_index_dirty(session, entity_type="person", entity_id=person_id)
            result = PromotionResult(
                action="created",
                entity_type="person",
                zone="create",
                entity_id=person_id,
                dry_run=False,
            )
        elif route.zone == "review":
            source_id = insert_source(
                session,
                source_url=staged.source_url,
                fetched_at=staged.extracted_at,
                description="agent discovery person review",
            )
            review_id = _insert_person_review(session, staged, route, source_id)
            result = PromotionResult(
                action="queued_for_review",
                entity_type="person",
                zone="review",
                entity_id=route.target_entity_id,
                dry_run=False,
                review_id=review_id,
            )
        else:
            result = _link_existing_person(session, staged, route)
    except Exception:
        if transaction is not None:
            transaction.rollback()
        raise

    if live and transaction is not None:
        transaction.commit()
        return result
    if live:
        return result
    if transaction is not None:
        transaction.rollback()
    return _dry_run_result(result, route)


def _link_existing_person(
    session, staged: StagedRecord, route: RouteDecision
) -> PromotionResult:
    """Link a reviewed person to a resolved institution and log affiliation changes."""
    if not route.target_entity_id:
        raise ValueError("person link_existing route requires target_entity_id")
    metadata = dict(route.metadata or {})
    actor_id = str(metadata.get("affiliation_actor_id") or "").strip()
    source_id = insert_source(
        session,
        source_url=staged.source_url,
        fetched_at=staged.extracted_at,
        description="human-reviewed person affiliation",
    )
    if metadata.get("create_affiliation_stub") is True:
        actor_id = _insert_actor(
            session,
            {"name": str(metadata.get("affiliation_stub_name") or "").strip()},
            source_id,
        )
        _mark_index_dirty(session, entity_type="actor", entity_id=actor_id)
    if not actor_id:
        raise ValueError("person link_existing route requires an affiliation actor")
    role = str(staged.normalized_payload.get("role") or "").strip()
    if not role or len(role) > 120:
        raise ValueError("person role is required and must not exceed 120 characters")
    current = (
        session.execute(
            text(
                "SELECT ap.actor_id::text AS actor_id, a.name AS affiliation, ap.role "
                "FROM actor_person ap JOIN actor a ON a.actor_id = ap.actor_id "
                "WHERE ap.person_id = CAST(:person_id AS uuid) "
                "AND ap.is_current IS NOT FALSE "
                "ORDER BY ap.start_date DESC NULLS LAST LIMIT 1"
            ),
            {"person_id": route.target_entity_id},
        ).mappings().first()
    )
    if (
        current
        and str(current["actor_id"]) == actor_id
        and str(current.get("role") or "") == role
    ):
        return PromotionResult(
            action="no_op",
            entity_type="person",
            zone="link_existing",
            entity_id=route.target_entity_id,
            dry_run=False,
        )
    if current:
        session.execute(
            text(
                "UPDATE actor_person SET is_current = FALSE, "
                "end_date = CAST(:changed_at AS date) "
                "WHERE person_id = CAST(:person_id AS uuid) "
                "AND actor_id = CAST(:actor_id AS uuid) AND is_current IS NOT FALSE"
            ),
            {
                "person_id": route.target_entity_id,
                "actor_id": current["actor_id"],
                "changed_at": staged.extracted_at,
            },
        )
    session.execute(
        text(
            "INSERT INTO actor_person (actor_id, person_id, role, is_current, start_date) "
            "VALUES (CAST(:actor_id AS uuid), CAST(:person_id AS uuid), :role, TRUE, "
            "CAST(:changed_at AS date)) ON CONFLICT (actor_id, person_id, role) "
            "DO UPDATE SET is_current = TRUE, end_date = NULL"
        ),
        {
            "actor_id": actor_id,
            "person_id": route.target_entity_id,
            "role": role,
            "changed_at": staged.extracted_at,
        },
    )
    if current and str(current["actor_id"]) != actor_id:
        session.execute(
            text(
                "INSERT INTO person_change_log (person_change_id, person_id, field_name, "
                "previous_value, new_value, source_url, changed_at) VALUES "
                "(CAST(:change_id AS uuid), CAST(:person_id AS uuid), 'affiliation', "
                ":previous_value, :new_value, :source_url, "
                "CAST(:changed_at AS timestamptz))"
            ),
            {
                "change_id": str(uuid.uuid4()),
                "person_id": route.target_entity_id,
                "previous_value": str(current.get("affiliation") or ""),
                "new_value": str(staged.normalized_payload.get("affiliation") or ""),
                "source_url": staged.source_url,
                "changed_at": staged.extracted_at,
            },
        )
    _mark_index_dirty(session, entity_type="person", entity_id=route.target_entity_id)
    return PromotionResult(
        action="linked_existing",
        entity_type="person",
        zone="link_existing",
        entity_id=route.target_entity_id,
        dry_run=False,
    )


def _guard_person_create(staged: StagedRecord, route: RouteDecision) -> None:
    metadata = dict(route.metadata or {})
    payload = staged.normalized_payload
    failures: list[str] = []
    if metadata.get("score_band") != "auto_high":
        failures.append("score_band must be auto_high")
    if metadata.get("identity_outcome") != "create":
        failures.append("identity_outcome must be create")
    if metadata.get("clean_identity_key") is not True:
        failures.append("clean_identity_key must be true")
    actor_id = str(metadata.get("affiliation_actor_id") or "").strip()
    creates_stub = metadata.get("create_affiliation_stub") is True
    if not actor_id and not creates_stub:
        failures.append("affiliation_actor_id or create_affiliation_stub is required")
    if creates_stub:
        stub_name = str(metadata.get("affiliation_stub_name") or "").strip()
        from agents.discovery.normalize import is_institution_affiliation

        if not is_institution_affiliation(stub_name):
            failures.append("affiliation stub must be an institution, never a department or role")
    name = str(payload.get("name") or "").strip()
    role = str(payload.get("role") or "").strip()
    affiliation = str(payload.get("affiliation") or "").strip()
    if not name:
        failures.append("name is required")
    elif len(name) > 255:
        failures.append("name exceeds the canonical 255-character limit")
    if not affiliation:
        failures.append("affiliation is required")
    if not role:
        failures.append("role is required")
    elif len(role) > 120:
        failures.append("role exceeds the actor_person 120-character limit")
    if not 0.0 <= float(route.score) <= 1.0:
        failures.append("score must be between 0 and 1")
    if failures:
        raise RuntimeError("person create guard failed: " + "; ".join(failures))


def _insert_person(
    session,
    payload: dict[str, object],
    source_id: str,
    *,
    confidence: float,
) -> str:
    person_id = str(uuid.uuid4())
    cols: dict[str, object] = {
        "person_id": person_id,
        "full_name": str(payload["name"]).strip(),
        "title": str(payload["role"]).strip(),
        "source_id": source_id,
        "verification_status": "needs_review",
        "confidence": confidence,
    }
    profile_url = str(payload.get("public_profile_url") or "").strip()
    if _is_linkedin_profile(profile_url):
        cols["linkedin_url"] = profile_url
    names = ", ".join(cols)
    binds = ", ".join(
        f"CAST(:{name} AS uuid)" if name in {"person_id", "source_id"} else f":{name}"
        for name in cols
    )
    session.execute(text(f"INSERT INTO person ({names}) VALUES ({binds})"), cols)
    return person_id


def _insert_person_affiliation(
    session,
    *,
    person_id: str,
    actor_id: str,
    role: str,
) -> None:
    session.execute(
        text(
            "INSERT INTO actor_person (actor_id, person_id, role, is_current) "
            "VALUES (CAST(:actor_id AS uuid), CAST(:person_id AS uuid), :role, TRUE)"
        ),
        {"actor_id": actor_id, "person_id": person_id, "role": role},
    )


def _insert_person_discovery_profile(
    session,
    *,
    staged: StagedRecord,
    person_id: str,
    actor_id: str,
    source_id: str,
    needs_actor_enrichment: bool = False,
) -> str:
    profile_id = str(uuid.uuid4())
    payload = staged.normalized_payload
    session.execute(
        text(
            "INSERT INTO person_discovery_profile (person_discovery_profile_id, "
            "person_id, actor_id, role, affiliation_raw, research_area, public_profile_url, "
            "needs_actor_enrichment, source_id, "
            "source_url, fetched_at) VALUES (CAST(:person_discovery_profile_id AS uuid), "
            "CAST(:person_id AS uuid), CAST(:actor_id AS uuid), :role, :affiliation_raw, "
            ":research_area, :public_profile_url, :needs_actor_enrichment, "
            "CAST(:source_id AS uuid), :source_url, :fetched_at)"
        ),
        {
            "person_discovery_profile_id": profile_id,
            "person_id": person_id,
            "actor_id": actor_id,
            "role": payload.get("role"),
            "affiliation_raw": payload.get("affiliation_raw") or payload.get("affiliation"),
            "research_area": payload.get("research_area"),
            "public_profile_url": payload.get("public_profile_url"),
            "needs_actor_enrichment": needs_actor_enrichment,
            "source_id": source_id,
            "source_url": staged.source_url,
            "fetched_at": staged.extracted_at,
        },
    )
    return profile_id


def _is_linkedin_profile(value: str) -> bool:
    if not value:
        return False
    hostname = (urlparse(value).hostname or "").casefold()
    return hostname == "linkedin.com" or hostname.endswith(".linkedin.com")


def _insert_person_review(
    session,
    staged: StagedRecord,
    route: RouteDecision,
    source_id: str,
) -> str:
    payload = staged.normalized_payload
    staged_name = str(payload.get("name") or "").strip()
    if not staged_name:
        raise ValueError("cannot queue person review without name")

    metadata = dict(route.metadata or {})
    person_review_id = str(uuid.uuid4())
    conflict_clause = (
        "ON CONFLICT (staged_record_id, candidate_person_id) "
        "WHERE candidate_person_id IS NOT NULL DO UPDATE SET "
        if route.target_entity_id
        else "ON CONFLICT (staged_record_id) WHERE candidate_person_id IS NULL DO UPDATE SET "
    )
    session.execute(
        text(
            "INSERT INTO person_review_queue (person_review_id, staged_record_id, source_id, "
            "candidate_person_id, score, staged_name, affiliation, role, public_profile_url, "
            "affiliation_raw, research_area, candidate_name, source_url, status, reviewer, review_kind, "
            "rubric, score_breakdown, rerank_position, rerank_reason, identity_outcome) "
            "VALUES (CAST(:person_review_id AS uuid), CAST(:staged_record_id AS uuid), "
            "CAST(:source_id AS uuid), CAST(:candidate_person_id AS uuid), :score, "
            ":staged_name, :affiliation, :role, :public_profile_url, :affiliation_raw, :research_area, "
            ":candidate_name, :source_url, 'pending', NULL, :review_kind, "
            "CAST(:rubric AS jsonb), CAST(:score_breakdown AS jsonb), :rerank_position, "
            ":rerank_reason, :identity_outcome) "
            f"{conflict_clause}"
            "source_id = EXCLUDED.source_id, score = EXCLUDED.score, "
            "staged_name = EXCLUDED.staged_name, affiliation = EXCLUDED.affiliation, "
            "role = EXCLUDED.role, public_profile_url = EXCLUDED.public_profile_url, "
            "affiliation_raw = EXCLUDED.affiliation_raw, research_area = EXCLUDED.research_area, "
            "candidate_name = EXCLUDED.candidate_name, "
            "source_url = EXCLUDED.source_url, review_kind = EXCLUDED.review_kind, "
            "rubric = EXCLUDED.rubric, score_breakdown = EXCLUDED.score_breakdown, "
            "rerank_position = EXCLUDED.rerank_position, "
            "rerank_reason = EXCLUDED.rerank_reason, "
            "identity_outcome = EXCLUDED.identity_outcome, updated_at = now()"
        ),
        {
            "person_review_id": person_review_id,
            "staged_record_id": staged.staged_record_id,
            "source_id": source_id,
            "candidate_person_id": route.target_entity_id,
            "score": float(route.score),
            "staged_name": staged_name,
            "affiliation": payload.get("affiliation"),
            "affiliation_raw": payload.get("affiliation_raw") or payload.get("affiliation"),
            "role": payload.get("role"),
            "public_profile_url": payload.get("public_profile_url"),
            "research_area": payload.get("research_area"),
            "candidate_name": metadata.get("candidate_name"),
            "source_url": staged.source_url,
            "review_kind": metadata.get("review_kind") or "identity",
            "rubric": json.dumps(metadata.get("rubric"), sort_keys=True)
            if metadata.get("rubric") is not None
            else None,
            "score_breakdown": json.dumps(
                metadata.get("score_breakdown"), sort_keys=True
            )
            if metadata.get("score_breakdown") is not None
            else None,
            "rerank_position": metadata.get("rerank_position"),
            "rerank_reason": metadata.get("rerank_reason"),
            "identity_outcome": metadata.get("identity_outcome"),
        },
    )
    return person_review_id


def apply_approved_person_affiliation_change(
    session,
    *,
    person_id: str,
    previous_actor_id: str,
    new_actor_id: str,
    previous_affiliation: str,
    new_affiliation: str,
    role: str,
    source_url: str,
    changed_at: str,
    live: bool = False,
) -> str:
    """Apply a reviewer-approved current-affiliation change and log its history."""
    required = {
        "person_id": person_id,
        "previous_actor_id": previous_actor_id,
        "new_actor_id": new_actor_id,
        "previous_affiliation": previous_affiliation,
        "new_affiliation": new_affiliation,
        "role": role,
        "source_url": source_url,
        "changed_at": changed_at,
    }
    missing = [name for name, value in required.items() if not str(value or "").strip()]
    if missing:
        raise ValueError(f"person affiliation change is missing: {', '.join(missing)}")
    if previous_actor_id == new_actor_id or previous_affiliation == new_affiliation:
        raise ValueError("person affiliation change requires distinct previous and new values")

    change_id = str(uuid.uuid4())
    transaction = session.begin()
    try:
        result = session.execute(
            text(
                "UPDATE actor_person SET actor_id = CAST(:new_actor_id AS uuid), "
                "role = :role, is_current = TRUE, start_date = CAST(:changed_at AS date), "
                "end_date = NULL "
                "WHERE person_id = CAST(:person_id AS uuid) "
                "AND actor_id = CAST(:previous_actor_id AS uuid) "
                "AND is_current IS NOT FALSE"
            ),
            {
                "person_id": person_id,
                "previous_actor_id": previous_actor_id,
                "new_actor_id": new_actor_id,
                "role": role,
                "changed_at": changed_at,
            },
        )
        if result.rowcount != 1:
            raise RuntimeError(
                "person affiliation change guard matched zero or multiple current relationships"
            )
        session.execute(
            text(
                "INSERT INTO person_change_log (person_change_id, person_id, field_name, "
                "previous_value, new_value, source_url, changed_at) "
                "VALUES (CAST(:person_change_id AS uuid), CAST(:person_id AS uuid), "
                "'affiliation', :previous_value, :new_value, :source_url, "
                "CAST(:changed_at AS timestamptz))"
            ),
            {
                "person_change_id": change_id,
                "person_id": person_id,
                "previous_value": previous_affiliation,
                "new_value": new_affiliation,
                "source_url": source_url,
                "changed_at": changed_at,
            },
        )
    except Exception:
        transaction.rollback()
        raise

    if live:
        transaction.commit()
    else:
        transaction.rollback()
    return change_id


def _gap_sql(field_name: str) -> str:
    if field_name == "estimated_trl":
        return f"{field_name} IS NULL"
    return f"({field_name} IS NULL OR btrim({field_name}::text) = '')"


def _slugify(value: str) -> str:
    try:
        from src.etl.common.text_cleaning import slugify

        return slugify(value)
    except ImportError:
        import re

        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _actor_slug(name: str, actor_id: str) -> str:
    suffix = f"-{actor_id[:8]}"
    max_base_length = 160 - len(suffix)
    base = _slugify(name)[:max_base_length].strip("-") or "actor"
    return f"{base}{suffix}"


def _unsafe_actor_absorb_reason(value: object) -> str | None:
    name = str(value or "").strip()
    if not name:
        return None
    if ACTOR_ABSORB_CONNECTOR_RE.search(name):
        return "connector phrase remains in actor name"
    if ACTOR_ROLE_PREFIX_RE.search(name):
        return "actor name reads as a role rather than an organization"
    if _looks_like_combined_actor_name(name):
        return "actor name looks like a combined organization list"
    return None


def _looks_like_combined_actor_name(name: str) -> bool:
    if not re.search(r"[;,]|\band\b", name, flags=re.IGNORECASE):
        return False
    parts = [
        part.strip()
        for part in ACTOR_LIST_DELIMITER_RE.split(name)
        if part and part.strip().lower() not in ACTOR_LIST_SUFFIXES
    ]
    return sum(1 for part in parts if _looks_like_actor_name_part(part)) >= 2


def _looks_like_actor_name_part(value: str) -> bool:
    stripped = value.strip()
    if re.fullmatch(r"[A-Z0-9][A-Z0-9&./-]+(?:\s+[A-Z0-9][A-Z0-9&./-]+)*", stripped):
        return True
    tokens = re.findall(r"[A-Za-z][A-Za-z&.'-]*", stripped)
    if {token.lower().strip(".") for token in tokens}.intersection(ACTOR_ORG_MARKERS):
        return True
    title_tokens = [token for token in tokens if token[:1].isupper()]
    return len(tokens) >= 2 and len(title_tokens) >= 2


def _is_empty(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _has_value(value: object) -> bool:
    return not _is_empty(value)
