"""Contracts for detached Architecture V2 proposals and the isolated test DB."""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import uuid
from pathlib import Path
from typing import ClassVar

import pytest
import yaml
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from agents.common.resolve_route import RouteDecision
from agents.discovery.promote import ACTOR_MAPPING_STEPS, map_new_actor
from agents.discovery.stage import StagedRecord
from src.db.base import Base
from src.db.models import Actor, Person
from src.db.models_v2 import V2Base

ROOT = Path(__file__).resolve().parents[2]
PROPOSED = ROOT / "migrations" / "proposed"
MANIFEST = PROPOSED / "manifest.json"
V2_CONFIG = ROOT / "config" / "architecture_v2.yaml"

V2_TABLES = {
    "actor_category_definition",
    "actor_category_type_definition",
    "region_definition",
    "region_state",
    "source_origin_definition",
    "us_city_coord",
    "topic",
    "actor_topic",
    "actor_location",
    "record_verification",
    "actor_fact",
    "fact_resolution",
    "entity_edge",
    "collection_request",
    "collection_run",
    "fetched_document",
    "actor_ranking",
    "person_topic",
    "contact_collection_authorization",
    "event_topic",
    "event_claim",
    "strategic_entity",
    "actor_strategic_connection_check",
    "hub_center_review",
    "hub_assignment_evidence",
    "hub_detection_run",
    "proposed_hub",
    "proposed_hub_member",
    "proposed_hub_decision",
    "review_item",
    "review_item_decision",
    "canonical_write_audit",
}


def _manifest() -> list[dict]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["logical_migrations"]


def test_manifest_has_21_ordered_reversible_migrations():
    steps = _manifest()
    assert [step["id"] for step in steps] == [f"{number:03d}" for number in range(1, 22)]
    for step in steps:
        for action in step["actions"]:
            if action["type"] == "sql":
                assert (ROOT / action["up"]).is_file()
                assert (ROOT / action["down"]).is_file()
            else:
                assert (ROOT / action["path"]).is_file()


def test_migration_tracks_are_separate_and_detached():
    live_versions = set((ROOT / "migrations" / "versions").glob("*v2a*.py"))
    assert not live_versions
    proposal_modules = sorted((PROPOSED / "versions").glob("v2a*.py"))
    assert len(proposal_modules) == 5
    assert all(
        "down_revision = None" in path.read_text(encoding="utf-8") for path in proposal_modules
    )
    platform = sorted((ROOT / "agents" / "sql").glob("*_v2_*.sql"))
    assert [int(path.name[:3]) for path in platform] == [
        *range(190, 391, 10), 420, 430, 510, 520, 530, 540, 550, 560, 570, 580, 590,
    ]
    assert len(list((ROOT / "agents" / "sql" / "rollback").glob("*_v2_*.sql"))) == 32


def test_populated_canonical_constraints_are_not_valid():
    for path in (PROPOSED / "versions").glob("v2a*.py"):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        class CaptureOperations:
            statements: ClassVar[list[str]] = []

            @classmethod
            def execute(cls, statement) -> None:
                cls.statements.append(str(statement))

        module.op = CaptureOperations
        module.upgrade()
        clauses = [
            statement for statement in CaptureOperations.statements if "ADD CONSTRAINT" in statement
        ]
        if path.name == "v2a05_hub_assignment.py":
            assert not clauses
            assert any("center_method_version" in statement for statement in CaptureOperations.statements)
            continue
        assert clauses, path.name
        assert all("NOT VALID" in clause for clause in clauses), path.name


def test_platform_sql_never_alters_canonical_tables():
    prohibited = re.compile(
        r"\bALTER\s+TABLE\s+(actor|hub|hub_actor|event|person)\b", re.IGNORECASE
    )
    for path in (ROOT / "agents" / "sql").glob("*_v2_*.sql"):
        assert not prohibited.search(path.read_text(encoding="utf-8")), path.name


