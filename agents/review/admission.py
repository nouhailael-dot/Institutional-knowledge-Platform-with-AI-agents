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
    load_actor_candidates,
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
from agents.enrichment.decisions import create_sector
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
        # ACTOR_CREATE_FIELDS is the V1 inheritable list. A GHUS reviewer also
        # decides the V2 classification and the actor's primary sector on the
        # Review screen; without these the screen's own payload was refused
        # ("unsupported edited fields") and no reviewed actor could be created.
        allowed = {"name", *ACTOR_CREATE_FIELDS, *V2_ACTOR_EDIT_FIELDS}
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
    if entity_type == "actor":
        _validate_actor_v2_fields(edited_payload)
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


# What a GHUS reviewer may set on the Review screen beyond the V1 fields: the
# Architecture V2 classification, the chosen primary sector, and the region
# (which promotion recomputes from the state, so it is accepted, not trusted).
V2_ACTOR_EDIT_FIELDS = frozenset({
    "actor_category", "category_type", "category_note", "category_needs_review",
    "primary_sector", "sector_codes", "region", "region_code", "state_code",
    "alternate_names", "topic_id",
})


def _validate_actor_v2_fields(payload: Mapping[str, Any]) -> None:
    """The category/type pair and the sector code, checked against the catalog."""
    from agents.common.actor_classification import (
        CATCH_ALL_TYPE_CODES,
        load_category_catalog,
    )
    from agents.enrichment.decisions import SECTOR_CODE

    category = str(payload.get("actor_category") or "").strip()
    type_code = str(payload.get("category_type") or "").strip()
    note = str(payload.get("category_note") or "").strip()
    if category or type_code:
        catalog = load_category_catalog()
        if category not in catalog.by_code:
            raise AdmissionValidationError(
                f"actor_category must be one of the 12 GHUS categories, not {category!r}")
        if type_code and not catalog.validates(category, type_code):
            raise AdmissionValidationError(
                f"category_type {type_code!r} is not a type of {category!r}")
        if (type_code in CATCH_ALL_TYPE_CODES
                or payload.get("category_needs_review")) and not note:
            raise AdmissionValidationError(
                "a catch-all type or a flagged category needs a one-line note")
    for code in [payload.get("primary_sector"), *(payload.get("sector_codes") or [])]:
        if str(code or "").strip() and not SECTOR_CODE.match(str(code).strip().upper()):
            raise AdmissionValidationError(f"{code!r} is not a sector code")


