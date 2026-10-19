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


SECTOR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,19}$")


def sector_code_for(name: str) -> str:
    """A short code from a sector name: 'Water Technology' -> 'WATER_TECHNOLOGY'."""
    words = [w for w in re.findall(r"[A-Za-z0-9]+", name or "")
             if w.lower() not in {"and", "of", "the", "for"}]
    code = "_".join(w.upper() for w in words[:2])[:20].rstrip("_")
    return code if SECTOR_CODE.match(code or "") else ""


def create_sector(
    session,
    *,
    name: str,
    created_by: str,
    code: str | None = None,
    description: str | None = None,
) -> dict[str, object]:
    """Add a GHUS sector, and its topic, when a real actor fits none of them.

    Topics mirror sectors one-to-one (same code). That is what lets a new
    sector be chosen in Review, requested on the Discovery page and used as a
    hub dimension. Both rows are reference data written only here. A sector
    that already exists (by code or name) is returned, never duplicated.
    """
    name = " ".join(str(name or "").split())
    if not 2 <= len(name) <= 80:
        raise ValueError("a sector name must be 2 to 80 characters")
    if not str(created_by or "").strip():
        raise ValueError("created_by is required: a sector is a GHUS decision")
    explicit = bool(str(code or "").strip())
    code = (code or sector_code_for(name)).strip().upper()
    if not SECTOR_CODE.match(code):
        raise ValueError("a sector code must be 2-20 capital letters, digits or _")
    # The same sector is found by its name first. A code made FROM the name is
    # cut to 20 characters, so two different names can produce the same code
    # ("Water Technology ab12cd" -> WATER_TECHNOLOGY): that is a collision to
    # avoid, never a match. Only a code the caller gave identifies a sector.
    existing = session.execute(text(
        "SELECT sector_id::text AS sector_id, code, name FROM sector "
        "WHERE lower(name) = lower(:name) OR (:explicit AND upper(code) = :code) "
        "ORDER BY (lower(name) = lower(:name)) DESC LIMIT 1"
    ), {"code": code, "name": name, "explicit": explicit}).mappings().first()
    if existing:
        return {**dict(existing), "created": False}
    taken = set(session.execute(text(
        "SELECT upper(code) FROM sector WHERE upper(code) LIKE :prefix"
    ), {"prefix": f"{code[:17]}%"}).scalars())
    if code in taken:
        code = next(f"{code[:17]}_{n}" for n in range(2, 1000) if f"{code[:17]}_{n}" not in taken)
    note = (description or "").strip() or None
    sector_id = execute_canonical_write(
        session,
        text(
            "INSERT INTO sector (code, name, description, is_thematic, active) "
            "VALUES (:code, :name, :description, true, true) RETURNING sector_id::text"
        ),
        {"code": code, "name": name,
         "description": note or f"Added by {created_by} in Review for a discovered actor."},
    ).scalar_one()
    execute_canonical_write(
        session,
        text(
            "INSERT INTO topic (code, name, description, active) VALUES (:code, :name, "
            ":description, true) ON CONFLICT DO NOTHING"
        ),
        {"code": code, "name": name, "description": note or f"Topic for the {name} sector."},
    )
    return {"sector_id": sector_id, "code": code, "name": name, "created": True}


AGENT_VERIFIER = "discovery-agent"


def record_agent_auto_verification(
    session,
    *,
    actor_id: str,
    topic_id: str | None,
    reason: str,
) -> None:
    """Verify an actor the discovery agent ACCEPTED (score and every gate).

    Decision 2026-10-14: accepted discovery candidates are created Verified.
    The event is labelled ``agent_auto_accept`` and carries the agent's reasons,
    so it can never be mistaken for a person's decision, and a person can still
    reject the actor later in Review. Verify only: an agent never rejects.
    """
    if not str(reason or "").strip():
        raise ValueError("an agent verification must state its reasons")
    execute_canonical_write(
        session,
        text(
            "INSERT INTO actor_verification_event (actor_id,topic_id,decision,decided_by,"
            "decided_at,reason,decision_origin) VALUES (CAST(:actor_id AS uuid),"
            "CAST(:topic_id AS uuid),'verified',:decided_by,now(),:reason,'agent_auto_accept')"
        ),
        {
            "actor_id": actor_id,
            "topic_id": topic_id,
            "decided_by": AGENT_VERIFIER,
            "reason": reason,
        },
    )


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