def test_no_forbidden_overlap_queue_name_in_v2_artifacts():
    paths = list((ROOT / "agents" / "sql").glob("*_v2_*.sql")) + [
        ROOT / "src" / "db" / "models_v2.py",
        V2_CONFIG,
        ROOT / "agents" / "common" / "hub_assignment.py",
        ROOT / "agents" / "common" / "hub_centers.py",
    ]
    assert all("hub_overlap" not in path.read_text(encoding="utf-8") for path in paths)


def test_models_v2_is_not_imported_by_application_or_autogenerate():
    offenders = []
    for root_name in ("src", "agents", "scripts", "migrations"):
        for path in (ROOT / root_name).rglob("*.py"):
            if path == ROOT / "src" / "db" / "models_v2.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "src.db.models_v2":
                    offenders.append(path.relative_to(ROOT))
                if isinstance(node, ast.Import) and any(
                    alias.name == "src.db.models_v2" for alias in node.names
                ):
                    offenders.append(path.relative_to(ROOT))
    assert not offenders
    env_source = (ROOT / "migrations" / "env.py").read_text(encoding="utf-8")
    model_source = (ROOT / "src" / "db" / "models.py").read_text(encoding="utf-8")
    assert "models_v2" not in env_source
    assert "models_v2" not in model_source
    assert V2Base.metadata is not Base.metadata
    assert "actor_fact" not in Base.metadata.tables


def test_pending_defaults_are_configured_safely():
    config = yaml.safe_load(V2_CONFIG.read_text(encoding="utf-8"))
    assert config["defaults_pending_ghus_confirmation"] is True
    assert config["execution"] == {"dry_run_default": True, "require_explicit_live_flag": True}
    assert config["people"]["discovery_enabled"] is False
    assert config["people"]["contact_collection_enabled"] is False
    assert config["hubs"]["minimum_verified_independent_families"] == 10
    assert config["hubs"]["minimum_categories"] == 5
    assert config["hubs"]["default_radius_miles"] == 200
    assert config["hubs"]["core_radius_miles"] == 50
    assert config["hubs"]["center_drift_review_threshold_miles"] == 25
    assert config["hubs"]["preserve_phase1_names"] is True
    assert config["hubs"]["preserve_phase1_memberships"] is True
    assert config["hubs"]["detection"] == {
        "hub_trigger_statuses": ["verified"],
        "hub_min_actors": 10,
        "hub_min_categories": 5,
        "hub_core_radius_miles": 50,
        "hub_radius_miles": 200,
        "proposal_method_version": "hub_proposal_v1",
        "family_fingerprint_version": "hub_family_set_v1",
    }
    assert config["events"]["blanket_sweep_enabled"] is False


def test_legacy_models_remain_usable_until_ordered_rename_phase():
    actor = Actor(actor_type="company", verification_status="parked")
    person = Person(verification_status="imported")
    assert actor.actor_type == "company"
    assert actor.verification_status == "parked"
    assert person.verification_status == "imported"
    assert "actor_type" in Actor.__table__.c
    assert "actor_category" in V2Base.metadata.tables["actor"].c


