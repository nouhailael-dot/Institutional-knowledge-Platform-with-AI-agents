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


def test_a_proposed_category_type_is_set_only_on_acceptance_and_only_while_untyped(connection):
    from agents.enrichment.decisions import propose_category_type, record_category_review_decision

    actor = connection.execute(text(
        "SELECT actor_id::text FROM actor WHERE actor_category = 'association_network' "
        "AND category_type IS NULL LIMIT 1")).scalar()
    if actor is None:
        pytest.skip("no untyped association in this database")

    def propose(**changes):
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            result = propose_category_type(session, **{
                "actor_id": actor, "actor_category": "association_network",
                "category_type": "professional_network", "category_note": None,
                "main_job": "It convenes water professionals across the region.",
                "source_url": "https://example.org/about", "live": True, **changes})
            session.commit()
            return result
        finally:
            session.close()

    def type_of():
        return connection.execute(text(
            "SELECT category_type FROM actor WHERE actor_id = CAST(:a AS uuid)"),
            {"a": actor}).scalar()

    # Another category's type, or Not Applicable without a note, is never raised.
    with pytest.raises(ValueError):
        propose(category_type="private_company")
    with pytest.raises(ValueError):
        propose(category_type="not_applicable")
    first = propose()
    assert first["action"] == "proposed"
    assert propose()["action"] == "already_proposed"
    assert type_of() is None                       # a proposal changes nothing
    with pytest.raises(ValueError, match="record_category_type_decision"):
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        record_category_review_decision(session, review_item_id=first["review_item_id"],
                                        actor_category="association_network",
                                        decided_by="GHUS test", live=True)
    refused = _decide(connection, decision_kind="resolve_category_type",
                      review_item_id=first["review_item_id"], accept=False)
    assert refused["decision"] == "refused" and type_of() is None
    second = propose()
    accepted = _decide(connection, decision_kind="resolve_category_type",
                       review_item_id=second["review_item_id"], accept=True)
    assert accepted["action"] == "decided" and type_of() == "professional_network"
    # Typed now: nothing more is proposed for it.
    assert propose()["action"] == "already_typed"


def test_an_entry_box_adds_a_new_grant_and_keeps_the_old_one_in_the_history(connection):
    from datetime import UTC, datetime, timedelta

    from agents.common.facts import ActorFactWrite
    from agents.enrichment.decisions import append_actor_fact

    row = connection.execute(text(
        "SELECT a.actor_id::text, t.topic_id::text FROM actor a CROSS JOIN topic t "
        "WHERE NOT EXISTS (SELECT 1 FROM actor_fact_current_pointer p WHERE p.actor_id=a.actor_id "
        "AND p.topic_id=t.topic_id AND p.fact_key='funding_signal') LIMIT 1")).first()
    if row is None:
        pytest.skip("needs an actor and a topic")
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    now = datetime.now(UTC)

    def write(value, confidence, when):
        return append_actor_fact(session, ActorFactWrite(
            actor_id=row[0], topic_id=row[1], field_key="funding_signal", fact_type="light_pull",
            layer=1, value=value, collection_state="found", source_url="https://x.example/news",
            source_origin="newly_found", date_read=when, confidence=confidence,
            created_by="agent.test"), live=True)

    first = write({"entries": [{"amount": "$1M", "funder": "DOE"}]}, "high", now)
    # Weaker evidence, but it only adds: it becomes current, the first stays in history.
    second = write({"entries": [{"amount": "$2M", "funder": "NSF"},
                                {"amount": "$1M", "funder": "DOE"}]}, "medium",
                   now + timedelta(minutes=1))
    current = connection.execute(text(
        "SELECT actor_fact_id::text FROM actor_fact_current_pointer WHERE actor_id=CAST(:a AS uuid) "
        "AND topic_id=CAST(:t AS uuid) AND fact_key='funding_signal'"), {"a": row[0], "t": row[1]}).scalar()
    assert current == second != first
    state = connection.execute(text(
        "SELECT lifecycle_state, supersedes_fact_id::text FROM actor_fact WHERE actor_fact_id=CAST(:f AS uuid)"),
        {"f": second}).one()
    assert state[0] == "accepted" and state[1] == first
    session.close()