def _pending_review_item(session, review_item_id: str, kinds: tuple[str, ...]):
    item = session.execute(
        text(
            "SELECT review_item_id::text AS review_item_id,review_kind,entity_type,"
            "entity_id::text AS entity_id,candidate_entity_id::text AS candidate_entity_id,"
            "status,payload FROM review_item WHERE review_item_id=CAST(:id AS uuid) "
            "AND review_kind = ANY(CAST(:kinds AS text[])) FOR UPDATE"
        ),
        {"id": review_item_id, "kinds": list(kinds)},
    ).mappings().first()
    if item is None:
        raise ValueError("review item not found for this decision")
    payload = item["payload"] if isinstance(item["payload"], dict) else json.loads(item["payload"] or "{}")
    return dict(item), payload


def _close_review_item(session, review_item_id: str, *, decision: str, status: str,
                       decided_by: str, reason: str) -> None:
    execute_canonical_write(session, text(
        "INSERT INTO review_item_decision(review_item_decision_id,review_item_id,decision,"
        "decided_by,reason,decided_at) VALUES (CAST(:id AS uuid),CAST(:item AS uuid),:decision,"
        ":by,:reason,now())"
    ), {"id": str(uuid.uuid4()), "item": review_item_id, "decision": decision,
        "by": decided_by, "reason": reason})
    execute_canonical_write(session, text(
        "UPDATE review_item SET status=:status WHERE review_item_id=CAST(:item AS uuid)"
    ), {"status": status, "item": review_item_id})


def record_actor_verification_review_decision(
    session,
    *,
    review_item_id: str,
    decided_by: str,
    verified: bool,
    rejection_reason: str | None = None,
    notes: str | None = None,
    live: bool = False,
) -> dict[str, object]:
    """Record the GHUS verify/reject decision behind a ``verify_actor`` review.

    The actor's status is projected from the appended verification event, never
    written directly. A verification is topic-scoped: it authorizes Deep Pull for
    that actor and topic only.
    """
    reviewer = str(decided_by or "").strip()
    if not reviewer:
        raise ValueError("decided_by is required")
    if not verified and not str(rejection_reason or "").strip():
        raise ValueError("rejecting an actor requires a rejection reason")
    item, _payload = _pending_review_item(session, review_item_id, ("verify_actor",))
    topic_id = session.execute(text(
        "SELECT topic_id::text FROM review_item WHERE review_item_id=CAST(:id AS uuid)"
    ), {"id": review_item_id}).scalar()
    outcome: dict[str, object] = {
        "review_item_id": review_item_id,
        "actor_id": item["entity_id"],
        "topic_id": topic_id,
        "decision": "verified" if verified else "rejected",
    }
    if item["status"] != "pending":
        return {**outcome, "action": "already_resolved"}
    if not live:
        return {**outcome, "action": "would_decide"}
    record_verification_decision(
        session,
        entity_type="actor",
        entity_ids=[str(item["entity_id"])],
        decision="verified" if verified else "rejected",
        decided_by=reviewer,
        notes=notes,
        rejection_reason=str(rejection_reason).strip() if not verified else None,
        topic_id=topic_id,
    )
    _close_review_item(
        session, review_item_id,
        decision="approve" if verified else "reject",
        status="approved" if verified else "rejected",
        decided_by=reviewer,
        reason=("verified for this topic" if verified else f"rejected: {rejection_reason}")
        + (f"; {notes}" if notes else ""),
    )
    return {**outcome, "action": "decided"}


