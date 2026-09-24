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
    "proposed_hub",
    "proposed_hub_member",
    "proposed_hub_decision",
    "review_item",
    "review_item_decision",
    "canonical_write_audit",
}


def _manifest() -> list[dict]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["logical_migrations"]


def test_manifest_has_16_ordered_reversible_migrations():
    steps = _manifest()
    assert [step["id"] for step in steps] == [f"{number:03d}" for number in range(1, 17)]
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
    assert len(proposal_modules) == 4
    assert all(
        "down_revision = None" in path.read_text(encoding="utf-8") for path in proposal_modules
    )
    platform = sorted((ROOT / "agents" / "sql").glob("*_v2_*.sql"))
    assert [int(path.name[:3]) for path in platform] == list(range(190, 341, 10))
    assert len(list((ROOT / "agents" / "sql" / "rollback").glob("*_v2_*.sql"))) == 16


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
    assert {"actor_v1_compat", "staged_record_agent3_compat", "actor_profile_current"} <= set(
        database.get_view_names()
    )
    actor_columns = {column["name"] for column in database.get_columns("actor")}
    assert {"actor_category", "category_type", "record_status", "source_origin"} <= actor_columns
    assert "actor_type" not in actor_columns
    assert "verification_status" not in actor_columns


def test_orm_columns_match_isolated_v2_database(v2_engine: Engine):
    database = inspect(v2_engine)
    for table_name in sorted(V2_TABLES | {"actor", "person", "event", "hub", "hub_actor"}):
        database_columns = {column["name"] for column in database.get_columns(table_name)}
        orm_columns = set(V2Base.metadata.tables[table_name].columns.keys())
        assert orm_columns == database_columns, table_name


def test_reference_seed_counts(v2_engine: Engine):
    expected = {
        "actor_category_definition": 12,
        "actor_category_type_definition": 65,
        "region_definition": 7,
        "region_state": 51,
        "source_origin_definition": 4,
    }
    with v2_engine.connect() as connection:
        actual = {
            table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in expected
        }
    assert actual == expected


def test_append_only_and_role_permissions(v2_engine: Engine):
    verification_id = uuid.uuid4()
    with v2_engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("SET LOCAL ROLE service_role"))
            connection.execute(
                text(
                    "INSERT INTO record_verification (verification_id,entity_type,entity_id,decision,decided_by) VALUES (:id,'actor',:entity,'parked','phase2-test')"
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
                    "INSERT INTO record_verification (verification_id,entity_type,entity_id,decision,decided_by) VALUES (:id,'actor',:entity,'parked','phase2-test')"
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
        "INSERT INTO record_verification (entity_type,entity_id,decision,decided_by) VALUES ('actor',gen_random_uuid(),'parked','agent')",
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
