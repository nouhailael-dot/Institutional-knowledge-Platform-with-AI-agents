"""Apply/proposal decisions for field-level enrichment."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text

from agents.common.facts import ActorFactWrite, validate_actor_fact
from agents.common.provenance import insert_field_proposal, insert_source
from agents.common.relationships import (
    EntityEdgeRequest,
    network_location_requests,
    validate_entity_edge,
)
from agents.enrichment.fields import FieldPolicy
from agents.enrichment.gaps import is_gap, is_present, sql_gap_condition
from agents.enrichment.specs import EntitySpec

logger = logging.getLogger(__name__)

AI_CONFIDENCE = 0.70
_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


@dataclass(frozen=True)
class FieldOutcome:
    action: str
    reason: str
    proposal_id: str | None = None
    source_id: str | None = None


def persist_canonical_record(session, record):
    """The sole ORM gateway for legacy importers until they stage V2 records."""
    session.add(record)
    return record


def execute_canonical_write(session, statement, params=None):
    """The sole statement gateway for approved manual canonical decisions."""
    return session.execute(statement, params or {})


def append_entity_edge(
    session,
    request: EntityEdgeRequest,
    *,
    live: bool = False,
) -> str:
    """Append one sourced V2 edge through the approved manual writer boundary."""
    edge = validate_entity_edge(request)
    if not live:
        return "would_append"
    inserted = execute_canonical_write(
        session,
        text(
            "INSERT INTO entity_edge (subject_type,subject_id,relationship_type,"
            "object_type,object_id,topic_id,source_id,confidence) VALUES ("
            ":subject_type,CAST(:subject_id AS uuid),:relationship_type,:object_type,"
            "CAST(:object_id AS uuid),CAST(:topic_id AS uuid),CAST(:source_id AS uuid),"
            ":confidence) ON CONFLICT DO NOTHING RETURNING entity_edge_id::text"
        ),
        edge.__dict__,
    ).scalar_one_or_none()
    if inserted:
        return str(inserted)
    existing = session.execute(
        text(
            "SELECT entity_edge_id::text FROM entity_edge WHERE "
            "subject_type=:subject_type AND subject_id=CAST(:subject_id AS uuid) "
            "AND relationship_type=:relationship_type AND object_type=:object_type "
            "AND object_id=CAST(:object_id AS uuid) "
            "AND topic_id IS NOT DISTINCT FROM CAST(:topic_id AS uuid) "
            "AND source_id=CAST(:source_id AS uuid)"
        ),
        edge.__dict__,
    ).scalar_one()
    return str(existing)


def append_network_locations(
    session,
    *,
    parent_actor_id: str,
    location_actor_ids: list[str],
    source_id: str,
    topic_id: str | None = None,
    live: bool = False,
) -> list[str]:
    """Append location->network ``unit_of`` edges; never copy network reach to sites."""
    requests = network_location_requests(
        parent_actor_id=parent_actor_id,
        location_actor_ids=location_actor_ids,
        source_id=source_id,
        topic_id=topic_id,
    )
    return [append_entity_edge(session, request, live=live) for request in requests]


def append_actor_fact(
    session,
    write: ActorFactWrite,
    *,
    live: bool = False,
) -> str:
    """Resolve one immutable topic fact; dry-run is the default.

    Historical fact values are never updated. A mutable pointer identifies the
    single current value; corroboration, supersession, conflict and pending
    human update are recorded as new rows.
    """
    fact = validate_actor_fact(write)
    if not live:
        return "would_append"
    source_id = insert_source(
        session,
        source_url=fact.source_url,
        fetched_at=fact.date_read,
        description=f"Architecture V2 layer {fact.layer} {fact.fact_type}.{fact.field_key}",
        source_type="agent_collection",
        trust_tier="candidate",
    )
    semantic_hash = _fact_semantic_hash(fact)
    current = session.execute(
        text(
            "SELECT f.actor_fact_id::text AS actor_fact_id,f.semantic_hash,f.confidence,"
            "f.retrieved_at,f.creator_class,f.collection_state,f.fact_value FROM actor_fact_current_pointer p "
            "JOIN actor_fact f ON f.actor_fact_id=p.actor_fact_id "
            "WHERE p.actor_id=CAST(:actor_id AS uuid) AND p.topic_id=CAST(:topic_id AS uuid) "
            "AND p.fact_key=:fact_key FOR UPDATE OF p"
        ),
        {"actor_id": fact.actor_id, "topic_id": fact.topic_id, "fact_key": fact.field_key},
    ).mappings().first()
    current_hash = (
        current["semantic_hash"] if current and current["semantic_hash"]
        else _stored_fact_semantic_hash(current) if current else None
    )
    if current and current_hash == semantic_hash:
        corroboration_id = str(uuid.uuid4())
        execute_canonical_write(session, text(
            "INSERT INTO fact_corroboration (fact_corroboration_id,actor_fact_id,source_id,"
            "request_id,confidence,retrieved_at,generated_by) VALUES (CAST(:id AS uuid),"
            "CAST(:fact_id AS uuid),CAST(:source_id AS uuid),CAST(:request_id AS uuid),"
            ":confidence,:retrieved_at,:generated_by) ON CONFLICT DO NOTHING"
        ), {"id": corroboration_id, "fact_id": current["actor_fact_id"], "source_id": source_id,
            "request_id": fact.request_id, "confidence": fact.confidence,
            "retrieved_at": fact.date_read, "generated_by": fact.created_by})
        return str(current["actor_fact_id"])

    creator_class = _fact_creator_class(fact)
    if current is None:
        state, supersedes = "accepted", None
    elif current["creator_class"] == "ghus_human":
        state, supersedes = "pending_update", None
    elif (_confidence_rank(fact.confidence) >= _confidence_rank(current["confidence"])
          and fact.date_read > current["retrieved_at"]):
        state, supersedes = "accepted", str(current["actor_fact_id"])
    else:
        state, supersedes = "conflict_flagged", None

    fact_id = _insert_resolved_fact(
        session, fact=fact, source_id=source_id, semantic_hash=semantic_hash,
        creator_class=creator_class, lifecycle_state=state, supersedes_fact_id=supersedes,
    )
    if current is None or supersedes:
        if supersedes:
            _append_fact_resolution(session, supersedes, "superseded", fact_id,
                                    fact.created_by, "newer equal-or-higher confidence evidence")
        _append_fact_resolution(session, fact_id, "accepted", supersedes,
                                fact.created_by, "current immutable fact")
        execute_canonical_write(session, text(
            "INSERT INTO actor_fact_current_pointer(actor_id,topic_id,fact_key,actor_fact_id) "
            "VALUES(CAST(:actor AS uuid),CAST(:topic AS uuid),:key,CAST(:fact AS uuid)) "
            "ON CONFLICT(actor_id,topic_id,fact_key) DO UPDATE SET "
            "actor_fact_id=EXCLUDED.actor_fact_id,changed_at=now()"
        ), {"actor": fact.actor_id, "topic": fact.topic_id, "key": fact.field_key,
            "fact": fact_id})
    else:
        resolution = "pending_human_update" if state == "pending_update" else "conflict"
        _append_fact_resolution(session, fact_id, resolution, str(current["actor_fact_id"]),
                                fact.created_by, state)
        _insert_fact_review(session, fact, fact_id, str(current["actor_fact_id"]), state)
    return fact_id


def _insert_resolved_fact(session, *, fact, source_id, semantic_hash, creator_class,
                          lifecycle_state, supersedes_fact_id):
    fact_id = str(uuid.uuid4())
    execute_canonical_write(session, text(
        "INSERT INTO actor_fact (actor_fact_id,actor_id,topic_id,fact_type,fact_key,fact_value,"
        "collection_state,layer,source_id,source_origin,confidence,retrieved_at,generated_by,"
        "request_id,semantic_hash,creator_class,lifecycle_state,supersedes_fact_id) VALUES ("
        "CAST(:fact_id AS uuid),CAST(:actor_id AS uuid),CAST(:topic_id AS uuid),:fact_type,"
        ":fact_key,CAST(:fact_value AS jsonb),:collection_state,:layer,CAST(:source_id AS uuid),"
        ":source_origin,:confidence,:date_read,:created_by,CAST(:request_id AS uuid),:semantic_hash,"
        ":creator_class,:lifecycle_state,CAST(:supersedes AS uuid))"
    ), {"fact_id": fact_id, "actor_id": fact.actor_id, "topic_id": fact.topic_id,
        "fact_type": fact.fact_type, "fact_key": fact.field_key,
        "fact_value": json.dumps(fact.value, sort_keys=True, default=str)
        if fact.collection_state == "found" else None,
        "collection_state": fact.collection_state, "layer": fact.layer,
        "source_id": source_id, "source_origin": fact.source_origin,
        "confidence": fact.confidence, "date_read": fact.date_read,
        "created_by": fact.created_by, "request_id": fact.request_id,
        "semantic_hash": semantic_hash, "creator_class": creator_class,
        "lifecycle_state": lifecycle_state, "supersedes": supersedes_fact_id})
    return fact_id


def _append_fact_resolution(session, fact_id, resolution, related_id, decided_by, reason):
    execute_canonical_write(session, text(
        "INSERT INTO fact_resolution(actor_fact_id,resolution,related_actor_fact_id,decided_by,reason) "
        "VALUES(CAST(:fact AS uuid),:resolution,CAST(:related AS uuid),:by,:reason)"
    ), {"fact": fact_id, "resolution": resolution, "related": related_id,
        "by": decided_by, "reason": reason})


def _insert_fact_review(session, fact, fact_id, current_id, state):
    review_kind = "pending_update" if state == "pending_update" else "fact_conflict"
    execute_canonical_write(session, text(
        "INSERT INTO review_item(review_item_id,review_kind,entity_type,entity_id,topic_id,"
        "priority,payload,status) VALUES(CAST(:id AS uuid),:kind,'actor',CAST(:actor AS uuid),"
        "CAST(:topic AS uuid),'high',CAST(:payload AS jsonb),'pending')"
    ), {"id": str(uuid.uuid4()), "kind": review_kind, "actor": fact.actor_id,
        "topic": fact.topic_id, "payload": json.dumps({"field_key": fact.field_key,
        "new_fact_id": fact_id, "current_fact_id": current_id, "state": state}, sort_keys=True)})


def _fact_semantic_hash(fact):
    payload = {"collection_state": fact.collection_state,
               "value": fact.value if fact.collection_state == "found" else None}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     default=str).encode("utf-8")).hexdigest()


def _stored_fact_semantic_hash(fact):
    payload = {"collection_state": fact["collection_state"],
               "value": fact["fact_value"] if fact["collection_state"] == "found" else None}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     default=str).encode("utf-8")).hexdigest()


def _fact_creator_class(fact):
    creator = fact.created_by.casefold()
    return "ghus_human" if (fact.source_origin == "ghus_manual" or
                            creator.startswith(("ghus", "human", "reviewer"))) else "agent"


def _confidence_rank(value):
    return {"low": 1, "medium": 2, "high": 3}[value]


def record_verification_decision(
    session,
    *,
    entity_type: str,
    entity_ids: list[str],
    decision: str,
    decided_by: str,
    notes: str | None = None,
    rejection_reason: str | None = None,
    topic_id: str | None = None,
) -> int:
    """Append GHUS verification history; never overwrite a status column."""
    if decision == "rejected" and not str(rejection_reason or "").strip():
        raise ValueError("rejected decisions require rejection_reason")
    if not str(decided_by or "").strip():
        raise ValueError("decided_by is required")
    use_v2_actor_events = entity_type == "actor" and bool(
        session.execute(
            text("SELECT to_regclass('public.actor_verification_event') IS NOT NULL")
        ).scalar_one()
    )
    count = 0
    for entity_id in dict.fromkeys(str(value) for value in entity_ids):
        if use_v2_actor_events:
            execute_canonical_write(
                session,
                text(
                    "INSERT INTO actor_verification_event (actor_id,topic_id,decision,"
                    "decided_by,decided_at,reason,rejection_reason,decision_origin) VALUES ("
                    "CAST(:entity_id AS uuid),CAST(:topic_id AS uuid),:decision,:decided_by,"
                    "now(),:notes,:rejection_reason,'ghus_review')"
                ),
                {
                    "entity_id": entity_id,
                    "decision": decision,
                    "decided_by": decided_by,
                    "notes": notes,
                    "rejection_reason": rejection_reason,
                    "topic_id": topic_id,
                },
            )
            count += 1
            continue
        execute_canonical_write(
            session,
            text(
                "INSERT INTO record_verification (entity_type,entity_id,decision,"
                "decided_by,notes,rejection_reason,topic_id) VALUES (:entity_type,"
                "CAST(:entity_id AS uuid),:decision,:decided_by,:notes,:rejection_reason,"
                "CAST(:topic_id AS uuid))"
            ),
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "decision": decision,
                "decided_by": decided_by,
                "notes": notes,
                "rejection_reason": rejection_reason,
                "topic_id": topic_id,
            },
        )
        count += 1
    return count


def record_category_review_decision(
    session,
    *,
    review_item_id: str,
    actor_category: str,
    decided_by: str,
    reason: str | None = None,
    live: bool = False,
) -> dict[str, object]:
    """Resolve one pending category_doubt review with a GHUS-chosen category.

    A true aggregate (a bucket of organizations) is not resolved here: its
    disposition is a separate GHUS decision. Dry-run is the default.
    """
    from agents.common.actor_classification import load_category_catalog

    reviewer = str(decided_by or "").strip()
    if not reviewer:
        raise ValueError("decided_by is required")
    category = str(actor_category or "").strip()
    if category not in load_category_catalog().by_code:
        raise ValueError(f"unknown actor category {category!r}")
    item = session.execute(
        text(
            "SELECT r.review_item_id::text AS review_item_id,r.entity_id::text AS actor_id,"
            "r.status,r.payload,a.actor_category AS current_category "
            "FROM review_item r JOIN actor a ON a.actor_id=r.entity_id "
            "WHERE r.review_item_id=CAST(:id AS uuid) AND r.review_kind='category_doubt' "
            "AND r.entity_type='actor' FOR UPDATE OF r"
        ),
        {"id": review_item_id},
    ).mappings().first()
    if item is None:
        raise ValueError("category review item not found")
    payload = item["payload"] if isinstance(item["payload"], dict) else json.loads(item["payload"] or "{}")
    if payload.get("is_true_aggregate"):
        raise ValueError("a true aggregate needs a GHUS disposition, not a category")
    outcome = {
        "review_item_id": item["review_item_id"],
        "actor_id": item["actor_id"],
        "actor_category": category,
        "previous_category": item["current_category"],
    }
    if item["status"] != "pending":
        return {**outcome, "action": "already_resolved"}
    if not live:
        return {**outcome, "action": "would_resolve"}
    execute_canonical_write(session, text(
        "UPDATE actor SET actor_category=:category,category_needs_review=false,"
        "category_type=CASE WHEN actor_category IS DISTINCT FROM :category THEN NULL "
        "ELSE category_type END,"
        "category_note=:note,updated_at=now() WHERE actor_id=CAST(:actor AS uuid)"
    ), {"category": category, "actor": item["actor_id"],
        "note": str(reason or "").strip() or f"Category confirmed by GHUS review ({reviewer})."})
    execute_canonical_write(session, text(
        "INSERT INTO review_item_decision(review_item_decision_id,review_item_id,decision,"
        "decided_by,reason,decided_at) VALUES (CAST(:id AS uuid),CAST(:item AS uuid),'resolve',"
        ":by,:reason,now())"
    ), {"id": str(uuid.uuid4()), "item": item["review_item_id"], "by": reviewer,
        "reason": f"actor_category={category}" + (f"; {reason}" if reason else "")})
    execute_canonical_write(session, text(
        "UPDATE review_item SET status='resolved' WHERE review_item_id=CAST(:item AS uuid)"
    ), {"item": item["review_item_id"]})
    return {**outcome, "action": "resolved"}


def apply_hub_center_decision(
    session,
    *,
    hub_id: str,
    hub_center_review_id: str,
    decided_by: str,
) -> None:
    """Apply an explicitly approved frozen-center review through the manual writer."""
    if not str(decided_by or "").strip():
        raise ValueError("decided_by is required")
    proposal = session.execute(
        text(
            "SELECT proposed_city,proposed_state_code,proposed_latitude,proposed_longitude "
            "FROM hub_center_review WHERE hub_center_review_id=CAST(:review_id AS uuid) "
            "AND hub_id=CAST(:hub_id AS uuid) AND status='approved' FOR UPDATE"
        ),
        {"review_id": hub_center_review_id, "hub_id": hub_id},
    ).mappings().first()
    if proposal is None:
        raise ValueError("hub center review must exist and be approved")
    execute_canonical_write(
        session,
        text(
            "UPDATE hub SET center_city=:city,center_state_code=:state_code,"
            "center_latitude=:latitude,center_longitude=:longitude,center_frozen=TRUE,"
            "center_method='density_center',center_method_version='density_center_v1',"
            "center_computed_at=now(),approved_at=now(),approved_by=:decided_by "
            "WHERE hub_id=CAST(:hub_id AS uuid)"
        ),
        {
            "city": proposal["proposed_city"],
            "state_code": proposal["proposed_state_code"],
            "latitude": proposal["proposed_latitude"],
            "longitude": proposal["proposed_longitude"],
            "decided_by": decided_by,
            "hub_id": hub_id,
        },
    )


def record_hub_center_drift_review(
    session,
    *,
    hub_id: str,
    topic_id: str | None,
    proposed_city: str,
    proposed_state_code: str,
    proposed_latitude: float,
    proposed_longitude: float,
    shift_miles: float,
    threshold_miles: float,
    eligible_member_count: int,
    method_version: str = "density_center_v1",
) -> str:
    """Record a frozen-center drift proposal; never mutate the hub here."""
    center_review_id = str(uuid.uuid4())
    review_item_id = str(uuid.uuid4())
    session.execute(
        text(
            "INSERT INTO hub_center_review (hub_center_review_id,hub_id,proposed_city,"
            "proposed_state_code,proposed_latitude,proposed_longitude,shift_miles,"
            "trigger_threshold_miles,status) VALUES (CAST(:center_review_id AS uuid),"
            "CAST(:hub_id AS uuid),:city,:state_code,:latitude,:longitude,:shift_miles,"
            ":threshold_miles,'pending')"
        ),
        {
            "center_review_id": center_review_id,
            "hub_id": hub_id,
            "city": proposed_city,
            "state_code": proposed_state_code,
            "latitude": proposed_latitude,
            "longitude": proposed_longitude,
            "shift_miles": shift_miles,
            "threshold_miles": threshold_miles,
        },
    )
    session.execute(
        text(
            "INSERT INTO review_item (review_item_id,review_kind,entity_type,entity_id,topic_id,"
            "priority,payload,status) VALUES (CAST(:review_item_id AS uuid),'hub_center_drift',"
            "'hub',CAST(:hub_id AS uuid),CAST(:topic_id AS uuid),'normal',"
            "CAST(:payload AS jsonb),'pending')"
        ),
        {
            "review_item_id": review_item_id,
            "hub_id": hub_id,
            "topic_id": topic_id,
            "payload": json.dumps(
                {
                    "hub_center_review_id": center_review_id,
                    "shift_miles": shift_miles,
                    "threshold_miles": threshold_miles,
                    "eligible_member_count": eligible_member_count,
                    "method_version": method_version,
                    "deterministic_evidence": {
                        "city": proposed_city,
                        "state_code": proposed_state_code,
                        "latitude": proposed_latitude,
                        "longitude": proposed_longitude,
                    },
                },
                sort_keys=True,
            ),
        },
    )
    return review_item_id


def classify_field_candidate(
    *,
    policy: FieldPolicy,
    current_value: object,
    proposed_value: object,
    source_url: str | None,
    confidence: float,
    needs_human_review: bool = False,
) -> FieldOutcome:
    if is_gap(proposed_value):
        return FieldOutcome("no_candidate_value", "candidate did not provide a usable value")
    if not source_url or is_gap(source_url):
        return FieldOutcome("missing_source_url", "candidate has no source_url; proposal/write refused")
    if is_present(current_value):
        return FieldOutcome("propose_existing_value", "current value is non-empty; overwrite refused")
    if needs_human_review:
        return FieldOutcome("propose_human_review", "candidate requested human review")
    if policy.auto_apply_floor is None:
        return FieldOutcome("propose_no_floor", "field has no auto-apply floor")
    if confidence < policy.auto_apply_floor:
        return FieldOutcome(
            "propose_below_floor",
            f"confidence {confidence:.4f} below auto-apply floor {policy.auto_apply_floor:.4f}",
        )
    return FieldOutcome("apply", "confidence meets field auto-apply floor")


def apply_or_propose_field(
    session,
    *,
    run_id: str,
    spec: EntitySpec,
    policy: FieldPolicy,
    entity_id: str,
    field_name: str,
    proposed_value: object,
    source_url: str | None,
    confidence: float,
    reason: str,
    live: bool,
    needs_human_review: bool = False,
) -> FieldOutcome:
    _assert_identifier(spec.table_name)
    _assert_identifier(spec.id_column)
    _assert_identifier(field_name)
    if field_name not in spec.fields:
        raise ValueError(f"{field_name!r} is not a column in {spec.entity_type}")
    if not policy.enrichable:
        raise ValueError(f"{spec.entity_type}.{field_name} is not enrichable")

    current_value = _select_current_value(session, spec, entity_id, field_name, for_update=live)
    outcome = classify_field_candidate(
        policy=policy,
        current_value=current_value,
        proposed_value=proposed_value,
        source_url=source_url,
        confidence=confidence,
        needs_human_review=needs_human_review,
    )

    if outcome.action == "apply":
        if not live:
            return FieldOutcome("would_apply", outcome.reason)
        # This is the explicit last-moment guard: if another process filled the
        # gap after candidate selection, the canonical update becomes a proposal.
        latest_value = _select_current_value(session, spec, entity_id, field_name, for_update=True)
        if is_present(latest_value):
            return _write_proposal(
                session,
                run_id=run_id,
                spec=spec,
                entity_id=entity_id,
                field_name=field_name,
                proposed_value=proposed_value,
                current_value=latest_value,
                source_url=str(source_url),
                confidence=confidence,
                reason="current value was filled before write; overwrite refused",
                live=live,
                action="proposed_existing_value",
            )
        source_id = insert_source(
            session,
            source_url=str(source_url),
            fetched_at=datetime.now(UTC),
            description=f"Agent enrichment for {spec.entity_type}.{field_name}",
            source_type="agent_enrichment",
            trust_tier="candidate",
        )
        _update_canonical_gap(
            session,
            spec=spec,
            entity_id=entity_id,
            field_name=field_name,
            proposed_value=proposed_value,
            source_id=source_id,
        )
        return FieldOutcome("applied", outcome.reason, source_id=source_id)

    if outcome.action.startswith("propose_"):
        if not live:
            return FieldOutcome("would_" + outcome.action, outcome.reason)
        return _write_proposal(
            session,
            run_id=run_id,
            spec=spec,
            entity_id=entity_id,
            field_name=field_name,
            proposed_value=proposed_value,
            current_value=current_value,
            source_url=str(source_url),
            confidence=confidence,
            reason=reason or outcome.reason,
            live=live,
            action=outcome.action.replace("propose_", "proposed_"),
        )

    if outcome.action == "missing_source_url":
        logger.warning(
            "refused %s.%s enrichment for %s because source_url is missing",
            spec.entity_type,
            field_name,
            entity_id,
        )
    return outcome


def record_field_proposal(
    session,
    *,
    run_id: str,
    spec: EntitySpec,
    entity_id: str,
    field_name: str,
    proposed_value: object,
    current_value: object,
    source_url: str,
    confidence: float | None,
    reason: str,
) -> str:
    if is_gap(source_url):
        raise ValueError("field_proposal.source_url must be non-null")
    source_id = insert_source(
        session,
        source_url=source_url,
        fetched_at=datetime.now(UTC),
        description=f"Agent enrichment proposal for {spec.entity_type}.{field_name}",
        source_type="agent_enrichment",
        trust_tier="candidate",
    )
    staged_record_id = _insert_enrichment_staged_record(
        session,
        run_id=run_id,
        spec=spec,
        entity_id=entity_id,
        field_name=field_name,
        proposed_value=proposed_value,
        current_value=current_value,
        source_url=source_url,
        source_id=source_id,
        confidence=confidence,
        reason=reason,
    )
    return insert_field_proposal(
        session,
        run_id=run_id,
        staged_record_id=staged_record_id,
        source_id=source_id,
        entity_type=spec.entity_type,
        entity_id=entity_id,
        field_name=field_name,
        proposed_value=proposed_value,
        current_value=current_value,
        source_url=source_url,
        confidence=confidence,
        reason=reason,
    )


def _write_proposal(
    session,
    *,
    run_id: str,
    spec: EntitySpec,
    entity_id: str,
    field_name: str,
    proposed_value: object,
    current_value: object,
    source_url: str,
    confidence: float | None,
    reason: str,
    live: bool,
    action: str,
) -> FieldOutcome:
    if not live:
        return FieldOutcome("would_" + action, reason)
    proposal_id = record_field_proposal(
        session,
        run_id=run_id,
        spec=spec,
        entity_id=entity_id,
        field_name=field_name,
        proposed_value=proposed_value,
        current_value=current_value,
        source_url=source_url,
        confidence=confidence,
        reason=reason,
    )
    return FieldOutcome(action, reason, proposal_id=proposal_id)


def _select_current_value(session, spec: EntitySpec, entity_id: str, field_name: str, *, for_update: bool):
    suffix = " FOR UPDATE" if for_update else ""
    row = session.execute(
        text(
            f"SELECT {field_name} AS current_value "
            f"FROM {spec.table_name} "
            f"WHERE {spec.id_column} = CAST(:entity_id AS uuid)"
            f"{suffix}"
        ),
        {"entity_id": entity_id},
    ).mappings().first()
    if row is None:
        raise RuntimeError(f"{spec.entity_type} {entity_id} does not exist")
    return row["current_value"]


def _update_canonical_gap(
    session,
    *,
    spec: EntitySpec,
    entity_id: str,
    field_name: str,
    proposed_value: object,
    source_id: str,
) -> None:
    if spec.entity_type == "actor":
        _append_actor_enrichment_fact(
            session,
            actor_id=entity_id,
            field_name=field_name,
            proposed_value=proposed_value,
            source_id=source_id,
        )
        return
    set_clauses = [f"{field_name} = :value"]
    params: dict[str, object] = {
        "entity_id": entity_id,
        "value": proposed_value,
        "source_id": source_id,
        "confidence": AI_CONFIDENCE,
    }
    if spec.source_id_column:
        _assert_identifier(spec.source_id_column)
        set_clauses.append(f"{spec.source_id_column} = CAST(:source_id AS uuid)")
    if spec.verification_status_column and _has_column(
        session, spec.table_name, spec.verification_status_column
    ):
        _assert_identifier(spec.verification_status_column)
        set_clauses.append(f"{spec.verification_status_column} = 'ai_inferred'")
    if spec.confidence_column:
        _assert_identifier(spec.confidence_column)
        set_clauses.append(f"{spec.confidence_column} = :confidence")
    if spec.updated_at_column:
        _assert_identifier(spec.updated_at_column)
        set_clauses.append(f"{spec.updated_at_column} = now()")

    result = session.execute(
        text(
            f"UPDATE {spec.table_name} "
            f"SET {', '.join(set_clauses)} "
            f"WHERE {spec.id_column} = CAST(:entity_id AS uuid) "
            f"AND ({sql_gap_condition(field_name)})"
        ),
        params,
    )
    if getattr(result, "rowcount", 1) != 1:
        raise RuntimeError(
            f"refused to update {spec.entity_type}.{field_name}: gap guard matched zero rows"
        )


def _append_actor_enrichment_fact(
    session,
    *,
    actor_id: str,
    field_name: str,
    proposed_value: object,
    source_id: str,
) -> None:
    """Append an Agent 2 value to the immutable V2 ledger."""
    session.execute(
        text(
            "INSERT INTO actor_fact (actor_fact_id,actor_id,topic_id,fact_type,fact_key,"
            "fact_value,collection_state,layer,source_id,source_origin,confidence,"
            "retrieved_at,generated_by) VALUES (CAST(:fact_id AS uuid),"
            "CAST(:actor_id AS uuid),NULL,'enrichment',:fact_key,CAST(:fact_value AS jsonb),"
            "'found',2,CAST(:source_id AS uuid),'newly_found','medium',now(),'agent')"
        ),
        {
            "fact_id": str(uuid.uuid4()),
            "actor_id": actor_id,
            "fact_key": field_name,
            "fact_value": json.dumps(proposed_value, sort_keys=True, default=str),
            "source_id": source_id,
        },
    )


def _insert_enrichment_staged_record(
    session,
    *,
    run_id: str,
    spec: EntitySpec,
    entity_id: str,
    field_name: str,
    proposed_value: object,
    current_value: object,
    source_url: str,
    source_id: str,
    confidence: float | None,
    reason: str,
) -> str:
    staged_record_id = str(uuid.uuid4())
    natural_key = f"enrichment:{spec.entity_type}:{entity_id}:{field_name}"
    payload = {
        "entity_id": entity_id,
        "field_name": field_name,
        "proposed_value": proposed_value,
        "current_value": current_value,
        "source_url": source_url,
        "source_id": source_id,
        "confidence": confidence,
        "reason": reason,
    }
    row = session.execute(
        text(
            "INSERT INTO staged_record (staged_record_id, run_id, raw_document_id, "
            "entity_type, natural_key, source_url, prompt_version, extracted_at, "
            "payload, normalized_payload, status, target_entity_id) "
            "VALUES (CAST(:staged_record_id AS uuid), CAST(:run_id AS uuid), NULL, "
            ":entity_type, :natural_key, :source_url, :prompt_version, :extracted_at, "
            "CAST(:payload AS jsonb), CAST(:payload AS jsonb), 'proposed', "
            "CAST(:entity_id AS uuid)) "
            "ON CONFLICT (run_id, entity_type, natural_key) DO UPDATE SET "
            "source_url = EXCLUDED.source_url, payload = EXCLUDED.payload, "
            "normalized_payload = EXCLUDED.normalized_payload, updated_at = now() "
            "RETURNING staged_record_id::text"
        ),
        {
            "staged_record_id": staged_record_id,
            "run_id": run_id,
            "entity_type": spec.entity_type,
            "natural_key": natural_key,
            "source_url": source_url,
            "prompt_version": "enrichment_v1",
            "extracted_at": datetime.now(UTC),
            "payload": json.dumps(payload, sort_keys=True, default=str),
            "entity_id": entity_id,
        },
    ).scalar_one()
    return str(row)


def _has_column(session, table: str, column: str) -> bool:
    """True when the column still exists (legacy status columns go at the V2 cutover)."""
    return bool(session.execute(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
        "AND table_name=:table AND column_name=:column)"
    ), {"table": table, "column": column}).scalar())


def _assert_identifier(value: str) -> None:
    if not _IDENTIFIER_RE.match(value):
        raise ValueError(f"unsafe SQL identifier: {value!r}")
