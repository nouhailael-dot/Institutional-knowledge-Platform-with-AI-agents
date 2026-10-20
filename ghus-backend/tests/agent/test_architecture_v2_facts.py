"""Minimum immutable fact foundation required by Phase 9 and Phase 10."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from agents.common.facts import ActorFactWrite, validate_actor_fact
from agents.enrichment.decisions import append_actor_fact


def _fact(**changes):
    values = {
        "actor_id": "00000000-0000-0000-0000-000000000001",
        "topic_id": "00000000-0000-0000-0000-000000000002",
        "field_key": "primary_technical_focus",
        "fact_type": "light_pull",
        "layer": 1,
        "value": "Battery recycling",
        "collection_state": "found",
        "source_url": "https://example.org/research",
        "source_origin": "newly_found",
        "date_read": datetime(2026, 10, 5, tzinfo=UTC),
        "confidence": "medium",
        "created_by": "phase9-light-pull",
    }
    values.update(changes)
    return ActorFactWrite(**values)


def test_complete_fact_contract_is_validated():
    fact = validate_actor_fact(_fact())
    assert fact.field_key == "primary_technical_focus"
    assert fact.layer == 1
    assert fact.source_origin == "newly_found"
    assert fact.date_read.tzinfo is not None


@pytest.mark.parametrize("state", ["not_found", "not_yet_collected"])
def test_explicit_empty_states_require_null_value(state):
    assert validate_actor_fact(_fact(collection_state=state, value=None)).collection_state == state
    with pytest.raises(ValueError, match="null value"):
        validate_actor_fact(_fact(collection_state=state, value="invented"))


@pytest.mark.parametrize("field,value,match", [
    ("topic_id", None, "UUID"),
    ("source_url", "not-a-url", "HTTP"),
    ("confidence", "certain", "confidence"),
    ("layer", 4, "layer"),
    ("created_by", "", "created_by"),
])
def test_incomplete_or_uncontrolled_fact_is_rejected(field, value, match):
    with pytest.raises(ValueError, match=match):
        validate_actor_fact(_fact(**{field: value}))


def test_fact_writer_is_dry_run_by_default():
    class RefuseSession:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("dry-run must not touch the database")

    assert append_actor_fact(RefuseSession(), _fact()) == "would_append"


@pytest.mark.skipif(
    not os.environ.get("V2_TEST_DATABASE_URL"),
    reason="V2_TEST_DATABASE_URL is required for isolated fact-ledger enforcement",
)
def test_isolated_fact_rows_are_append_only_and_preserve_explicit_states():
    from src.db.session import SessionLocal

    with SessionLocal() as session:
        actor_id = session.execute(text(
            "SELECT actor_id::text FROM actor ORDER BY actor_id LIMIT 1"
        )).scalar_one()
        topic_id = session.execute(text(
            "SELECT topic_id::text FROM topic ORDER BY topic_id LIMIT 1"
        )).scalar_one_or_none()
        if topic_id is None:
            topic_id = str(uuid.uuid4())
            session.execute(text(
                "INSERT INTO topic(topic_id,code,name) VALUES(CAST(:id AS uuid),:code,:name)"
            ), {"id": topic_id, "code": f"fact-{topic_id[:8]}",
                "name": f"Fact test {topic_id[:8]}"})
        ids = []
        for state, value in (
            ("found", {"summary": "Evidence-backed value"}),
            ("not_found", None),
            ("not_yet_collected", None),
        ):
            ids.append(append_actor_fact(session, _fact(
                actor_id=actor_id,
                topic_id=topic_id,
                field_key=f"foundation_{state}",
                value=value,
                collection_state=state,
                source_url=f"https://example.org/{state}",
                date_read=datetime.now(UTC),
            ), live=True))
        rows = session.execute(text(
            "SELECT actor_fact_id::text,collection_state,fact_value,layer,confidence,"
            "generated_by FROM actor_fact WHERE actor_fact_id=ANY(CAST(:ids AS uuid[])) "
            "ORDER BY collection_state"
        ), {"ids": ids}).all()
        assert len(rows) == 3
        assert {row.collection_state for row in rows} == {
            "found", "not_found", "not_yet_collected"
        }
        assert all(row.layer == 1 and row.confidence == "medium" for row in rows)
        assert all(row.generated_by == "phase9-light-pull" for row in rows)

        with pytest.raises(DBAPIError, match="append-only"), session.begin_nested():
            session.execute(text(
                "UPDATE actor_fact SET confidence='high' "
                "WHERE actor_fact_id=CAST(:id AS uuid)"
            ), {"id": ids[0]})
        with pytest.raises(DBAPIError, match="append-only"), session.begin_nested():
            session.execute(text(
                "DELETE FROM actor_fact WHERE actor_fact_id=CAST(:id AS uuid)"
            ), {"id": ids[0]})
        session.rollback()
