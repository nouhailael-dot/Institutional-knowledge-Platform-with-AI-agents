from __future__ import annotations

import uuid
from pathlib import Path

from agents.enrichment.decisions import apply_or_propose_field
from agents.enrichment.fields import FieldPolicy, load_field_config, policies_for_entity
from agents.enrichment.gaps import is_gap
from agents.enrichment.specs import get_entity_spec
from agents.index.refresh import SearchDocCandidate, refresh_search_doc

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class FakeMappingResult:
    def __init__(self, rows=None, *, rowcount=1):
        self.rows = rows or []
        self.rowcount = rowcount

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows

    def scalar_one(self):
        return str(uuid.uuid4())


class FakeSession:
    def __init__(self, current_values=None):
        self.current_values = list(current_values if current_values is not None else [None])
        self.statements = []
        self.params = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        self.params.append(params or {})
        if sql.strip().startswith("SELECT") and "AS current_value" in sql:
            value = self.current_values.pop(0) if self.current_values else None
            return FakeMappingResult([{"current_value": value}])
        return FakeMappingResult()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_gap_semantics_are_only_null_empty_or_placeholders():
    assert is_gap(None)
    assert is_gap("")
    assert is_gap("  N/A  ")
    assert is_gap("not available")
    assert not is_gap("0")
    assert not is_gap(0)
    assert not is_gap(False)
    assert not is_gap("unknown but active")


def test_person_fields_are_proposal_only():
    config = load_field_config(PROJECT_ROOT)
    person_policies = policies_for_entity(config, "person")

    assert person_policies
    assert all(policy.auto_apply_floor is None for policy in person_policies.values())


def test_below_floor_candidate_writes_field_proposal_not_update():
    session = FakeSession(current_values=[None])
    spec = get_entity_spec("actor")
    outcome = apply_or_propose_field(
        session,
        run_id=str(uuid.uuid4()),
        spec=spec,
        policy=FieldPolicy("actor", "website", enrichable=True, auto_apply_floor=0.95),
        entity_id=str(uuid.uuid4()),
        field_name="website",
        proposed_value="https://example.org",
        source_url="https://registry.example.org/example",
        confidence=0.80,
        reason="below configured floor",
        live=True,
    )

    assert outcome.action == "proposed_below_floor"
    assert any("INSERT INTO field_proposal" in sql for sql in session.statements)
    assert not any("UPDATE actor" in sql for sql in session.statements)
    field_proposal_params = [
        params for sql, params in zip(session.statements, session.params) if "INSERT INTO field_proposal" in sql
    ][0]
    assert field_proposal_params["source_url"] == "https://registry.example.org/example"


def test_existing_value_becomes_proposal_never_overwrite():
    session = FakeSession(current_values=["https://existing.example"])
    spec = get_entity_spec("actor")
    outcome = apply_or_propose_field(
        session,
        run_id=str(uuid.uuid4()),
        spec=spec,
        policy=FieldPolicy("actor", "website", enrichable=True, auto_apply_floor=0.95),
        entity_id=str(uuid.uuid4()),
        field_name="website",
        proposed_value="https://replacement.example",
        source_url="https://registry.example.org/replacement",
        confidence=0.99,
        reason="high confidence but existing value is present",
        live=True,
    )

    assert outcome.action == "proposed_existing_value"
    assert any("INSERT INTO field_proposal" in sql for sql in session.statements)
    assert not any("UPDATE actor" in sql for sql in session.statements)


def test_high_confidence_gap_applies_with_last_moment_gap_guard():
    session = FakeSession(current_values=[None, None])
    spec = get_entity_spec("actor")
    outcome = apply_or_propose_field(
        session,
        run_id=str(uuid.uuid4()),
        spec=spec,
        policy=FieldPolicy("actor", "website", enrichable=True, auto_apply_floor=0.95),
        entity_id=str(uuid.uuid4()),
        field_name="website",
        proposed_value="https://example.org",
        source_url="https://registry.example.org/example",
        confidence=0.99,
        reason="meets configured floor",
        live=True,
    )

    assert outcome.action == "applied"
    update_sql = [sql for sql in session.statements if "UPDATE actor" in sql][0]
    assert "WHERE actor_id = CAST(:entity_id AS uuid)" in update_sql
    assert "website IS NULL" in update_sql
    assert "INSERT INTO source" in "\n".join(session.statements)


def test_zero_search_doc_candidates_never_delete():
    session = FakeSession()
    stats = refresh_search_doc(session, candidates=[], live=True)

    assert stats.candidates == 0
    assert stats.deletes == 0
    assert not any("DELETE" in sql.upper() for sql in session.statements)


def test_search_doc_refresh_upserts_only_selected_candidates():
    session = FakeSession()
    stats = refresh_search_doc(
        session,
        live=True,
        candidates=[
            SearchDocCandidate(
                entity_type="actor",
                entity_id=str(uuid.uuid4()),
                name="Example Actor",
                doc_text="Name: Example Actor\nWebsite: https://example.org",
            )
        ],
    )

    assert stats.candidates == 1
    assert stats.upserts == 1
    assert stats.deletes == 0
    assert any("INSERT INTO search_doc" in sql for sql in session.statements)
    assert not any("search_doc_2" in sql for sql in session.statements)