@pytest.fixture(scope="module")
def v2_engine() -> Engine:
    raw_url = os.getenv("V2_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("V2_TEST_DATABASE_URL is required for live schema contract tests")
    url = make_url(raw_url)
    assert url.get_backend_name() == "postgresql"
    assert url.host in {"127.0.0.1", "localhost"}
    assert url.port == 55432
    assert (url.database or "").endswith("_test")
    engine = create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()


def test_isolated_database_contains_v2_schema(v2_engine: Engine):
    database = inspect(v2_engine)
    assert V2_TABLES <= set(database.get_table_names())
    # Final contract after migration 500: transitional views and columns are gone.
    assert not {"actor_v1_compat", "staged_record_agent3_compat", "actor_profile_current"} & set(
        database.get_view_names()
    )
    actor_columns = {column["name"] for column in database.get_columns("actor")}
    assert {"actor_category", "category_type", "status", "source_origin", "city",
            "alt_names"} <= actor_columns
    assert not {"actor_type", "actor_type_raw", "verification_status", "record_status",
                "state", "location_city", "alternate_names", "primary_technical_focus",
                "funding_summary", "estimated_trl"} & actor_columns
    assert not {"organization_hierarchy", "actor_profile", "actor_capability_fact"} & set(
        database.get_table_names()
    )


def test_orm_columns_match_isolated_v2_database(v2_engine: Engine):
    database = inspect(v2_engine)
    for table_name in sorted(V2_TABLES | {"actor", "person", "event", "hub", "hub_actor"}):
        database_columns = {column["name"] for column in database.get_columns(table_name)}
        orm_columns = set(V2Base.metadata.tables[table_name].columns.keys())
        assert orm_columns == database_columns, table_name


def test_reference_seed_counts(v2_engine: Engine):
    """The reference data is complete, whichever catalog the database holds.

    A database that has had agents/sql/510 applied carries the Intern Guide's
    69 selectable types plus the retired Phase 5 rows; one that has not carries
    the 65 Phase 5 types and nothing retired. Both are valid states, so the
    assertion is on what must be true of either: 12 categories, every category
    with a selectable catch-all, and no type row ever deleted.
    """

    fixed = {
        "actor_category_definition": 12,
        "region_definition": 7,
        "region_state": 51,
        "source_origin_definition": 7,
    }
    with v2_engine.connect() as connection:
        actual = {
            table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in fixed
        }
        selectable = connection.execute(
            text("SELECT count(*) FROM actor_category_type_definition WHERE active")
        ).scalar_one()
        total = connection.execute(
            text("SELECT count(*) FROM actor_category_type_definition")
        ).scalar_one()
        catch_alls = connection.execute(
            text(
                "SELECT count(*) FROM actor_category_definition c WHERE EXISTS ("
                " SELECT 1 FROM actor_category_type_definition t"
                " WHERE t.category_code=c.category_code AND t.active"
                "   AND t.type_code IN ('not_applicable','other'))"
            )
        ).scalar_one()
    assert actual == fixed
    assert selectable in (65, 69), (
        f"expected the Phase 5 catalog (65) or the Intern Guide catalog (69), found {selectable}"
    )
    # Retiring never deletes, so the total can only grow.
    assert total >= selectable
    if selectable == 69:
        assert total > 69, "applying 510 must keep the superseded Phase 5 rows"
    # Every category can always be answered, even when nothing listed fits.
    assert catch_alls == 12


def test_phase3_record_creation_dry_run_executes_then_rolls_back(v2_engine: Engine):
    with v2_engine.connect() as connection:
        before = {
            table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in ("actor", "actor_fact", "review_item")
        }
    session = sessionmaker(bind=v2_engine)()
    try:
        staged = StagedRecord(
            run_id=str(uuid.uuid4()),
            raw_document_id=None,
            entity_type="actor",
            natural_key="phase3-isolated-dry-run",
            source_url="https://phase3.example.org",
            payload={},
            normalized_payload={
                "name": "Phase 3 Isolated Dry Run",
                "website": "https://phase3.example.org",
                "sector_match": "in_sector",
                "actor_category": "company",
                "category_type": "small_mid_size",
                "classification_evidence": {"main_job": "Commercial technology company."},
            },
            prompt_version="actor_v2",
            extracted_at="2026-09-25T00:00:00+00:00",
        )
        result = map_new_actor(
            staged,
            RouteDecision(zone="create", score=0.0),
            session=session,
            live=False,
        )
    finally:
        session.close()

    assert result.action == "would_create"
    assert result.dry_run is True
    assert result.step_trace == list(ACTOR_MAPPING_STEPS)
    with v2_engine.connect() as connection:
        after = {
            table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in before
        }
    assert after == before


def test_append_only_and_role_permissions(v2_engine: Engine):
    verification_id = uuid.uuid4()
    with v2_engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("SET LOCAL ROLE service_role"))
            connection.execute(
                text(
                    "INSERT INTO record_verification (verification_id,entity_type,entity_id,decision,decided_by) VALUES (:id,'event',:entity,'parked','phase2-test')"
                ),
                {"id": verification_id, "entity": uuid.uuid4()},
            )
            with pytest.raises(DBAPIError, match="permission denied"):
                connection.execute(
                    text("DELETE FROM record_verification WHERE verification_id=:id"),
                    {"id": verification_id},
                )
        finally:
            transaction.rollback()

    with v2_engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(
                text(
                    "INSERT INTO record_verification (verification_id,entity_type,entity_id,decision,decided_by) VALUES (:id,'event',:entity,'parked','phase2-test')"
                ),
                {"id": verification_id, "entity": uuid.uuid4()},
            )
            with pytest.raises(DBAPIError, match="append-only"):
                connection.execute(
                    text("DELETE FROM record_verification WHERE verification_id=:id"),
                    {"id": verification_id},
                )
        finally:
            transaction.rollback()

    denied_statements = (
        "INSERT INTO record_verification (entity_type,entity_id,decision,decided_by) VALUES ('event',gen_random_uuid(),'parked','agent')",
        "DELETE FROM actor WHERE false",
        "UPDATE actor SET ghus_notes='forbidden' WHERE false",
    )
    for statement in denied_statements:
        with v2_engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("SET LOCAL ROLE authenticated"))
                with pytest.raises(DBAPIError, match="permission denied|row-level security"):
                    connection.execute(text(statement))
            finally:
                transaction.rollback()

    with v2_engine.connect() as connection:
        for role in ("anon", "authenticated", "service_role"):
            for table in ("actor", "hub", "event", "person", "hub_actor"):
                may_delete = connection.execute(
                    text("SELECT has_table_privilege(:role, :table, 'DELETE')"),
                    {"role": role, "table": table},
                ).scalar_one()
                assert may_delete is False, f"{role} unexpectedly may DELETE {table}"


