"""Phase 12 legacy preservation (482) and category proposal (484) proofs."""

from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from agents.common.geography import STATE_ALIASES, normalize_city, normalize_state, region_for_state
from scripts.phase12_category_proposal_sql import CSV_PATH, SQL_PATH, render

ROOT = Path(__file__).resolve().parents[2]
DEFERRED = ROOT / "migrations/proposed/deferred"
MANIFEST = ROOT / "migrations/proposed/functional_v2_isolated_manifest.json"
FULL_URL = os.environ.get("V2_PHASE12_FULL_DATABASE_URL", "")
live = pytest.mark.skipif(not FULL_URL, reason="V2_PHASE12_FULL_DATABASE_URL is required")


def test_sql_state_aliases_match_python_geography():
    sql = (DEFERRED / "482_v2_phase12_legacy_preservation.sql").read_text(encoding="utf-8")
    block = sql[sql.index("INSERT INTO us_state_alias"):sql.index("ON CONFLICT (alias)")]
    pairs = dict(re.findall(r"\('([^']+)','([A-Z]{2})'\)", block))
    assert pairs == STATE_ALIASES


def test_backfill_steps_run_after_480_and_before_validation():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    steps = [step["id"] for step in manifest["checkpoints"]["phase12_policy_backfill"]["steps"]]
    assert steps == ["480", "482", "484", "488", "489"]
    assert manifest["checkpoints"]["phase12_policy_validate"]["inherits"] == "phase12_policy_backfill"


def test_480_preserves_legacy_verification_status_not_the_empty_v2_status():
    sql = (DEFERRED / "480_v2_phase12_existing_actor_backfill.sql").read_text(encoding="utf-8")
    assert "'verification_status' ELSE 'status' END INTO legacy_status_column" in sql
    assert "%2$I,source_origin,category_note,category_needs_review" in sql


def test_482_never_invents_provenance():
    sql = (DEFERRED / "482_v2_phase12_legacy_preservation.sql").read_text(encoding="utf-8")
    assert "FROM legacy WHERE source_id IS NOT NULL" in sql
    assert "s.retrieved_at IS NOT NULL" in sql
    assert "now()" not in sql.split("-- 5.")[1]  # facts carry the legacy source's retrieved_at
    assert "INSERT INTO entity_edge" not in sql  # unsourced hierarchy becomes review only


def test_484_is_generated_from_the_reviewed_csv():
    assert SQL_PATH.read_text(encoding="utf-8") == render(CSV_PATH.read_bytes())
    with CSV_PATH.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 214
    for row in rows:
        if row["is_true_aggregate"] == "True":
            assert row["proposed_category"] == ""


@pytest.fixture(scope="module")
def engine():
    assert "127.0.0.1:55432/ghus_v2_phase12_full_test" in FULL_URL
    value = create_engine(FULL_URL)
    try:
        yield value
    finally:
        value.dispose()


@live
def test_sql_normalization_matches_python_on_all_real_values(engine):
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT value, ghus_normalize_city(value) city, ghus_normalize_state(value) state
            FROM (SELECT location_city value FROM actor UNION SELECT state FROM actor
                  UNION SELECT place_name FROM us_city_coord) v
            WHERE value IS NOT NULL
        """)).all()
    assert len(rows) > 25_000
    city_mismatch = [r.value for r in rows if r.city != normalize_city(r.value)]
    state_mismatch = [r.value for r in rows if r.state != normalize_state(r.value)]
    assert city_mismatch == []
    assert state_mismatch == []


@live
def test_geography_backfill_matches_python_lookup(engine):
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT state, state_code, region_code FROM actor
            WHERE NULLIF(btrim(state),'') IS NOT NULL
        """)).all()
    for row in rows:
        assert row.state_code == normalize_state(row.state)
        assert row.region_code == region_for_state(row.state)


@live
def test_backfill_reruns_are_noops(engine):
    counted = ("actor_fact", "legacy_migration_record", "review_item", "actor_location",
               "actor_verification_event", "actor_category_migration_audit")

    def counts():
        with engine.connect() as connection:
            return {t: connection.execute(text(f"SELECT count(*) FROM {t}")).scalar_one()
                    for t in counted}

    before = counts()
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cursor:
            for name in ("480_v2_phase12_existing_actor_backfill.sql",
                         "482_v2_phase12_legacy_preservation.sql",
                         "484_v2_phase12_category_proposals.sql"):
                cursor.execute((DEFERRED / name).read_text(encoding="utf-8"))
        raw.commit()
    finally:
        raw.close()
    assert counts() == before


@live
def test_category_review_confirmation_is_audited_idempotent_and_refuses_aggregates(engine):
    from sqlalchemy.orm import Session

    from agents.review.admission import AdmissionValidationError, apply_category_decisions

    with engine.connect() as connection:
        outer = connection.begin()
        try:
            proposal = connection.execute(text("""
                SELECT review_item_id::text id, entity_id::text actor_id,
                       payload->>'proposed_category' category
                FROM review_item WHERE review_kind='category_doubt' AND status='pending'
                  AND payload->>'is_true_aggregate'='false' LIMIT 1
            """)).mappings().one()
            aggregate = connection.execute(text("""
                SELECT review_item_id::text id FROM review_item
                WHERE review_kind='category_doubt' AND payload->>'is_true_aggregate'='true' LIMIT 1
            """)).scalar_one()
            session = Session(bind=connection, join_transaction_mode="create_savepoint")
            request = {"decision_kind": "confirm_category", "reviewer": "GHUS test reviewer",
                       "idempotency_key": "phase12-test",
                       "items": [{"review_item_id": proposal["id"],
                                  "actor_category": proposal["category"]}]}
            first = apply_category_decisions(session, request)
            assert first["resolved"] == 1
            actor = connection.execute(text(
                "SELECT actor_category, category_needs_review FROM actor "
                "WHERE actor_id=CAST(:id AS uuid)"), {"id": proposal["actor_id"]}).one()
            assert actor == (proposal["category"], False)
            decision = connection.execute(text(
                "SELECT decision, decided_by FROM review_item_decision "
                "WHERE review_item_id=CAST(:id AS uuid)"), {"id": proposal["id"]}).one()
            assert decision == ("resolve", "GHUS test reviewer")
            assert apply_category_decisions(session, request)["already_resolved"] == 1
            with pytest.raises(ValueError, match="aggregate"):
                apply_category_decisions(session, {**request, "items": [
                    {"review_item_id": aggregate, "actor_category": "company"}]})
            with pytest.raises((ValueError, AdmissionValidationError)):
                apply_category_decisions(session, {**request, "items": [
                    {"review_item_id": proposal["id"], "actor_category": "aggregate"}]})
            session.close()
        finally:
            outer.rollback()
