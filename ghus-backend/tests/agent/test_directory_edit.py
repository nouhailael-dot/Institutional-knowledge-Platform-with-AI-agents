"""Edit in the Ecosystem Directory (10 Nov 2026): a GHUS person corrects a record.

The writer is decisions.record_directory_edit, reached through the admission
process. The database tests run on the isolated V2 test database, inside a
transaction that is always rolled back.
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text

from agents.enrichment.decisions import record_directory_edit
from agents.review import admission

ACTOR = "11111111-2222-3333-4444-555555555555"


# --- the admission entry point (no database) ----------------------------------

def test_a_refusal_from_the_writer_is_a_plain_validation_error():
    session = MagicMock()
    with patch("agents.enrichment.decisions.record_directory_edit",
               side_effect=ValueError("unknown US state: Atlantis")), \
            pytest.raises(admission.AdmissionValidationError, match="unknown US state"):
        admission.apply_directory_edit(session, {
            "decision_kind": "edit_directory_record", "entity_type": "actor",
            "entity_id": ACTOR, "changes": {"state": "Atlantis"}, "reviewer": "Ana"})
    session.begin.return_value.rollback.assert_called_once()


def test_the_entry_point_reports_what_changed_and_commits():
    session = MagicMock()
    with patch("agents.enrichment.decisions.record_directory_edit",
               return_value={"changed": ["name"], "written": True}) as writer:
        outcome = admission.apply_directory_edit(session, {
            "decision_kind": "edit_directory_record", "entity_type": "actor",
            "entity_id": ACTOR, "changes": {"name": "New"}, "ghus_notes": None, "reviewer": "Ana"})
    assert outcome == {"decision_kind": "edit_directory_record", "entity_type": "actor",
                       "entity_id": ACTOR, "status": "applied", "changed": ["name"]}
    assert writer.call_args.kwargs["live"] is True
    assert writer.call_args.kwargs["decided_by"] == "Ana"
    session.begin.return_value.commit.assert_called_once()


@pytest.mark.parametrize("change, words", [
    ({"reviewer": ""}, "reviewer"),
    ({"entity_id": "nope"}, "UUID"),
    ({"changes": ["name"]}, "object"),
])
def test_the_entry_point_refuses_a_malformed_request(change, words):
    decision = {"decision_kind": "edit_directory_record", "entity_type": "actor",
                "entity_id": ACTOR, "changes": {"name": "x"}, "reviewer": "Ana", **change}
    with pytest.raises(admission.AdmissionValidationError, match=words):
        admission.apply_directory_edit(MagicMock(), decision)


# --- the writer, on the isolated test database --------------------------------

DB = os.environ.get("V2_TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB, reason="V2_TEST_DATABASE_URL is required")


@pytest.fixture
def conn():
    engine = create_engine(DB)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()
    engine.dispose()


def _one(conn, sql, **params):
    return conn.execute(text(sql), params).mappings().first()


@needs_db
def test_an_organization_edit_writes_columns_and_keeps_the_history(conn):
    actor = _one(conn, "SELECT actor_id::text AS id FROM actor WHERE merged_into_actor_id IS NULL "
                       "ORDER BY name LIMIT 1")["id"]
    state = _one(conn, "SELECT state_code, state_name FROM region_state ORDER BY state_code LIMIT 1")
    region = _one(conn, "SELECT region_code, display_name FROM region_definition LIMIT 1")
    outcome = record_directory_edit(conn, entity_type="actor", entity_id=actor, decided_by="Ana Ruiz",
                                    changes={"name": "Example Edited Lab",
                                             "website": "https://www.edited-lab.example/about",
                                             "state": state["state_name"],
                                             "region": region["display_name"],
                                             "alt_names": "EEL, Edited Lab",
                                             "funding_summary": "NSF grant, 2025."},
                                    ghus_notes="Met them in Phoenix.", live=True)
    assert outcome["written"] is True
    assert set(outcome["changed"]) >= {"name", "website", "state_code", "region_code",
                                       "alternate_names", "funding_summary", "ghus_notes"}
    row = _one(conn, "SELECT name, website, website_domain, state_code, region_code, "
                     "alternate_names, ghus_notes FROM actor WHERE actor_id=CAST(:id AS uuid)", id=actor)
    assert (row["name"], row["website_domain"]) == ("Example Edited Lab", "edited-lab.example")
    assert (row["state_code"], row["region_code"]) == (state["state_code"], region["region_code"])
    assert row["alternate_names"] == ["EEL", "Edited Lab"]
    assert row["ghus_notes"] == "Met them in Phoenix."
    facts = conn.execute(text(
        "SELECT * FROM actor_fact "
        "WHERE actor_id=CAST(:id AS uuid) AND fact_type='ghus_edit' AND generated_by='Ana Ruiz' "
        "ORDER BY created_at"),
        {"id": actor}).mappings().all()
    by_key = {f["fact_key"]: f for f in facts}
    assert by_key["funding_summary"]["fact_value"] == "NSF grant, 2025."
    assert by_key["name"]["fact_value"] == "Example Edited Lab"
    if "creator_class" in facts[0]:
        assert {f["creator_class"] for f in facts} == {"ghus_human"}
    assert {f["source_origin"] for f in facts} == {"ghus_manual"}
    assert {f["generated_by"] for f in facts} == {"Ana Ruiz"}

    again = record_directory_edit(conn, entity_type="actor", entity_id=actor, decided_by="Ana Ruiz",
                                  changes={"name": "Example Edited Lab", "funding_summary": "NSF grant, 2025."},
                                  ghus_notes="Met them in Phoenix.", live=True)
    assert again == {"changed": [], "written": False}


@needs_db
@pytest.mark.parametrize("changes, words", [
    ({"name": "  "}, "name cannot be empty"),
    ({"state": "Atlantis"}, "unknown US state"),
    ({"region": "Moon"}, "unknown region"),
    ({"actor_type": "Pirate ship"}, "unknown organization category"),
    ({"hubs": "x"}, "cannot be edited here"),
    ({"description": "x" * 5001}, "at most 5000"),
])
def test_an_invalid_organization_edit_is_refused_before_any_write(conn, changes, words):
    actor = _one(conn, "SELECT actor_id::text AS id FROM actor WHERE merged_into_actor_id IS NULL LIMIT 1")["id"]
    with pytest.raises(ValueError, match=words):
        record_directory_edit(conn, entity_type="actor", entity_id=actor, changes=changes,
                              decided_by="Ana", live=True)


@needs_db
def test_events_hubs_and_people_can_be_corrected(conn):
    event = _one(conn, "SELECT event_id::text AS id FROM event LIMIT 1")
    if event:
        out = record_directory_edit(conn, entity_type="event", entity_id=event["id"], decided_by="Ana",
                                    changes={"name": "Edited Summit", "start_date": "2027-03-04",
                                             "thematic_focus": "Water reuse"},
                                    ghus_notes="Two of us went.", live=True)
        assert out["written"] and "name" in out["changed"]
        row = _one(conn, "SELECT * FROM event WHERE event_id=CAST(:id AS uuid)", id=event["id"])
        assert row["name"] == "Edited Summit" and row["ghus_notes"] == "Two of us went."
        assert str(row.get("start_date") or row.get("next_date")) == "2027-03-04"
        with pytest.raises(ValueError, match="must be a date"):
            record_directory_edit(conn, entity_type="event", entity_id=event["id"], decided_by="Ana",
                                  changes={"end_date": "03/04/2027"}, live=True)
    hub = _one(conn, "SELECT hub_id::text AS id FROM hub LIMIT 1")
    if hub:
        record_directory_edit(conn, entity_type="hub", entity_id=hub["id"], decided_by="Ana",
                              changes={"talent_narrative": "Strong PhD pipeline."}, live=True)
        assert _one(conn, "SELECT talent_narrative FROM hub WHERE hub_id=CAST(:id AS uuid)",
                    id=hub["id"])["talent_narrative"] == "Strong PhD pipeline."
    person = _one(conn, "SELECT person_id::text AS id FROM person LIMIT 1")
    if person:
        record_directory_edit(conn, entity_type="person", entity_id=person["id"], decided_by="Ana",
                              changes={"title": "Professor of Hydrology"}, live=True)
        assert _one(conn, "SELECT title FROM person WHERE person_id=CAST(:id AS uuid)",
                    id=person["id"])["title"] == "Professor of Hydrology"


@needs_db
def test_a_dry_run_writes_nothing(conn):
    actor = _one(conn, "SELECT actor_id::text AS id, name FROM actor WHERE merged_into_actor_id IS NULL LIMIT 1")
    out = record_directory_edit(conn, entity_type="actor", entity_id=actor["id"], decided_by="Ana",
                                changes={"name": actor["name"] + " X"})
    assert out == {"changed": ["name"], "written": False}
    assert _one(conn, "SELECT name FROM actor WHERE actor_id=CAST(:id AS uuid)", id=actor["id"])["name"] \
        == actor["name"]