FACT_REVIEW_KINDS = ("fact_conflict", "pending_update")


def record_fact_review_decision(
    session,
    *,
    review_item_id: str,
    decided_by: str,
    accept: bool,
    notes: str | None = None,
    live: bool = False,
) -> dict[str, object]:
    """GHUS decides a fact conflict or a pending update raised by ``append_actor_fact``.

    ``accept`` makes the proposed fact current: the current fact is resolved
    ``superseded`` and the pointer moves. Otherwise the proposed fact is
    resolved ``rejected`` and the current one stands. Both facts stay in the
    ledger; nothing is deleted. If the current value changed after the review
    item was raised, accepting is refused rather than overwriting the newer value.
    """
    reviewer = str(decided_by or "").strip()
    if not reviewer:
        raise ValueError("decided_by is required")
    item, payload = _pending_review_item(session, review_item_id, FACT_REVIEW_KINDS)
    new_id = str(payload.get("new_fact_id") or "")
    current_id = str(payload.get("current_fact_id") or "")
    if not new_id or not current_id:
        raise ValueError("this review item does not name the two facts it compares")
    outcome: dict[str, object] = {
        "review_item_id": review_item_id, "actor_id": item["entity_id"],
        "field_key": payload.get("field_key"), "new_fact_id": new_id,
        "current_fact_id": current_id,
        "decision": "use_new_value" if accept else "keep_current_value",
    }
    if item["status"] != "pending":
        return {**outcome, "action": "already_resolved"}
    fact = session.execute(text(
        "SELECT actor_id::text AS actor_id, topic_id::text AS topic_id, fact_key "
        "FROM actor_fact WHERE actor_fact_id=CAST(:id AS uuid)"
    ), {"id": new_id}).mappings().first()
    if fact is None:
        raise ValueError("the proposed fact no longer exists")
    pointer = session.execute(text(
        "SELECT actor_fact_id::text FROM actor_fact_current_pointer WHERE "
        "actor_id=CAST(:a AS uuid) AND topic_id=CAST(:t AS uuid) AND fact_key=:k FOR UPDATE"
    ), {"a": fact["actor_id"], "t": fact["topic_id"], "k": fact["fact_key"]}).scalar()
    if accept and pointer != current_id:
        raise ValueError("the current value changed after this review was raised; "
                         "check the actor again before replacing it")
    if not live:
        return {**outcome, "action": "would_decide"}
    reason = ("GHUS review: use the new value" if accept else
              "GHUS review: keep the current value") + (f"; {notes}" if notes else "")
    if accept:
        _append_fact_resolution(session, current_id, "superseded", new_id, reviewer, reason)
        _append_fact_resolution(session, new_id, "accepted", current_id, reviewer, reason)
        execute_canonical_write(session, text(
            "UPDATE actor_fact_current_pointer SET actor_fact_id=CAST(:fact AS uuid),"
            "changed_at=now() WHERE actor_id=CAST(:a AS uuid) AND topic_id=CAST(:t AS uuid) "
            "AND fact_key=:k"
        ), {"fact": new_id, "a": fact["actor_id"], "t": fact["topic_id"], "k": fact["fact_key"]})
    else:
        _append_fact_resolution(session, new_id, "rejected", current_id, reviewer, reason)
    _close_review_item(session, review_item_id, decision="approve" if accept else "reject",
                       status="approved" if accept else "rejected", decided_by=reviewer,
                       reason=reason)
    return {**outcome, "action": "decided"}


