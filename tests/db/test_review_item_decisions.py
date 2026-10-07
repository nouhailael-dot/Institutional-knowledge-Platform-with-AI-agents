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