def test_conformance_fixes_close_their_findings_and_respect_the_track_split():
    """530 and 545 close the audit's gaps without crossing the track boundary."""

    platform = (ROOT / "agents/sql/530_v2_conformance_fixes.sql").read_text(encoding="utf-8")
    canonical = (
        ROOT / "migrations/proposed/deferred/545_v2_canonical_conformance.sql"
    ).read_text(encoding="utf-8")

    # F1: collection_run can describe a run, and the initiator stays nullable
    # because there is no authenticated identity yet.
    for column in (
        "trigger_type", "cadence", "initiated_by", "config_snapshot",
        "found_count", "deduplicated_count", "staged_count", "review_item_count",
    ):
        assert column in platform, f"collection_run.{column} is missing"
    initiated = platform.split("ADD COLUMN IF NOT EXISTS initiated_by")[1][:40]
    assert "text" in initiated and "NOT NULL" not in initiated, (
        "initiated_by must stay nullable: there is no authenticated identity yet, "
        "and an unknown initiator is never defaulted"
    )

    # F14: the UM6P/OCP master list and its three states, named as 5.5 names them.
    assert "CREATE TABLE IF NOT EXISTS strategic_entity" in platform
    assert "CREATE TABLE IF NOT EXISTS actor_strategic_connection_check" in platform
    for state in ("'found'", "'not_found_in_sources_read'", "'not_yet_checked'"):
        assert state in platform, f"the {state} state is missing"

    # F7: records are guarded, not just their evidence.
    assert "ghus_guard_no_delete" in platform
    for table in ("actor", "person", "event", "hub", "hub_actor", "actor_topic", "actor_location"):
        assert f"'{table}'" in platform, f"{table} has no delete guard"

    # F11 and person verification.
    assert "actor_ranking_university_only" in platform
    assert "CREATE TABLE IF NOT EXISTS person_verification_event" in platform
    # Same honesty rule as actor_verification_event: no fake reviewer, no fake date.
    assert "ck_person_verification_origin" in platform

    # The canonical-table work is in the other track, and only there.
    assert "fk_actor_category_type" in canonical
    assert "is_current" in canonical
    assert "fk_actor_category_type" not in platform
    assert not re.search(
        r"\bALTER\s+TABLE\s+(actor|hub|hub_actor|event|person)\b", platform, re.IGNORECASE
    )

    # Nothing is backfilled and nothing is dropped by either file.
    for text_body, name in ((platform, "530"), (canonical, "545")):
        assert "DROP TABLE" not in text_body, f"{name} drops a table"
        assert "DELETE FROM" not in text_body, f"{name} deletes rows"
