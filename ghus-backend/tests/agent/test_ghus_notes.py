"""GHUS analyst notes from Review: written only by GHUS, only on actors and events."""

from __future__ import annotations

import os
import uuid
from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from agents.enrichment.decisions import record_ghus_notes
from agents.review import admission


def _decision(entity_type="actor", kind="new", **updates):
    value = {
        "entity_type": entity_type,
        "source_ref": {"table": "search_candidate", "id": "00000000-0000-0000-0000-000000000001"},
        "decision_kind": kind,
        "target_id": "00000000-0000-0000-0000-000000000002" if kind == "same_existing" else None,
        "edited_payload": {"name": "Example"},
        "reviewer": "Reviewer",
        "idempotency_key": f"{entity_type}-{kind}",
    }
    value.update(updates)
    return value


class Session:
    def __init__(self, rowcount=1):
        self.statements, self.rowcount = [], rowcount

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params))
        return type("Result", (), {"rowcount": self.rowcount})()


def test_notes_travel_with_an_admitted_actor_or_event():
    for entity_type in ("actor", "event"):
        clean = admission._normalise_decision(_decision(entity_type, ghus_notes="  Met them at CES.  "))
        assert clean["ghus_notes"] == "Met them at CES."
    assert admission._normalise_decision(_decision())["ghus_notes"] is None


@pytest.mark.parametrize("decision, words", [
    (_decision("person", ghus_notes="x"), "only for actors and events"),
    (_decision("actor", "defer", ghus_notes="x"), "admitted record"),
    (_decision("actor", "reject", rejection_reason="Duplicate of an existing record", ghus_notes="x"), "admitted record"),
    (_decision("actor", ghus_notes="x" * 5001), "at most 5000"),
])
def test_notes_are_refused_where_they_cannot_be_kept(decision, words):
    with pytest.raises(admission.AdmissionValidationError, match=words):
        admission._normalise_decision(decision)


def test_the_writer_declares_the_session_human_for_this_transaction_only():
    session = Session()
    actor = str(uuid.uuid4())
    assert record_ghus_notes(session, entity_type="actor", entity_id=actor, notes="Back-to-office "
                             "report: https://onedrive.example/r1", decided_by="Ana", live=True)
    (first, _), (update, params) = session.statements
    assert first == "SET LOCAL ghus.actor_is_human = 'on'"
    assert update.startswith("UPDATE actor SET ghus_notes")
    assert params == {"notes": "Back-to-office report: https://onedrive.example/r1", "id": actor}


def test_the_writer_writes_nothing_unless_live_and_never_for_people():
    session = Session()
    actor = str(uuid.uuid4())
    assert record_ghus_notes(session, entity_type="event", entity_id=actor, notes="x",
                             decided_by="Ana") is False
    assert record_ghus_notes(session, entity_type="actor", entity_id=actor, notes="  ",
                             decided_by="Ana", live=True) is False
    assert session.statements == []
    with pytest.raises(ValueError, match="only for actors and events"):
        record_ghus_notes(session, entity_type="person", entity_id=actor, notes="x",
                          decided_by="Ana", live=True)
    with pytest.raises(ValueError, match="GHUS person"):
        record_ghus_notes(session, entity_type="actor", entity_id=actor, notes="x",
                          decided_by=" ", live=True)
    with pytest.raises(ValueError, match="not found"):
        record_ghus_notes(Session(rowcount=0), entity_type="actor", entity_id=actor, notes="x",
                          decided_by="Ana", live=True)


# --------------------------------------------------- isolated PostgreSQL proof
URL = os.environ.get("V2_TEST_DATABASE_URL", "")


def _local_test_url() -> str:
    parsed = urlsplit(URL.replace("postgresql+psycopg2", "postgresql", 1))
    if (parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port != 55432
            or not parsed.path.removeprefix("/").endswith("_test")):
        pytest.skip("needs a local *_test database on port 55432")
    return URL


@pytest.mark.skipif(not URL, reason="V2_TEST_DATABASE_URL is required")
def test_only_a_human_session_changes_ghus_notes_and_nothing_is_kept():
    engine = create_engine(_local_test_url(), future=True)
    with engine.connect() as conn:
        if not conn.execute(text("SELECT 1 FROM information_schema.columns WHERE "
                                 "table_name = 'actor' AND column_name = 'ghus_notes'")).first():
            pytest.skip("this database has no ghus_notes column (migration 330)")
        actor = conn.execute(text("SELECT actor_id::text FROM actor ORDER BY actor_id LIMIT 1")).scalar()
        if actor is None:
            pytest.skip("no actor in this database")
        conn.rollback()  # the reads above opened a transaction
        # An agent session cannot write the notes (migration 530's guard)...
        trans = conn.begin()
        guarded = conn.execute(text("SELECT 1 FROM pg_trigger WHERE tgname = 'actor_ghus_notes_guard'")).first()
        if guarded:
            with pytest.raises(DBAPIError, match="written only by GHUS"):
                conn.execute(text("UPDATE actor SET ghus_notes = 'agent' WHERE actor_id = CAST(:a AS uuid)"),
                             {"a": actor})
        trans.rollback()
        # ...the GHUS writer can, and the test leaves no trace.
        trans = conn.begin()
        assert record_ghus_notes(conn, entity_type="actor", entity_id=actor,
                                 notes="Test note from Review", decided_by="Test", live=True)
        assert conn.execute(text("SELECT ghus_notes FROM actor WHERE actor_id = CAST(:a AS uuid)"),
                            {"a": actor}).scalar() == "Test note from Review"
        trans.rollback()
    engine.dispose()