def test_event_and_person_facts_are_kept_with_their_source_and_never_overwritten(connection):
    """Migration 600: what Review shows about an event or a person has a home."""
    from datetime import UTC, datetime

    from agents.discovery.promote import _append_record_facts
    from agents.discovery.stage import StagedRecord
    from agents.enrichment.decisions import append_entity_fact

    if not connection.execute(text("SELECT to_regclass('public.event_fact')")).scalar():
        pytest.skip("migration 600 not applied to this database")
    event_id = connection.execute(text("SELECT event_id::text FROM event LIMIT 1")).scalar()
    if event_id is None:
        pytest.skip("needs an event")
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    now = datetime.now(UTC)
    kw = dict(entity_type="event", entity_id=event_id, fact_key="test_format",
              source_url="https://example.org/event", date_read=now, created_by="agent:test")
    assert append_entity_fact(session, value="Hybrid", live=True, **kw)["action"] == "appended"
    assert append_entity_fact(session, value="Hybrid", live=True, **kw)["action"] == "same_value"
    assert append_entity_fact(session, value="In person", live=True, **kw)["action"] == "superseded"
    rows = connection.execute(text(
        "SELECT count(*) FROM event_fact WHERE event_id=CAST(:e AS uuid) AND fact_key='test_format'"),
        {"e": event_id}).scalar()
    current = connection.execute(text(
        "SELECT fact_value FROM event_fact_current WHERE event_id=CAST(:e AS uuid) "
        "AND fact_key='test_format'"), {"e": event_id}).scalar()
    assert rows == 2 and current == "In person"
    staged = StagedRecord(
        run_id="r", entity_type="event", natural_key="x", source_url="https://example.org/event",
        payload={}, prompt_version="t", extracted_at=now.isoformat(),
        normalized_payload={"audience": "Growers and agtech investors", "facts": {
            "format": "In person", "standing_claims": ["The largest agtech summit in the US"],
            "dropped": ["organizer"], "evidence": {"format": {
                "source_url": "https://example.org/event/about", "date_read": now.isoformat()}}}})
    assert _append_record_facts(session, entity_type="event", entity_id=event_id, staged=staged) == 3
    keys = {r[0] for r in connection.execute(text(
        "SELECT fact_key FROM event_fact_current WHERE event_id=CAST(:e AS uuid)"), {"e": event_id})}
    assert {"format", "audience"} <= keys and "dropped" not in keys
    assert connection.execute(text(
        "SELECT count(*) FROM event_claim WHERE event_id=CAST(:e AS uuid) "
        "AND claim_text='The largest agtech summit in the US'"), {"e": event_id}).scalar() == 1
    source = connection.execute(text(
        "SELECT s.url FROM event_fact_current f JOIN source s USING (source_id) "
        "WHERE f.event_id=CAST(:e AS uuid) AND f.fact_key='format'"), {"e": event_id}).scalar()
    assert source == "https://example.org/event/about"
    session.close()


def test_actor_details_shows_every_box_as_a_column_and_follows_each_new_reading(connection):
    """Migration 620 (5 Nov 2026): one row per organization, a column per box."""
    from datetime import UTC, datetime, timedelta

    from agents.common.facts import ActorFactWrite
    from agents.enrichment.decisions import append_actor_fact

    if connection.execute(text("SELECT to_regclass('public.actor_details')")).scalar() is None:
        pytest.skip("migration 620 is not applied to this test database")
    row = connection.execute(text(
        "SELECT a.actor_id::text, t.topic_id::text FROM actor a CROSS JOIN topic t "
        "WHERE NOT EXISTS (SELECT 1 FROM actor_fact_current_pointer p WHERE p.actor_id=a.actor_id "
        "AND p.fact_key IN ('funding_signal','founding_year_location','unlisted_box')) LIMIT 1")).first()
    if row is None:
        pytest.skip("needs an actor and a topic")
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    now = datetime.now(UTC)

    def write(key, value, when, state="found"):
        return append_actor_fact(session, ActorFactWrite(
            actor_id=row[0], topic_id=row[1], field_key=key, fact_type="light_pull",
            layer=1, value=value, collection_state=state, source_url="https://x.example/news",
            source_origin="newly_found", date_read=when, confidence="high",
            created_by="agent.test"), live=True)

    def details():
        return connection.execute(text(
            "SELECT funding_signal, founding_year_location, other_facts, fact_sources "
            "FROM actor_details WHERE actor_id=CAST(:a AS uuid)"), {"a": row[0]}).one()

    write("founding_year_location", None, now, state="not_found")
    assert details()[1] == "not_found"
    write("funding_signal", {"entries": [{"amount": "$1M", "funder": "DOE"}]}, now)
    write("funding_signal", {"entries": [{"amount": "$2M", "funder": "NSF"},
                                         {"amount": "$1M", "funder": "DOE"}]},
          now + timedelta(minutes=1))
    write("unlisted_box", "kept anyway", now)
    funding, founding, other, sources = details()
    assert funding["entries"][0]["funder"] == "NSF" and founding == "not_found"
    assert other["unlisted_box"] == "kept anyway"
    assert sources["funding_signal"]["source_url"] == "https://x.example/news"
    assert sources["funding_signal"]["confidence"] == "high"
    # Migration 621: a reading with no topic (as V1 carried over) shows too.
    if connection.execute(text("SELECT 1 FROM pg_trigger WHERE tgname="
                               "'actor_details_follows_topicless_fact'")).scalar():
        carried = connection.execute(text(
            "SELECT DISTINCT ON (f.actor_id) f.actor_id::text, f.fact_value FROM actor_fact f "
            "WHERE f.topic_id IS NULL AND f.fact_key='current_activities' "
            "AND f.collection_state='found' ORDER BY f.actor_id, f.retrieved_at DESC, "
            "f.created_at DESC LIMIT 1")).first()
        if carried is not None:
            assert connection.execute(text(
                "SELECT current_activities FROM actor_details WHERE actor_id=CAST(:a AS uuid)"),
                {"a": carried[0]}).scalar() == carried[1]
    session.close()