def _load_source(session, table: str, source_id: str) -> dict[str, Any]:
    if table == "search_candidate":
        # The topic of the discovery request that found this candidate, so a
        # reviewed actor is always admitted FOR a topic: Layer 1 facts are
        # topic-scoped, and promotion collects none without one. Topics mirror
        # sectors by code. Only used when the record itself states no topic.
        sql = (
            "SELECT c.candidate_id::text AS source_id, c.run_id::text AS run_id, c.entity_type, "
            "c.url AS source_url, c.record_preview AS payload, c.created_at AS extracted_at, "
            "c.rubric, ("
            "  SELECT t.topic_id::text FROM actor_update_subscription s"
            "  JOIN actor_update_subscription_run sr"
            "    ON sr.actor_update_subscription_id = s.actor_update_subscription_id"
            "  JOIN collection_run cr ON cr.collection_run_id = sr.collection_run_id"
            "  JOIN topic t ON t.code = s.sector_codes[1]"
            "  WHERE cr.config_snapshot->>'search_run_id' = c.run_id::text"
            "  ORDER BY cr.started_at DESC LIMIT 1) AS request_topic_id "
            "FROM search_candidate c WHERE c.candidate_id = CAST(:source_id AS uuid)"
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


def _source_sector_codes(source: Mapping[str, Any], payload: Mapping[str, Any]) -> list[str]:
    """The reviewer's chosen sector first, then the sectors the page evidenced.

    Admission used to stage a reviewed discovery candidate with NO sector codes,
    so the actor it created had no sector at all - whatever the page showed and
    whatever the reviewer chose.
    """
    rubric = source.get("rubric") or {}
    if isinstance(rubric, str):
        rubric = json.loads(rubric)
    evidenced = [str(row.get("code") or "").upper() for row in (rubric.get("sector_codes") or [])
                 if isinstance(row, dict) and row.get("code")]
    chosen = str(payload.get("primary_sector") or "").strip().upper()
    listed = [str(c).upper() for c in (payload.get("sector_codes") or []) if str(c).strip()]
    return list(dict.fromkeys(c for c in [chosen, *listed, *evidenced] if c))


def _staged(source: Mapping[str, Any], entity_type: str, edited: Mapping[str, Any]) -> StagedRecord:
    payload = {**dict(source["payload"]), **dict(edited)}
    payload.pop("_discovered_domain", None)
    if entity_type == "actor" and not payload.get("topic_id") and source.get("request_topic_id"):
        payload["topic_id"] = str(source["request_topic_id"])
    sector_codes = _source_sector_codes(source, payload) if entity_type == "actor" else []
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
        sector_codes=sector_codes,
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
        # The same mapped-first rule discovery applies: an exact website-domain
        # or name / alternate-name match is the existing actor, whatever the
        # model score says. Without the mapped list a renamed or differently
        # written organisation on the same domain could be created twice.
        route = route_actor(staged.normalized_payload, load_actor_resolver_class()(session),
                            load_actor_candidates(session))
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
        match = route.metadata or {}
        found = (f" ({match.get('match_rule')}: {match.get('matched_name') or ''} "
                 f"{route.target_entity_id or ''})".rstrip() + ")") if match.get("match_rule") else ""
        raise AdmissionConflict(
            "frozen entity resolution found an existing or ambiguous match"
            f"{found}; choose same existing or defer"
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


def apply_category_decisions(session, decision: Mapping[str, Any]) -> dict[str, Any]:
    """Confirm GHUS categories for pending category_doubt reviews, all or nothing.

    Canonical writes delegate to ``record_category_review_decision``. Replaying
    the same request is safe: already-resolved items are reported, not rewritten.
    """
    from agents.enrichment.decisions import record_category_review_decision

    reviewer = _clean_required(decision.get("reviewer"), "reviewer", 120)
    _clean_required(decision.get("idempotency_key"), "idempotency_key", 200)
    items = decision.get("items")
    if not isinstance(items, list) or not items:
        raise AdmissionValidationError("confirm_category requires a non-empty items list")
    if len(items) > 500:
        raise AdmissionValidationError("confirm_category accepts at most 500 items")
    notes = str(decision.get("notes") or "").strip() or None
    transaction = session.begin()
    try:
        results = [
            record_category_review_decision(
                session,
                review_item_id=_clean_required(item.get("review_item_id"), "review_item_id", 80),
                actor_category=_clean_required(item.get("actor_category"), "actor_category", 80),
                decided_by=reviewer,
                reason=notes,
                live=True,
            )
            for item in items
            if isinstance(item, Mapping)
        ]
        if len(results) != len(items):
            raise AdmissionValidationError("every item must be an object")
        transaction.commit()
    except Exception:
        transaction.rollback()
        raise
    return {
        "decision_kind": "confirm_category",
        "status": "resolved",
        "resolved": sum(result["action"] == "resolved" for result in results),
        "already_resolved": sum(result["action"] == "already_resolved" for result in results),
        "items": results,
    }


REVIEW_ITEM_DECISION_KINDS = {"resolve_location", "resolve_relationship", "verify_actor",
                              "resolve_fact", "resolve_hub_membership"}


def apply_review_item_decision(session, decision: Mapping[str, Any]) -> dict[str, Any]:
    """Apply one GHUS decision on a V2 location or relationship review item.

    Canonical writes delegate to ``agents.enrichment.decisions``; replaying a
    decided item is reported, not rewritten.
    """
    from agents.enrichment.decisions import (
        record_actor_verification_review_decision,
        record_fact_review_decision,
        record_geocode_review_decision,
        record_hub_membership_decision,
        record_relationship_review_decision,
    )

    kind = str(decision.get("decision_kind") or "")
    if kind not in REVIEW_ITEM_DECISION_KINDS:
        raise AdmissionValidationError("unsupported review item decision")
    reviewer = _clean_required(decision.get("reviewer"), "reviewer", 120)
    _clean_required(decision.get("idempotency_key"), "idempotency_key", 200)
    item_id = _clean_required(decision.get("review_item_id"), "review_item_id", 80)
    notes = str(decision.get("notes") or "").strip() or None
    transaction = session.begin()
    try:
        if kind == "verify_actor":
            result = record_actor_verification_review_decision(
                session, review_item_id=item_id, decided_by=reviewer,
                verified=bool(decision.get("verified")),
                rejection_reason=decision.get("rejection_reason"), notes=notes, live=True,
            )
        elif kind == "resolve_fact":
            # A fact conflict or pending update: use the proposed value or keep
            # the current one. Both facts stay in the ledger either way.
            result = record_fact_review_decision(
                session, review_item_id=item_id, decided_by=reviewer,
                accept=bool(decision.get("accept")), notes=notes, live=True,
            )
        elif kind == "resolve_hub_membership":
            # A hub an unassigned actor now fits: accept adds the membership,
            # refuse closes the proposal. Nothing is ever removed.
            result = record_hub_membership_decision(
                session, review_item_id=item_id, decided_by=reviewer,
                accept=bool(decision.get("accept")), notes=notes, live=True,
            )
        elif kind == "resolve_location":
            result = record_geocode_review_decision(
                session, review_item_id=item_id, decided_by=reviewer,
                city=decision.get("city"), state=decision.get("state"),
                country=decision.get("country") or "US",
                keep_unlocated=bool(decision.get("keep_unlocated")), reason=notes, live=True,
            )
        else:
            result = record_relationship_review_decision(
                session, review_item_id=item_id, decided_by=reviewer,
                approve=bool(decision.get("approve")), source_url=decision.get("source_url"),
                relationship_type=decision.get("relationship_type"), reason=notes, live=True,
            )
        transaction.commit()
    except Exception:
        transaction.rollback()
        raise
    return {"decision_kind": kind, "status": "applied", **result}


def apply_create_sector(session, decision: Mapping[str, Any]) -> dict[str, Any]:
    """A reviewer adds a sector that a real actor needs (decisions.create_sector)."""
    reviewer = _clean_required(decision.get("reviewer"), "reviewer", 120)
    transaction = session.begin()
    try:
        result = create_sector(
            session,
            name=str(decision.get("name") or ""),
            code=str(decision.get("code") or "") or None,
            description=str(decision.get("description") or "") or None,
            created_by=reviewer,
        )
    except ValueError as exc:
        transaction.rollback()
        raise AdmissionValidationError(str(exc)) from exc
    except Exception:
        transaction.rollback()
        raise
    transaction.commit()
    return {"decision_kind": "create_sector", "status": "applied", **result}


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply one reviewed GHUS discovery decision")
    parser.add_argument("--decision", required=True, type=Path)
    args = parser.parse_args(argv)
    if os.getenv("REVIEW_ADMISSION_WRITES_ENABLED", "").lower() not in {"1", "true", "yes"}:
        parser.error("REVIEW_ADMISSION_WRITES_ENABLED=true is required (fail-closed)")
    raw = json.loads(args.decision.read_text(encoding="utf-8"))
    from src.db.session import SessionLocal

    with SessionLocal() as session:
        if raw.get("decision_kind") == "create_sector":
            outcome = apply_create_sector(session, raw)
        elif raw.get("decision_kind") == "confirm_category":
            outcome = apply_category_decisions(session, raw)
        elif raw.get("decision_kind") in REVIEW_ITEM_DECISION_KINDS:
            outcome = apply_review_item_decision(session, raw)
        else:
            outcome = apply_review_decision(session, raw)
    json.dump(outcome, sys.stdout, sort_keys=True, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
