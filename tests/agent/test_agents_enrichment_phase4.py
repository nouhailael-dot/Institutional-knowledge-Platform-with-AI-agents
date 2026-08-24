from __future__ import annotations

import json
import re
import uuid
from argparse import Namespace
from pathlib import Path

import pytest

from agents.common.digest import build_digest
from agents.enrichment.decisions import apply_or_propose_field
from agents.enrichment.fields import FieldPolicy, load_field_config, policies_for_entity
from agents.enrichment.gaps import is_gap
from agents.enrichment.run import run_enrichment
from agents.enrichment.specs import get_entity_spec
from agents.index import refresh as refresh_module
from agents.index.refresh import SearchDocCandidate, load_incremental_candidate_selection, refresh_search_doc
from src.db import models

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _canonical_table_names_from_models() -> set[str]:
    return set(models.CANONICAL_ENTITY_TABLES)


def _agent_owned_table_names_from_sql() -> set[str]:
    create_table = re.compile(r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_][a-z0-9_]*)\b", re.IGNORECASE)
    tables: set[str] = set()
    for path in (PROJECT_ROOT / "agents" / "sql").glob("*.sql"):
        tables.update(match.group(1) for match in create_table.finditer(path.read_text(encoding="utf-8")))
    return tables


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
    def __init__(self, current_values=None, *, update_rowcount=1, select_rows=None):
        self.current_values = list(current_values if current_values is not None else [None])
        self.update_rowcount = update_rowcount
        self.select_rows = list(select_rows or [])
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
        if sql.strip().startswith("SELECT"):
            return FakeMappingResult(self.select_rows)
        if sql.strip().startswith("UPDATE actor"):
            return FakeMappingResult(rowcount=self.update_rowcount)
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
    assert any("INSERT INTO source" in sql for sql in session.statements)
    assert any("INSERT INTO field_proposal" in sql for sql in session.statements)
    assert not any("UPDATE actor" in sql for sql in session.statements)
    source_params = [params for sql, params in zip(session.statements, session.params) if "INSERT INTO source" in sql][0]
    field_proposal_params = [
        params for sql, params in zip(session.statements, session.params) if "INSERT INTO field_proposal" in sql
    ][0]
    assert field_proposal_params["source_url"] == "https://registry.example.org/example"
    assert field_proposal_params["source_id"] == source_params["source_id"]


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