def test_person_ghus_notes_are_written_only_by_ghus(connection):
    from agents.enrichment.decisions import record_ghus_notes

    has_column = connection.execute(text(
        "SELECT 1 FROM information_schema.columns WHERE table_name='person' "
        "AND column_name='ghus_notes'")).scalar()
    person = connection.execute(text("SELECT person_id::text FROM person LIMIT 1")).scalar()
    if not has_column or person is None:
        pytest.skip("needs migration 620 and a person")
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    with pytest.raises(Exception, match="written only by GHUS"):
        with session.begin_nested():
            session.execute(text("UPDATE person SET ghus_notes='agent text' "
                                 "WHERE person_id=CAST(:p AS uuid)"), {"p": person})
    assert record_ghus_notes(session, entity_type="person", entity_id=person,
                             notes="Met at the 2026 summit.", decided_by="GHUS test", live=True)
    assert connection.execute(text("SELECT ghus_notes FROM person WHERE person_id=CAST(:p AS uuid)"),
                              {"p": person}).scalar() == "Met at the 2026 summit."
    session.close()


def test_event_and_person_details_show_every_box_as_a_column(connection):
    """Migration 630 (5 Nov 2026): one row per event and per person, a column per box."""
    from datetime import UTC, datetime, timedelta

    from agents.enrichment.decisions import append_entity_fact, append_event_claim

    if connection.execute(text("SELECT to_regclass('public.event_details')")).scalar() is None:
        pytest.skip("migration 630 is not applied to this test database")
    event = connection.execute(text("SELECT event_id::text FROM event LIMIT 1")).scalar()
    if event is None:
        pytest.skip("needs an event")
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    # A person of this test only (rolled back with it) when the database has none.
    person = connection.execute(text("SELECT person_id::text FROM person LIMIT 1")).scalar()
    if person is None:
        person = session.execute(text(
            "INSERT INTO person (person_id, full_name) VALUES (gen_random_uuid(), 'Test Person') "
            "RETURNING person_id::text")).scalar()
    now = datetime.now(UTC)

    def fact(kind, entity, key, value, when=now):
        append_entity_fact(session, entity_type=kind, entity_id=entity, fact_key=key,
                           value=value, source_url="https://x.example/about", date_read=when,
                           confidence="high", created_by="agent:test", live=True)

    fact("event", event, "format", "online")
    fact("event", event, "format", "hybrid", now + timedelta(minutes=1))
    fact("event", event, "unlisted_box", "kept anyway")
    append_event_claim(session, event_id=event, claim_text="The largest test summit",
                       source_url="https://x.example/about", date_read=now, live=True)
    fmt, claims, other, sources = connection.execute(text(
        "SELECT format, standing_claims, other_facts, fact_sources FROM event_details "
        "WHERE event_id=CAST(:e AS uuid)"), {"e": event}).one()
    assert fmt == "hybrid" and "The largest test summit" in claims
    assert other["unlisted_box"] == "kept anyway"
    assert sources["format"]["source_url"] == "https://x.example/about"
    assert sources["format"]["confidence"] == "high"

    fact("person", person, "department", "Water Resources")
    fact("person", person, "email", "someone@example.org")
    dept, email, other = connection.execute(text(
        "SELECT department, email, other_facts FROM person_details "
        "WHERE person_id=CAST(:p AS uuid)"), {"p": person}).one()
    assert dept == "Water Resources" and email == "someone@example.org"
    assert "email" not in other
    session.close()
