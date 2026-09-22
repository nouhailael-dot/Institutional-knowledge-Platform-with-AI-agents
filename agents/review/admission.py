"""Transactional admission of human-reviewed discovery candidates.

This module orchestrates review decisions but deliberately contains no writes to
canonical entity tables. New/merge/link writes delegate to
``agents.discovery.promote.promote`` so the repository's single-writer rule is
preserved. The review audit row and source-queue status are committed in the
same outer transaction as that promotion.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import Enum, String, text

from agents.common.resolve_route import (
    RouteDecision,
    load_actor_resolver_class,
    load_event_candidates,
    load_person_affiliation_candidates,
    load_person_candidates,
    route_actor,
    route_event,
    route_person,
)
from agents.discovery.normalize import is_institution_affiliation
from agents.discovery.promote import ACTOR_CREATE_FIELDS, EVENT_CREATE_FIELDS, promote
from agents.discovery.stage import StagedRecord
from src.db.models import Actor, Event, Person

ENTITY_TYPES = {"actor", "event", "person"}
SOURCE_TABLES = {
    "search_candidate": ("candidate_id", "review_status"),
    "event_review_queue": ("event_review_id", "status"),
    "person_review_queue": ("person_review_id", "status"),
}
DECISION_ALIASES = {
    "same": "same_existing",
    "same_existing_actor": "same_existing",
    "same_existing_event": "same_existing",
    "same_existing_person": "same_existing",
    "new_actor": "new",
    "new_event": "new",
    "new_person": "new",
}
DECISION_KINDS = {"same_existing", "new", "reject", "defer"}
REJECTION_REASONS = (
    "Not relevant to GHUS sectors",
    "Not an organisation / event / person page",
    "Duplicate of an existing record",
    "Outside target geography",
    "Past event with no useful participants",
    "Insufficient evidence on the page",
    "Other",
)


class AdmissionValidationError(ValueError):
    pass


class AdmissionConflict(RuntimeError):
    pass


def _clean_required(value: object, name: str, max_length: int = 255) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise AdmissionValidationError(f"{name} is required")
    if len(cleaned) > max_length:
        raise AdmissionValidationError(f"{name} exceeds {max_length} characters")
    return cleaned


def _normalise_decision(raw: Mapping[str, Any]) -> dict[str, Any]:
    decision = dict(raw)
    entity_type = _clean_required(decision.get("entity_type"), "entity_type", 20).lower()
    if entity_type not in ENTITY_TYPES:
        raise AdmissionValidationError("entity_type must be actor, event, or person")
    kind = _clean_required(
        decision.get("decision_kind") or decision.get("kind"), "decision_kind", 40
    ).lower()
    kind = DECISION_ALIASES.get(kind, kind)
    if kind not in DECISION_KINDS:
        raise AdmissionValidationError("unsupported decision_kind")
    source = decision.get("source_ref") or {}
    if not isinstance(source, Mapping):
        raise AdmissionValidationError("source_ref must be an object")
    source_table = str(
        source.get("table") or decision.get("source_table") or ""
    ).strip()
    source_id = str(source.get("id") or decision.get("source_id") or "").strip()
    if source_table not in SOURCE_TABLES:
        raise AdmissionValidationError("unsupported source table")
    _clean_required(source_id, "source id", 80)
    target_id = str(decision.get("target_id") or "").strip() or None
    if kind == "same_existing" and not target_id:
        raise AdmissionValidationError("same_existing requires target_id")
    reviewer = _clean_required(decision.get("reviewer"), "reviewer", 120)
    key = _clean_required(decision.get("idempotency_key"), "idempotency_key", 200)
    edited = decision.get("edited_payload") or {}
    if not isinstance(edited, Mapping):
        raise AdmissionValidationError("edited_payload must be an object")
    hub_ids = decision.get("hub_ids") or []
    if entity_type != "actor" and hub_ids:
        raise AdmissionValidationError("hub assignments apply only to actors")
    if not isinstance(hub_ids, list):
        raise AdmissionValidationError("hub_ids must be a list")
    proposed_hub = decision.get("proposed_hub")
    if proposed_hub is not None and entity_type != "actor":
        raise AdmissionValidationError("a proposed hub applies only to actors")
    if proposed_hub is not None and kind not in {"same_existing", "new"}:
        raise AdmissionValidationError("a proposed hub requires an admitted actor decision")
    if proposed_hub is not None and not isinstance(proposed_hub, Mapping):
        raise AdmissionValidationError("proposed_hub must be an object")
    reason = str(decision.get("rejection_reason") or "").strip() or None
    reason_other = str(decision.get("rejection_reason_other") or "").strip() or None
    if kind == "reject":
        if reason not in REJECTION_REASONS:
            raise AdmissionValidationError("reject requires one fixed rejection reason")
        if reason == "Other" and not reason_other:
            raise AdmissionValidationError("Other rejection reason requires free text")
    elif reason or reason_other:
        raise AdmissionValidationError("rejection fields are valid only for reject")
    return {
        **decision,
        "entity_type": entity_type,
        "decision_kind": kind,
        "source_table": source_table,
        "source_id": source_id,
        "target_id": target_id,
        "reviewer": reviewer,
        "idempotency_key": key,
        "edited_payload": dict(edited),
        "hub_ids": [str(value).strip() for value in hub_ids if str(value).strip()],
        "proposed_hub": dict(proposed_hub) if proposed_hub is not None else None,
        "rejection_reason": reason,
        "rejection_reason_other": reason_other,
        "notes": str(decision.get("notes") or "").strip() or None,
    }


def _field_contract(entity_type: str) -> tuple[set[str], dict[str, tuple[int | None, list[str]]]]:
    if entity_type == "actor":
        model, aliases = Actor, {"name": "name"}
        allowed = {"name", *ACTOR_CREATE_FIELDS}
    elif entity_type == "event":
        model, aliases = Event, {"title": "name", "start_date": "next_date"}
        allowed = {"name", "title", "start_date", *EVENT_CREATE_FIELDS}
    else:
        model = Person
        aliases = {
            "name": "full_name",
            "role": "title",
            "public_profile_url": "linkedin_url",
        }
        allowed = {
            "name", "role", "affiliation", "affiliation_raw",
            "public_profile_url", "research_area",
        }
    contract: dict[str, tuple[int | None, list[str]]] = {}
    for field in allowed:
        column_name = aliases.get(field, field)
        column = model.__table__.columns.get(column_name)
        length = column.type.length if column is not None and isinstance(column.type, String) else None
        values = list(column.type.enums) if column is not None and isinstance(column.type, Enum) else []
        contract[field] = (length, values)
    if entity_type == "person":
        contract["role"] = (120, [])
    return allowed, contract


def validate_edited_payload(entity_type: str, edited_payload: Mapping[str, Any]) -> None:
    allowed, contract = _field_contract(entity_type)
    unknown = sorted(set(edited_payload) - allowed)
    if unknown:
        raise AdmissionValidationError("unsupported edited fields: " + ", ".join(unknown))
    for field, value in edited_payload.items():
        if value is None:
            continue
        length, enum_values = contract[field]
        if length is not None and len(str(value)) > length:
            raise AdmissionValidationError(f"{field} exceeds {length} characters")
        if enum_values and value not in enum_values:
            raise AdmissionValidationError(
                f"{field} must be one of: {', '.join(enum_values)}"
            )


def _load_source(session, table: str, source_id: str) -> dict[str, Any]:
    if table == "search_candidate":
        sql = (
            "SELECT candidate_id::text AS source_id, run_id::text AS run_id, entity_type, "
            "url AS source_url, record_preview AS payload, created_at AS extracted_at "
            "FROM search_candidate WHERE candidate_id = CAST(:source_id AS uuid)"
        )
    elif table == "event_review_queue":
        sql = (
            "SELECT q.event_review_id::text AS source_id, s.run_id::text AS run_id, "
            "'event' AS entity_type, s.source_url, s.normalized_payload AS payload, "
            "s.extracted_at FROM event_review_queue q JOIN staged_record s "
            "ON s.staged_record_id = q.staged_record_id "
            "WHERE q.event_review_id = CAST(:source_id AS uuid)"
        )
    else:
        sql = (
            "SELECT q.person_review_id::text AS source_id, s.run_id::text AS run_id, "
            "'person' AS entity_type, s.source_url, s.normalized_payload AS payload, "
            "s.extracted_at FROM person_review_queue q JOIN staged_record s "
            "ON s.staged_record_id = q.staged_record_id "
            "WHERE q.person_review_id = CAST(:source_id AS uuid)"
        )
    row = session.execute(text(sql), {"source_id": source_id}).mappings().first()
    if row is None:
        raise AdmissionValidationError("source review row does not exist")
    result = dict(row)
    payload = result.get("payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise AdmissionValidationError("source candidate payload is not an object")
    result["payload"] = payload
    return result


def _staged(source: Mapping[str, Any], entity_type: str, edited: Mapping[str, Any]) -> StagedRecord:
    payload = {**dict(source["payload"]), **dict(edited)}
    payload.pop("_discovered_domain", None)
    extracted = source.get("extracted_at") or datetime.now(timezone.utc)
    return StagedRecord(
        run_id=str(source.get("run_id") or uuid.uuid4()),
        entity_type=entity_type,
        natural_key=str(payload.get("natural_key") or payload.get("name") or payload.get("title") or source["source_id"]),
        source_url=str(source.get("source_url") or ""),
        payload=payload.copy(),
        normalized_payload=payload,
        prompt_version="human-review-admission-v1",
        extracted_at=extracted.isoformat() if hasattr(extracted, "isoformat") else str(extracted),
        staged_record_id=str(source.get("staged_record_id") or uuid.uuid4()),
    )


def _resolve_person_affiliation(session, payload: Mapping[str, Any]) -> dict[str, Any]:
    affiliation = str(payload.get("affiliation") or "").strip()
    if not is_institution_affiliation(affiliation):
        raise AdmissionValidationError(
            "affiliation must be an institution; departments and role text cannot become actors"
        )
    resolver = load_actor_resolver_class()(session)
    actor_route = route_actor({"name": affiliation}, resolver)
    if actor_route.zone == "review":
        raise AdmissionConflict("affiliation is ambiguous and must remain in review")
    if actor_route.zone == "absorb":
        return {"affiliation_actor_id": actor_route.target_entity_id}
    return {"create_affiliation_stub": True, "affiliation_stub_name": affiliation}


def _promotion_route(session, decision: Mapping[str, Any], staged: StagedRecord) -> RouteDecision:
    entity_type = str(decision["entity_type"])
    kind = str(decision["decision_kind"])
    metadata: dict[str, Any] = {}
    if entity_type == "actor":
        metadata["hub_ids"] = decision["hub_ids"]
    if kind == "same_existing":
        if entity_type == "person":
            metadata.update(_resolve_person_affiliation(session, staged.normalized_payload))
            return RouteDecision(
                zone="link_existing", score=1.0,
                target_entity_id=str(decision["target_id"]), metadata=metadata,
            )
        return RouteDecision(
            zone="absorb", score=1.0,
            target_entity_id=str(decision["target_id"]), metadata=metadata,
        )
    if entity_type == "actor":
        route = route_actor(staged.normalized_payload, load_actor_resolver_class()(session))
    elif entity_type == "event":
        route = route_event(staged.normalized_payload, load_event_candidates(session))
    else:
        route = route_person(
            staged.normalized_payload,
            load_person_candidates(session),
            allow_create=True,
            affiliation_candidates=load_person_affiliation_candidates(session),
            actor_resolver=load_actor_resolver_class()(session),
        )
    if route.zone != "create":
        raise AdmissionConflict(
            "frozen entity resolution found an existing or ambiguous match; choose same existing or defer"
        )
    metadata.update(dict(route.metadata or {}))
    metadata["hub_ids"] = decision["hub_ids"]
    if entity_type == "person":
        metadata["score_band"] = "auto_high"
    return RouteDecision(
        zone="create", score=1.0 if entity_type == "person" else route.score,
        candidate_ids=route.candidate_ids, metadata=metadata,
    )


def _insert_proposed_hub(session, decision: Mapping[str, Any]) -> str | None:
    proposed = decision.get("proposed_hub")
    if not proposed:
        return None
    proposed_id = str(uuid.uuid4())
    name = _clean_required(proposed.get("name"), "proposed hub name", 255)
    rationale = _clean_required(proposed.get("rationale"), "proposed hub rationale", 5000)
    session.execute(
        text(
            "INSERT INTO proposed_hub (proposed_hub_id, name, primary_city, state, country, "
            "rationale, source_table, source_row_id, proposed_by, status) VALUES "
            "(CAST(:id AS uuid), :name, :primary_city, :state, :country, :rationale, "
            ":source_table, CAST(:source_id AS uuid), :reviewer, 'pending')"
        ),
        {
            "id": proposed_id, "name": name,
            "primary_city": proposed.get("primary_city"), "state": proposed.get("state"),
            "country": proposed.get("country"), "rationale": rationale,
            "source_table": decision["source_table"], "source_id": decision["source_id"],
            "reviewer": decision["reviewer"],
        },
    )
    return proposed_id


def _update_source_status(session, table: str, source_id: str, status: str, reviewer: str, notes: str | None) -> None:
    id_column, status_column = SOURCE_TABLES[table]
    optional = ", review_updated_at = now()" if table == "search_candidate" else ", updated_at = now()"
    if table in {"event_review_queue", "person_review_queue"}:
        optional += ", reviewer = :reviewer, notes = COALESCE(:notes, notes)"
    result = session.execute(
        text(
            f"UPDATE {table} SET {status_column} = :status{optional} "
            f"WHERE {id_column} = CAST(:source_id AS uuid) AND {status_column} = 'pending'"
        ),
        {"status": status, "reviewer": reviewer, "notes": notes, "source_id": source_id},
    )
    if result.rowcount != 1:
        raise AdmissionConflict("source review row is no longer pending")


def apply_review_decision(session, decision: Mapping[str, Any]) -> dict[str, Any]:
    """Apply one idempotent review decision in a single database transaction."""
    clean = _normalise_decision(decision)
    validate_edited_payload(clean["entity_type"], clean["edited_payload"])
    transaction = session.begin()
    try:
        prior = session.execute(
            text(
                "SELECT outcome FROM review_admission_decision "
                "WHERE idempotency_key = :idempotency_key"
            ),
            {"idempotency_key": clean["idempotency_key"]},
        ).scalar_one_or_none()
        if prior is not None:
            transaction.rollback()
            if isinstance(prior, str):
                prior = json.loads(prior)
            return {**dict(prior), "idempotent_replay": True}

        source = _load_source(session, clean["source_table"], clean["source_id"])
        if str(source.get("entity_type") or "").lower() != clean["entity_type"]:
            raise AdmissionValidationError("source entity type does not match decision")
        result = None
        proposed_hub_id = None
        if clean["decision_kind"] in {"same_existing", "new"}:
            staged = _staged(source, clean["entity_type"], clean["edited_payload"])
            route = _promotion_route(session, clean, staged)
            result = promote(
                staged, route, session=session, live=True, people_enabled=True,
                manage_transaction=False,
            )
            proposed_hub_id = _insert_proposed_hub(session, clean)
            source_status = "approved"
        elif clean["decision_kind"] == "reject":
            source_status = "rejected"
        else:
            source_status = "deferred"
        outcome = {
            "decision_kind": clean["decision_kind"],
            "entity_type": clean["entity_type"],
            "source_table": clean["source_table"],
            "source_id": clean["source_id"],
            "status": source_status,
            "canonical_entity_id": result.entity_id if result is not None else None,
            "promotion_action": result.action if result is not None else None,
            "fields_absorbed": result.fields_absorbed if result is not None else [],
            "proposed_hub_id": proposed_hub_id,
            "idempotent_replay": False,
        }
        decision_id = str(uuid.uuid4())
        session.execute(
            text(
                "INSERT INTO review_admission_decision "
                "(review_admission_decision_id, idempotency_key, entity_type, source_table, "
                "source_row_id, decision_kind, target_entity_id, edited_payload, hub_ids, "
                "proposed_hub_id, reviewer, rejection_reason, rejection_reason_other, notes, outcome) "
                "VALUES (CAST(:decision_id AS uuid), :idempotency_key, :entity_type, :source_table, "
                "CAST(:source_id AS uuid), :decision_kind, CAST(:target_id AS uuid), "
                "CAST(:edited_payload AS jsonb), CAST(:hub_ids AS jsonb), "
                "CAST(:proposed_hub_id AS uuid), :reviewer, :rejection_reason, "
                ":rejection_reason_other, :notes, CAST(:outcome AS jsonb))"
            ),
            {
                **clean, "decision_id": decision_id,
                "edited_payload": json.dumps(clean["edited_payload"], default=str),
                "hub_ids": json.dumps(clean["hub_ids"]),
                "outcome": json.dumps(outcome, default=str),
                "proposed_hub_id": proposed_hub_id,
            },
        )
        _update_source_status(
            session, clean["source_table"], clean["source_id"], source_status,
            clean["reviewer"], clean["notes"],
        )
        transaction.commit()
        return outcome
    except Exception:
        transaction.rollback()
        raise


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply one reviewed GHUS discovery decision")
    parser.add_argument("--decision", required=True, type=Path)
    args = parser.parse_args(argv)
    if os.getenv("REVIEW_ADMISSION_WRITES_ENABLED", "").lower() not in {"1", "true", "yes"}:
        parser.error("REVIEW_ADMISSION_WRITES_ENABLED=true is required (fail-closed)")
    raw = json.loads(args.decision.read_text(encoding="utf-8"))
    from src.db.session import SessionLocal

    with SessionLocal() as session:
        outcome = apply_review_decision(session, raw)
    json.dump(outcome, sys.stdout, sort_keys=True, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
