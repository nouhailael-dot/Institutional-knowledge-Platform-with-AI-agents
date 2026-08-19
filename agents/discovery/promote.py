"""Canonical promotion path for agent-staged records.

This module is intentionally the only agents module that inserts or updates
canonical entity tables. The Phase 1 slice supports event create/absorb. The
existing review_queue table is actor-specific, so event routing is deterministic
and does not emit review-zone decisions.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import text

from agents.common.provenance import insert_source
from agents.common.resolve_route import RouteDecision
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


@dataclass
class PromotionResult:
    action: str
    entity_type: str
    zone: str
    entity_id: Optional[str] = None
    dry_run: bool = True
    fields_absorbed: list[str] = field(default_factory=list)


def promote(staged: StagedRecord, route: RouteDecision, session=None, *, live: bool = False) -> PromotionResult:
    if staged.entity_type != "event":
        raise NotImplementedError("Phase 1 promotion supports only entity_type='event'")

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
            result = PromotionResult(
                action="absorbed" if fields else "no_op",
                entity_type="event",
                zone="absorb",
                entity_id=route.target_entity_id,
                dry_run=False,
                fields_absorbed=fields,
            )
        elif route.zone == "review":
            raise RuntimeError(
                "event review routing cannot use the existing actor-only review_queue; "
                "event route_event() is deterministic and should not produce review"
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
    row = session.execute(
        text(
            "SELECT event_type, description, location, website, thematic_focus, "
            "expected_attendance, access_type, recurring_pattern, next_date, "
            "sponsoring_orgs, source_id FROM event WHERE event_id = CAST(:event_id AS uuid)"
        ),
        {"event_id": event_id},
    ).mappings().first()
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
    set_clause = ", ".join(f"{field_name} = :{field_name}" for field_name in updates if field_name != "event_id")
    session.execute(text(f"UPDATE event SET {set_clause} WHERE event_id = CAST(:event_id AS uuid)"), updates)
    return [field_name for field_name in updates if field_name not in {"event_id", "source_id"}]


def _is_empty(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _has_value(value: object) -> bool:
    return not _is_empty(value)
