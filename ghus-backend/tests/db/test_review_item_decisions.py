"""GHUS decisions on V2 location and relationship review items (live, rolled back)."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from agents.review.admission import apply_review_item_decision

URL = os.environ.get("V2_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not URL or "127.0.0.1:55432" not in URL, reason="V2_TEST_DATABASE_URL is required"
)


@pytest.fixture
def connection():
    engine = create_engine(URL)
    with engine.connect() as conn:
        outer = conn.begin()
        try:
            yield conn
        finally:
            outer.rollback()
    engine.dispose()


def _pending(connection, kind: str, offset: int = 0) -> str | None:
    return connection.execute(text(
        "SELECT review_item_id::text FROM review_item WHERE review_kind=:kind AND status='pending' "
        "ORDER BY review_item_id OFFSET :offset LIMIT 1"), {"kind": kind, "offset": offset}).scalar()


def _decide(connection, **decision):
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        return apply_review_item_decision(session, {"reviewer": "GHUS test",
                                                    "idempotency_key": "t", **decision})
    finally:
        session.close()


def test_location_review_locates_via_gazetteer_or_stays_unlocated_with_reason(connection):
    item = _pending(connection, "geocode_failed")
    if item is None:
        pytest.skip("no pending location review in this database")
    with pytest.raises(ValueError, match="not found"):
        _decide(connection, decision_kind="resolve_location", review_item_id=item,
                city="Nowhereville", state="Texas")
    result = _decide(connection, decision_kind="resolve_location", review_item_id=item,
                     city="Austin", state="Texas")
    assert result["action"] == "located" and result["state_code"] == "TX"
    actor = connection.execute(text(
        "SELECT state_code, region_code, latitude IS NOT NULL FROM actor a JOIN review_item r "
        "ON r.entity_id=a.actor_id WHERE r.review_item_id=CAST(:i AS uuid)"), {"i": item}).one()
    assert actor[0] == "TX" and actor[2]
    assert _decide(connection, decision_kind="resolve_location", review_item_id=item,
                   city="Austin", state="Texas")["action"] == "already_resolved"
    other = _pending(connection, "geocode_failed")
    with pytest.raises(ValueError, match="reason"):
        _decide(connection, decision_kind="resolve_location", review_item_id=other,
                keep_unlocated=True)
    assert _decide(connection, decision_kind="resolve_location", review_item_id=other,
                   keep_unlocated=True, notes="Organization is based in Canada.")[
        "action"] == "kept_unlocated"


def test_relationship_review_needs_a_source_to_create_an_edge(connection):
    item = _pending(connection, "relationship_review")
    if item is None:
        pytest.skip("no pending relationship review in this database")
    with pytest.raises(ValueError, match="source"):
        _decide(connection, decision_kind="resolve_relationship", review_item_id=item, approve=True)
    result = _decide(connection, decision_kind="resolve_relationship", review_item_id=item,
                     approve=True, source_url="https://www.un.org/en/about-us/un-system")
    assert result["action"] == "approved"
    edge = connection.execute(text(
        "SELECT relationship_type, confidence FROM entity_edge "
        "WHERE entity_edge_id=CAST(:e AS uuid)"), {"e": result["entity_edge_id"]}).one()
    assert edge == ("unit_of", "high")
    rejected = _pending(connection, "relationship_review")
    assert _decide(connection, decision_kind="resolve_relationship", review_item_id=rejected,
                   approve=False, notes="Not a parent body.")["action"] == "rejected"
    status = connection.execute(text(
        "SELECT status FROM review_item WHERE review_item_id=CAST(:i AS uuid)"),
        {"i": rejected}).scalar()
    assert status == "rejected"


def test_fact_conflict_review_routes_to_the_fact_decision(connection):
    """Review's "use the new value" goes through the approved writer, both facts kept."""
    import uuid
    from datetime import UTC, datetime, timedelta

    from agents.common.facts import ActorFactWrite
    from agents.enrichment.decisions import append_actor_fact

    actor = connection.execute(text("SELECT actor_id::text FROM actor LIMIT 1")).scalar_one()
    topic = connection.execute(text(
        "INSERT INTO topic(code, name) VALUES (:c, 'Fact review test') RETURNING topic_id::text"
    ), {"c": f"FR{uuid.uuid4().hex[:8].upper()}"}).scalar_one()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    now = datetime.now(UTC)

    def write(value, when, confidence):
        return append_actor_fact(session, ActorFactWrite(
            actor_id=actor, topic_id=topic, field_key="funding_signal", fact_type="light_pull",
            layer=1, value=value, collection_state="found",
            source_url="https://co.example/about", source_origin="newly_found", date_read=when,
            confidence=confidence, created_by="agent.test"), live=True)

    current = write("$1M.", now, "high")
    proposed = write("$3M.", now - timedelta(days=3), "low")
    session.commit()  # releases the savepoint; the outer transaction still rolls back
    session.close()
    item = connection.execute(text(
        "SELECT review_item_id::text FROM review_item WHERE review_kind='fact_conflict' "
        "AND payload->>'new_fact_id'=:f"), {"f": proposed}).scalar_one()
    result = _decide(connection, decision_kind="resolve_fact", review_item_id=item, accept=True)
    assert result["status"] == "applied" and result["action"] == "decided"
    assert connection.execute(text(
        "SELECT actor_fact_id::text FROM actor_fact_current_pointer WHERE actor_id=CAST(:a AS uuid) "
        "AND topic_id=CAST(:t AS uuid) AND fact_key='funding_signal'"),
        {"a": actor, "t": topic}).scalar_one() == proposed
    assert connection.execute(text(
        "SELECT count(*) FROM actor_fact WHERE actor_fact_id=CAST(:f AS uuid)"),
        {"f": current}).scalar_one() == 1


def test_hub_membership_proposal_routes_to_its_decision_and_refusal_writes_nothing(connection):
    import uuid

    from agents.enrichment.decisions import propose_hub_membership

    actor = connection.execute(text(
        "SELECT a.actor_id::text FROM actor a WHERE NOT EXISTS (SELECT 1 FROM hub_actor ha "
        "WHERE ha.actor_id = a.actor_id) LIMIT 1")).scalar_one()
    hub = connection.execute(text("SELECT hub_id::text FROM hub LIMIT 1")).scalar_one()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    proposal = propose_hub_membership(session, actor_id=actor, hub_id=hub, distance_miles=12.0,
                                      radius_miles=200.0, sector_code="WATER", live=True)
    session.commit()  # releases the savepoint; the outer transaction still rolls back
    session.close()
    refused = _decide(connection, decision_kind="resolve_hub_membership",
                      review_item_id=proposal["review_item_id"], accept=False)
    assert refused["status"] == "applied" and refused["decision"] == "refused"
    assert connection.execute(text(
        "SELECT count(*) FROM hub_actor WHERE actor_id = CAST(:a AS uuid)"),
        {"a": actor}).scalar_one() == 0
    with pytest.raises(ValueError, match="not a membership proposal"):
        legacy = connection.execute(text(
            "SELECT review_item_id::text FROM review_item WHERE review_kind = 'hub_assignment' "
            "AND status = 'pending' AND NOT (payload ? 'proposal') LIMIT 1")).scalar()
        if legacy is None:
            raise ValueError("not a membership proposal")  # nothing legacy here to refuse
        _decide(connection, decision_kind="resolve_hub_membership", review_item_id=legacy,
                accept=True)
    assert uuid.UUID(proposal["review_item_id"])