def test_gap_guard_rowcount_refuses_racing_non_null_write():
    session = FakeSession(current_values=[None, None], update_rowcount=0)
    spec = get_entity_spec("actor")

    with pytest.raises(RuntimeError, match="gap guard matched zero rows"):
        apply_or_propose_field(
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

    assert any("UPDATE actor" in sql for sql in session.statements)


def test_every_field_proposal_has_source_row_and_source_id_link():
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
    source_params = [params for sql, params in zip(session.statements, session.params) if "INSERT INTO source" in sql][0]
    proposal_params = [
        params for sql, params in zip(session.statements, session.params) if "INSERT INTO field_proposal" in sql
    ][0]
    staged_params = [
        params for sql, params in zip(session.statements, session.params) if "INSERT INTO staged_record" in sql
    ][0]
    staged_payload = json.loads(staged_params["payload"])

    assert proposal_params["source_id"] == source_params["source_id"]
    assert staged_payload["source_id"] == source_params["source_id"]


def test_no_adapter_run_closes_skipped_and_digest_requires_attention():
    session = FakeSession(select_rows=[{"entity_id": str(uuid.uuid4()), "name": "Sparse Hub"}])
    result = run_enrichment(
        Namespace(entity="hub", field_set="profile", limit=1, live=False, allow_claude=False),
        session=session,
        root=PROJECT_ROOT,
    )
    digest = build_digest(
        run_id=result["run_id"],
        source="enrichment",
        entity_type="hub",
        status=result["status"],
        stats=result["stats"],
    )

    assert result["status"] == "skipped"
    assert result["stats"]["attention_required"] is True
    assert "no candidate adapter exists for entity=hub" in result["stats"]["skipped_reason"]
    assert "**Status:** skipped" in digest
    assert "**Attention Required:** yes" in digest
    assert "no candidate adapter exists for entity=hub" in digest


def test_digest_reports_in_sector_and_out_of_sector_counts():
    digest = build_digest(
        run_id=str(uuid.uuid4()),
        source="climate_week",
        entity_type="event",
        status="succeeded",
        stats={
            "documents_fetched": 1,
            "skipped_unchanged": 0,
            "records_extracted": 3,
            "records_in_sector": 2,
            "records_out_of_sector": 1,
            "absorbed": 0,
            "queued_for_review": 0,
            "created": 2,
            "failures": 0,
        },
    )

    assert "| In-sector staged | 2 |" in digest
    assert "| Out-of-sector staged | 1 |" in digest


def test_canonical_writes_under_agents_are_only_in_permitted_modules():
    canonical_tables = _canonical_table_names_from_models()
    agent_owned_tables = _agent_owned_table_names_from_sql()
    protected_tables = canonical_tables | agent_owned_tables
    allowed_by_table = {
        table: {
            Path("agents/discovery/promote.py"),
            Path("agents/enrichment/decisions.py"),
        }
        for table in canonical_tables
    }
    allowed_by_table.update(
        {
            "scrape_run": {Path("agents/common/run_log.py")},
            "raw_document": {Path("agents/common/run_log.py")},
            "staged_record": {
                Path("agents/discovery/stage.py"),
                Path("agents/enrichment/decisions.py"),
            },
            "field_proposal": {Path("agents/common/provenance.py")},
            "index_dirty": {
                Path("agents/discovery/promote.py"),
                Path("agents/index/refresh.py"),
            },
            "event_review_queue": {Path("agents/discovery/promote.py")},
        }
    )
    table_pattern = "|".join(re.escape(table) for table in sorted(protected_tables, key=len, reverse=True))
    sql_pattern = re.compile(rf"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+({table_pattern})\b", re.IGNORECASE)
    orm_pattern = re.compile(rf"\b({table_pattern})\.[a-z_][a-z0-9_]*\s*=", re.IGNORECASE)
    offenders = []
    for path in (PROJECT_ROOT / "agents").rglob("*.py"):
        relative = path.relative_to(PROJECT_ROOT)
        relative_display = str(relative).replace("\\", "/")
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            sql_match = sql_pattern.search(line)
            orm_match = orm_pattern.search(line)
            table = (sql_match or orm_match).group(1).lower() if sql_match or orm_match else None
            if table and relative not in allowed_by_table.get(table, set()):
                offenders.append(f"{relative_display}:{lineno}: unexpected write to {table}: {line.strip()}")

    assert offenders == [], "Unapproved protected-table writes found:\n" + "\n".join(offenders)


def test_zero_search_doc_candidates_never_delete():
    session = FakeSession()
    stats = refresh_search_doc(session, candidates=[], live=True)

    assert stats.candidates == 0
    assert stats.deletes == 0
    assert not any("DELETE" in sql.upper() for sql in session.statements)


def test_index_dirty_candidates_are_not_starved_by_updated_at_limit(monkeypatch):
    updated_id = str(uuid.uuid4())
    dirty_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

    monkeypatch.setattr(refresh_module, "_table_columns", lambda session, table_name: {"updated_at"})
    monkeypatch.setattr(
        refresh_module,
        "_load_entity_rows",
        lambda session, spec, *, timestamp_column, limit: [
            {
                "entity_id": updated_id,
                "name": "Updated Event",
                "description": "Selected by updated_at",
                "source_updated_at": "2026-08-21T00:00:00Z",
            }
        ],
    )
    monkeypatch.setattr(
        refresh_module,
        "_load_index_dirty_rows",
        lambda session, spec: [
            {
                "entity_id": dirty_ids[0],
                "name": "Dirty Event 1",
                "description": "Selected by index_dirty",
                "source_updated_at": "2026-08-21T00:00:00Z",
            },
            {
                "entity_id": dirty_ids[1],
                "name": "Dirty Event 2",
                "description": "Selected by index_dirty",
                "source_updated_at": "2026-08-21T00:00:00Z",
            },
        ],
    )

    selection = load_incremental_candidate_selection(FakeSession(), entity_types=("event",), limit=1)

    assert selection.updated_at_candidates == 1
    assert selection.index_dirty_candidates == 2
    assert len(selection.candidates) == 3
    assert [candidate.entity_id for candidate in selection.candidates] == [updated_id, *dirty_ids]
    assert sum(1 for candidate in selection.candidates if candidate.from_index_dirty) == 2


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
    upsert_params = [params for sql, params in zip(session.statements, session.params) if "INSERT INTO search_doc" in sql][0]
    assert upsert_params["entity_type"] == "actor"
    assert upsert_params["entity_id"]
    assert not any("search_doc_2" in sql for sql in session.statements)


def test_search_doc_refresh_refuses_candidate_without_entity_reference():
    session = FakeSession()

    with pytest.raises(RuntimeError, match="missing entity_type or entity_id"):
        refresh_search_doc(
            session,
            live=True,
            candidates=[
                SearchDocCandidate(
                    entity_type="",
                    entity_id=str(uuid.uuid4()),
                    name="Broken Candidate",
                    doc_text="Name: Broken Candidate",
                )
            ],
        )

    assert not any("INSERT INTO search_doc" in sql for sql in session.statements)


def test_search_doc_upsert_clears_index_dirty_row_after_successful_upsert():
    session = FakeSession()
    stats = refresh_search_doc(
        session,
        live=True,
        candidates=[
            SearchDocCandidate(
                entity_type="event",
                entity_id=str(uuid.uuid4()),
                name="Climate Innovation Summit",
                doc_text="Name: Climate Innovation Summit\nDescription: Climate event",
                from_index_dirty=True,
            )
        ],
    )

    assert stats.candidates == 1
    assert stats.upserts == 1
    assert stats.index_dirty_candidates == 1
    assert stats.dirty_cleared == 1
    upsert_index = next(index for index, sql in enumerate(session.statements) if "INSERT INTO search_doc" in sql)
    clear_index = next(index for index, sql in enumerate(session.statements) if "DELETE FROM index_dirty" in sql)
    assert upsert_index < clear_index
    assert session.commits == 1
    assert session.rollbacks == 0


def test_search_doc_dry_run_executes_upsert_then_rolls_back():
    session = FakeSession()
    stats = refresh_search_doc(
        session,
        live=False,
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
    assert any("INSERT INTO search_doc" in sql for sql in session.statements)
    assert session.commits == 0
    assert session.rollbacks == 1