def propose_actor_relationship(
    session,
    *,
    subject_actor_id: str,
    object_actor_id: str,
    relationship_type: str,
    source_url: str,
    topic_id: str | None = None,
    request_id: str | None = None,
    live: bool = False,
) -> dict[str, object]:
    """Ask GHUS to confirm a relationship an actor update read on a page.

    Raises a ``relationship_review`` item; the edge itself is written only when
    a person approves it (``record_relationship_review_decision``). Not raised
    twice: an existing edge or a pending proposal for the same pair and type is
    reported instead.
    """
    validate_entity_edge(EntityEdgeRequest(
        subject_type="actor", subject_id=subject_actor_id, relationship_type=relationship_type,
        object_type="actor", object_id=object_actor_id,
        source_id="00000000-0000-0000-0000-000000000000", confidence="medium"))
    pair = {"subject": subject_actor_id, "object": object_actor_id, "type": relationship_type}
    linked = session.execute(text(
        "SELECT count(*) FROM entity_edge WHERE subject_type='actor' AND object_type='actor' "
        "AND subject_id=CAST(:subject AS uuid) AND object_id=CAST(:object AS uuid) "
        "AND relationship_type=:type"), pair).scalar()
    if linked:
        return {"action": "already_linked"}
    pending = session.execute(text(
        "SELECT review_item_id::text FROM review_item WHERE review_kind='relationship_review' "
        "AND status='pending' AND payload->>'subject_actor_id'=:subject "
        "AND payload->>'object_actor_id'=:object "
        "AND payload->>'proposed_relationship_type'=:type LIMIT 1"), pair).scalar()
    if pending:
        return {"action": "already_proposed", "review_item_id": pending}
    if not live:
        return {"action": "would_propose"}
    review_id = str(uuid.uuid4())
    execute_canonical_write(session, text(
        "INSERT INTO review_item(review_item_id,review_kind,entity_type,entity_id,"
        "candidate_entity_id,topic_id,priority,payload,status) VALUES(CAST(:id AS uuid),"
        "'relationship_review','actor',CAST(:subject AS uuid),CAST(:object AS uuid),"
        "CAST(:topic AS uuid),'normal',CAST(:payload AS jsonb),'pending')"
    ), {"id": review_id, "subject": subject_actor_id, "object": object_actor_id,
        "topic": topic_id, "payload": json.dumps({
            "subject_actor_id": subject_actor_id, "object_actor_id": object_actor_id,
            "proposed_relationship_type": relationship_type, "source_url": source_url,
            "origin": "actor_update", "request_id": request_id}, sort_keys=True)})
    return {"action": "proposed", "review_item_id": review_id}


def propose_hub_membership(
    session,
    *,
    actor_id: str,
    hub_id: str,
    distance_miles: float | None,
    radius_miles: float,
    sector_code: str | None,
    topic_id: str | None = None,
    live: bool = False,
) -> dict[str, object]:
    """Ask GHUS to confirm that an unassigned actor now fits a hub.

    A ``hub_assignment`` item marked as a membership proposal; the membership
    is written only on acceptance (``record_hub_membership_decision``).
    """
    member = session.execute(text(
        "SELECT count(*) FROM hub_actor WHERE hub_id=CAST(:hub AS uuid) "
        "AND actor_id=CAST(:actor AS uuid)"), {"hub": hub_id, "actor": actor_id}).scalar()
    if member:
        return {"action": "already_member"}
    pending = session.execute(text(
        "SELECT review_item_id::text FROM review_item WHERE review_kind='hub_assignment' "
        "AND status='pending' AND entity_id=CAST(:actor AS uuid) "
        "AND payload->>'proposed_hub_id'=:hub LIMIT 1"), {"hub": hub_id, "actor": actor_id}).scalar()
    if pending:
        return {"action": "already_proposed", "review_item_id": pending}
    if not live:
        return {"action": "would_propose"}
    review_id = str(uuid.uuid4())
    execute_canonical_write(session, text(
        "INSERT INTO review_item(review_item_id,review_kind,entity_type,entity_id,topic_id,"
        "priority,payload,status) VALUES(CAST(:id AS uuid),'hub_assignment','actor',"
        "CAST(:actor AS uuid),CAST(:topic AS uuid),'normal',CAST(:payload AS jsonb),'pending')"
    ), {"id": review_id, "actor": actor_id, "topic": topic_id, "payload": json.dumps({
        "proposal": "membership", "proposed_hub_id": hub_id, "hub_ids": [hub_id],
        "canonical_outcome": "assigned", "issue": "newly_eligible",
        "deterministic_evidence": {"sector_code": sector_code, "distance_miles": distance_miles,
                                   "radius_miles": radius_miles},
        "origin": "actor_update"}, sort_keys=True, default=str)})
    return {"action": "proposed", "review_item_id": review_id}


