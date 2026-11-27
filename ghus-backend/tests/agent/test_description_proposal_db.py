"""A better description goes to Review and replaces the record only on acceptance (25 Nov 2026).

Runs on a local copy of production (V2_TEST_DATABASE_URL, a *_test database), inside
a transaction that is rolled back.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from agents.enrichment.decisions import propose_description, record_fact_review_decision

DB = os.environ.get("V2_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB, reason="V2_TEST_DATABASE_URL is required")
PROPOSED = ("The Example Institute is a research center that studies critical minerals and runs "
            "a workforce program with community colleges, according to its own pages.")


@pytest.fixture
def session():
    parts = urlsplit(DB.replace("postgresql+psycopg://", "postgresql://"))
    assert parts.hostname in {"127.0.0.1", "localhost"} and parts.path.rstrip("/").endswith("_test")
    engine = create_engine(DB)
    connection = engine.connect()
    outer = connection.begin()
    s = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield s
    finally:
        s.close()
        outer.rollback()
        connection.close()
        engine.dispose()


def _actor(session):
    from agents.common.topics import topic_rows

    # Any sector id serves as the fact's topic: before 820 the topic table, after it the
    # thematic sectors that carry the same ids (topic_rows reads whichever exists).
    row = session.execute(text(
        "SELECT a.actor_id::text AS actor_id, a.description, "
        f"(SELECT t.topic_id FROM {topic_rows(session)} t ORDER BY t.code LIMIT 1)::text AS topic_id "
        "FROM actor a "
        "WHERE a.merged_into_actor_id IS NULL AND length(coalesce(a.description, '')) < 120 "
        "AND NOT EXISTS (SELECT 1 FROM review_item ri WHERE ri.entity_id = a.actor_id "
        "  AND ri.review_kind = 'pending_update' AND ri.status = 'pending' "
        "  AND ri.payload->>'field_key' = 'description') LIMIT 1")).mappings().first()
    if row is None:
        pytest.skip("this copy has no organization with a short description")
    return dict(row)


def _propose(session, actor):
    return propose_description(
        session, actor_id=actor["actor_id"], topic_id=actor["topic_id"], text_value=PROPOSED,
        source_url="https://example.org/about",
        quotes=[{"url": "https://example.org/about", "quote": "a research center"}],
        weakness="The description is only 3 words.", date_read=datetime.now(UTC), live=True)


def test_the_proposal_waits_in_review_and_changes_nothing(session):
    actor = _actor(session)
    out = _propose(session, actor)
    assert out["action"] == "proposed"
    item = session.execute(text(
        "SELECT review_kind, status, payload FROM review_item WHERE review_item_id = CAST(:i AS uuid)"),
        {"i": out["review_item_id"]}).mappings().one()
    assert (item["review_kind"], item["status"]) == ("pending_update", "pending")
    assert item["payload"]["field_key"] == "description"
    assert item["payload"]["current_text"] == (" ".join((actor["description"] or "").split()) or None)
    now = session.execute(text("SELECT description FROM actor WHERE actor_id = CAST(:a AS uuid)"),
                          {"a": actor["actor_id"]}).scalar()
    assert now == actor["description"]
    # Never twice at a time.
    assert _propose(session, actor)["action"] == "already_proposed"


def test_accepting_replaces_the_description(session):
    actor = _actor(session)
    out = _propose(session, actor)
    decided = record_fact_review_decision(session, review_item_id=out["review_item_id"],
                                          decided_by="test-reviewer", accept=True, live=True)
    assert decided["action"] == "decided" and decided["decision"] == "use_new_value"
    now = session.execute(text("SELECT description FROM actor WHERE actor_id = CAST(:a AS uuid)"),
                          {"a": actor["actor_id"]}).scalar()
    assert now == PROPOSED
    status = session.execute(text("SELECT status FROM review_item WHERE review_item_id = CAST(:i AS uuid)"),
                             {"i": out["review_item_id"]}).scalar()
    assert status == "approved"


def test_keeping_the_current_one_changes_nothing(session):
    actor = _actor(session)
    out = _propose(session, actor)
    decided = record_fact_review_decision(session, review_item_id=out["review_item_id"],
                                          decided_by="test-reviewer", accept=False, live=True)
    assert decided["decision"] == "keep_current_value"
    now = session.execute(text("SELECT description FROM actor WHERE actor_id = CAST(:a AS uuid)"),
                          {"a": actor["actor_id"]}).scalar()
    assert now == actor["description"]


def test_a_description_edited_meanwhile_is_not_overwritten(session):
    actor = _actor(session)
    out = _propose(session, actor)
    session.execute(text("UPDATE actor SET description = 'Edited by a person meanwhile.' "
                         "WHERE actor_id = CAST(:a AS uuid)"), {"a": actor["actor_id"]})
    with pytest.raises(ValueError, match="changed after this proposal"):
        record_fact_review_decision(session, review_item_id=out["review_item_id"],
                                    decided_by="test-reviewer", accept=True, live=True)
