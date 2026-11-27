"""Re-review (25 Nov 2026): park every verified record, then verify or reject each one.

Runs on a local copy of production (V2_TEST_DATABASE_URL, a *_test database), inside
a transaction that is rolled back.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from agents.enrichment.decisions import (
    park_for_rereview,
    record_directory_verification,
    restore_after_rereview,
)

DB = os.environ.get("V2_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB, reason="V2_TEST_DATABASE_URL is required")
REASON = "Re-review test"


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


def _count(session, sql, **params):
    return session.execute(text(sql), params).scalar()


def _first(session, table, key, status_column, status):
    return _count(session, f"SELECT {key}::text FROM {table} WHERE {status_column} = :s "
                           f"{'AND merged_into_actor_id IS NULL' if table == 'actor' else ''} LIMIT 1",
                  s=status)


def test_a_dry_run_counts_and_changes_nothing(session):
    verified = _count(session, "SELECT count(*) FROM actor WHERE status='verified' "
                               "AND merged_into_actor_id IS NULL")
    if not verified:
        pytest.skip("this copy was taken after the re-review park: nothing is verified")
    out = park_for_rereview(session, decided_by="tester", reason=REASON)
    assert out["live"] is False and out["parked"]["actor"] <= verified
    assert out["parked"]["actor"] > 0
    assert _count(session, "SELECT count(*) FROM actor WHERE status='verified' "
                           "AND merged_into_actor_id IS NULL") == verified


def test_parking_leaves_rejected_alone_and_records_events_and_people(session):
    rejected = _count(session, "SELECT count(*) FROM actor WHERE status='rejected'")
    out = park_for_rereview(session, decided_by="tester", reason=REASON, live=True)
    assert _count(session, "SELECT count(*) FROM actor WHERE status='verified' "
                           "AND merged_into_actor_id IS NULL") == 0
    assert _count(session, "SELECT count(*) FROM actor WHERE status='rejected'") == rejected
    assert _count(session, "SELECT count(*) FROM event WHERE record_status='verified'") == 0
    assert _count(session, "SELECT count(*) FROM person WHERE record_status='verified'") == 0
    # People keep their older status column in step (person_v2_compat_sync).
    assert _count(session, "SELECT count(*) FROM person WHERE verification_status='verified'") == 0
    parked_history = _count(session, "SELECT count(*) FROM record_verification WHERE decision='parked' "
                                     "AND notes = :n", n=REASON)
    assert parked_history == out["parked"]["event"] + out["parked"]["person"]
    assert len(out["records"]) == sum(out["parked"].values())


@pytest.mark.parametrize("entity_type, table, key, column", [
    ("actor", "actor", "actor_id", "status"),
    ("event", "event", "event_id", "record_status"),
    ("person", "person", "person_id", "record_status"),
])
def test_each_record_type_is_verified_or_rejected_from_the_directory(session, entity_type, table,
                                                                     key, column):
    park_for_rereview(session, decided_by="tester", reason=REASON, live=True)
    first = _first(session, table, key, column, "parked")
    if first is None:
        pytest.skip(f"no parked {entity_type} in this copy")
    out = record_directory_verification(session, entity_type=entity_type, entity_id=first,
                                        verified=True, decided_by="tester", live=True)
    assert out["status"] == "applied" and out["current_status"] == "verified"
    assert _count(session, f"SELECT {column} FROM {table} WHERE {key} = CAST(:i AS uuid)", i=first) == "verified"
    with pytest.raises(ValueError, match="reason"):
        record_directory_verification(session, entity_type=entity_type, entity_id=first,
                                      verified=False, decided_by="tester", live=True)
    out = record_directory_verification(session, entity_type=entity_type, entity_id=first,
                                        verified=False, rejection_reason="Not in scope",
                                        decided_by="tester", live=True)
    assert out["current_status"] == "rejected"
    assert _count(session, f"SELECT {column} FROM {table} WHERE {key} = CAST(:i AS uuid)", i=first) == "rejected"


def test_restore_puts_back_only_what_nobody_decided_since(session):
    out = park_for_rereview(session, decided_by="tester", reason=REASON, live=True)
    decided = next((r for r in out["records"] if r["entity_type"] == "actor"), None)
    if decided is None:
        pytest.skip("this copy was taken after the re-review park: nothing is verified")
    record_directory_verification(session, entity_type="actor", entity_id=decided["entity_id"],
                                  verified=False, rejection_reason="Not in scope",
                                  decided_by="tester", live=True)
    back = restore_after_rereview(session, records=out["records"], decided_by="tester", live=True)
    assert back["restored"]["actor"] == out["parked"]["actor"] - 1
    assert _count(session, "SELECT status FROM actor WHERE actor_id = CAST(:i AS uuid)",
                  i=decided["entity_id"]) == "rejected"
    assert _count(session, "SELECT count(*) FROM actor WHERE status='parked' "
                           "AND actor_id = ANY(CAST(:ids AS uuid[]))",
                  ids=[r["entity_id"] for r in out["records"] if r["entity_type"] == "actor"]) == 0
    if out["parked"]["event"]:
        assert back["restored"]["event"] == out["parked"]["event"]