def record_hub_membership_decision(
    session,
    *,
    review_item_id: str,
    decided_by: str,
    accept: bool,
    notes: str | None = None,
    live: bool = False,
) -> dict[str, object]:
    """GHUS accepts or refuses a proposed hub membership. Nothing is ever removed."""
    reviewer = str(decided_by or "").strip()
    if not reviewer:
        raise ValueError("decided_by is required")
    item, payload = _pending_review_item(session, review_item_id, ("hub_assignment",))
    if payload.get("proposal") != "membership" or not payload.get("proposed_hub_id"):
        raise ValueError("this hub review is not a membership proposal")
    hub_id = str(payload["proposed_hub_id"])
    outcome: dict[str, object] = {"review_item_id": review_item_id, "hub_id": hub_id,
                                  "actor_id": item["entity_id"],
                                  "decision": "accepted" if accept else "refused"}
    if item["status"] != "pending":
        return {**outcome, "action": "already_resolved"}
    if not live:
        return {**outcome, "action": "would_decide"}
    reason = (("membership accepted" if accept else "membership refused")
              + (f"; {notes}" if notes else ""))
    if accept:
        hub_topic = session.execute(text(
            "SELECT topic_id::text FROM hub WHERE hub_id=CAST(:hub AS uuid)"),
            {"hub": hub_id}).scalar()
        source_id = insert_source(session, source_url=None, fetched_at=None,
                                  description=f"GHUS-accepted hub membership ({reviewer})",
                                  source_type="ghus_review", trust_tier="verified")
        evidence = payload.get("deterministic_evidence") or {}
        distance = evidence.get("distance_miles")
        execute_canonical_write(session, text(
            "INSERT INTO hub_actor (hub_id,actor_id,relationship_type,is_primary,topic_id,"
            "distance_miles,assignment_outcome,outside_radius,overlap_flag,source_id) VALUES "
            "(CAST(:hub AS uuid),CAST(:actor AS uuid),'reviewed_assignment',FALSE,"
            "CAST(:topic AS uuid),:distance,'assigned',CAST(:outside AS boolean),FALSE,"
            "CAST(:source AS uuid)) ON CONFLICT (hub_id,actor_id) DO NOTHING"
        ), {"hub": hub_id, "actor": item["entity_id"], "topic": hub_topic,
            "distance": distance, "outside": None if distance is None else False,
            "source": source_id})
    _close_review_item(session, review_item_id, decision="approve" if accept else "reject",
                       status="approved" if accept else "rejected", decided_by=reviewer,
                       reason=reason)
    return {**outcome, "action": "decided"}


