"""Canonical promotion path for agent-staged records.

This module is intentionally one of the only agents modules that inserts or
updates canonical entity tables. The Phase 1 slice supports event
create/absorb/review. Event review rows use an agent-owned queue because the
existing review_queue table is actor-specific.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import text

from agents.common.provenance import insert_source
from agents.common.resolve_route import RouteDecision
from src.ML.entity_resolution.resolve_or_create import INHERITABLE_FIELDS as ACTOR_FIELDS
from agents.discovery.stage import StagedRecord

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
ACTOR_CREATE_FIELDS = list(ACTOR_FIELDS)
ACTOR_ABSORB_FIELDS = list(ACTOR_FIELDS)


@dataclass
class PromotionResult:
    action: str
    entity_type: str
    zone: str
    entity_id: Optional[str] = None
    dry_run: bool = True
    fields_absorbed: list[str] = field(default_factory=list)
    review_id: Optional[str] = None


def promote(
    staged: StagedRecord, route: RouteDecision, session=None, *, live: bool = False
) -> PromotionResult:
    if staged.sector_match == "out_of_sector":
        raise RuntimeError("out_of_sector staged records must not be promoted")
    if staged.entity_type == "actor":
        return _promote_actor(staged, route, session=session, live=live)
    if staged.entity_type != "event":
        raise NotImplementedError(
            "promotion supports only entity_type='event' or entity_type='actor'"
        )

    if session is None:
        if live:
            raise ValueError("live promotion requires a database session")
        return _dry_run_preview(staged, route)

    transaction = session.begin()
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
            if not route.target_entity_id:
                raise ValueError("event review route requires target_entity_id")
            _insert_event_review(session, staged, route)
            result = PromotionResult(
                action="queued_for_review",
                entity_type="event",
                zone="review",
                entity_id=route.target_entity_id,
                dry_run=False,
            )
        else:
            raise ValueError(f"unknown route zone {route.zone!r}")
    except Exception:
        transaction.rollback()
        raise

    if live:
        transaction.commit()
        return result
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


def _promote_actor(
    staged: StagedRecord, route: RouteDecision, session=None, *, live: bool = False
) -> PromotionResult:
    if session is None:
        if live:
            raise ValueError("live promotion requires a database session")
        return _dry_run_preview(staged, route)

    transaction = session.begin()
    try:
        if route.zone == "create":
            source_id = insert_source(
                session,
                source_url=staged.source_url,
                fetched_at=staged.extracted_at,
                description="agent discovery actor create",
            )
            actor_id = _insert_actor(session, staged.normalized_payload, source_id)
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
        transaction.rollback()
        raise

    if live:
        transaction.commit()
        return result
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
        "slug": f"{_slugify(str(name))}-{actor_id[:8]}",
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


def _is_empty(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _has_value(value: object) -> bool:
    return not _is_empty(value)