def record_geocode_review_decision(
    session,
    *,
    review_item_id: str,
    decided_by: str,
    city: str | None = None,
    state: str | None = None,
    country: str | None = "US",
    keep_unlocated: bool = False,
    reason: str | None = None,
    live: bool = False,
) -> dict[str, object]:
    """Resolve an actor location review with a GHUS-supplied city/state.

    The location is looked up in the vendored Census gazetteer; nothing is
    guessed. When GHUS confirms the actor has no resolvable US location
    (e.g. it is abroad), the review closes with that reason and no change.
    """
    from agents.common.geography import default_gazetteer

    reviewer = str(decided_by or "").strip()
    if not reviewer:
        raise ValueError("decided_by is required")
    item, _payload = _pending_review_item(session, review_item_id, ("geocode", "geocode_failed"))
    outcome: dict[str, object] = {"review_item_id": review_item_id, "actor_id": item["entity_id"]}
    if item["status"] != "pending":
        return {**outcome, "action": "already_resolved"}
    if keep_unlocated:
        note = str(reason or "").strip()
        if not note:
            raise ValueError("keeping an actor unlocated requires a reason")
        if live:
            _close_review_item(session, review_item_id, decision="resolve", status="resolved",
                               decided_by=reviewer, reason=f"kept unlocated: {note}")
        return {**outcome, "action": "kept_unlocated" if live else "would_keep_unlocated"}
    result = default_gazetteer().lookup(city, state, country or "US")
    if not result.found:
        raise ValueError(f"location not found in the Census gazetteer ({result.reason}); "
                         "correct the city/state or keep the actor unlocated with a reason")
    outcome.update({"city": result.city, "state_code": result.state_code,
                    "region_code": result.region_code, "latitude": result.latitude,
                    "longitude": result.longitude})
    if not live:
        return {**outcome, "action": "would_locate"}
    city_column = "city" if _has_column(session, "actor", "city") else "location_city"
    execute_canonical_write(session, text(
        f"UPDATE actor SET {city_column}=:city,state_code=:state_code,region_code=:region_code,"
        "country='US',latitude=:latitude,longitude=:longitude,updated_at=now() "
        "WHERE actor_id=CAST(:actor AS uuid)"
    ), {**outcome, "actor": item["entity_id"]})
    _close_review_item(session, review_item_id, decision="resolve", status="resolved",
                       decided_by=reviewer,
                       reason=f"located at {result.city}, {result.state_code} (Census gazetteer)"
                       + (f"; {reason}" if reason else ""))
    return {**outcome, "action": "located"}


def record_relationship_review_decision(
    session,
    *,
    review_item_id: str,
    decided_by: str,
    approve: bool,
    source_url: str | None = None,
    relationship_type: str | None = None,
    reason: str | None = None,
    live: bool = False,
) -> dict[str, object]:
    """Approve (with a source) or reject an unsourced legacy relationship."""
    from urllib.parse import urlsplit

    reviewer = str(decided_by or "").strip()
    if not reviewer:
        raise ValueError("decided_by is required")
    item, payload = _pending_review_item(session, review_item_id, ("relationship_review",))
    outcome: dict[str, object] = {"review_item_id": review_item_id}
    if item["status"] != "pending":
        return {**outcome, "action": "already_resolved"}
    if not approve:
        if live:
            _close_review_item(session, review_item_id, decision="reject", status="rejected",
                               decided_by=reviewer,
                               reason=str(reason or "").strip() or "relationship not confirmed")
        return {**outcome, "action": "rejected" if live else "would_reject"}
    url = str(source_url or "").strip()
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("approving a relationship requires the http(s) URL of its source")
    request = EntityEdgeRequest(
        subject_type="actor",
        subject_id=str(payload.get("subject_actor_id") or item["entity_id"]),
        relationship_type=str(relationship_type or payload.get("proposed_relationship_type")
                              or "unit_of"),
        object_type="actor",
        object_id=str(payload.get("object_actor_id") or item["candidate_entity_id"]),
        source_id="00000000-0000-0000-0000-000000000000",
        confidence="high",
    )
    validate_entity_edge(request)
    if not live:
        return {**outcome, "action": "would_approve"}
    source_id = insert_source(session, source_url=url, fetched_at=None,
                              description=f"GHUS-confirmed relationship ({reviewer})",
                              source_type="ghus_review", trust_tier="verified")
    edge_id = append_entity_edge(session, EntityEdgeRequest(**{**request.__dict__,
                                                               "source_id": source_id}), live=True)
    _close_review_item(session, review_item_id, decision="approve", status="approved",
                       decided_by=reviewer,
                       reason=f"{request.relationship_type} confirmed with source {url}"
                       + (f"; {reason}" if reason else ""))
    return {**outcome, "action": "approved", "entity_edge_id": edge_id}


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
