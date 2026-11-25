"""The package for migration 810 (remove the unused tables) stays consistent.

See migrations/proposed/unused_tables_810/README.md.
"""

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFERRED = ROOT / "migrations" / "proposed" / "deferred"
PACKAGE = ROOT / "migrations" / "proposed" / "unused_tables_810"
MIGRATION = DEFERRED / "810_remove_unused_tables.sql"
ROLLBACK = DEFERRED / "rollback" / "810_remove_unused_tables.sql"
FILES = [MIGRATION, ROLLBACK, *(PACKAGE / n for n in ("preflight.sql", "ledger.sql", "verify.sql"))]
REMOVED = ["actor_ranking", "actor_evaluation", "event_scoring", "fetched_document", "canonical_write_audit",
           "contact_collection_authorization", "query_log", "proposal", "hub_center_review", "person_topic",
           "legacy_migration_record", "actor_category_migration_audit", "hub_actor_removed", "hub_removed",
           "review_queue", "alembic_version", "schema_migrations"]
FUNCTIONS = ["ghus_guard_ranking_is_university", "ghus_pre_cutover_data_loss_audit"]
KEPT = ["migration_snapshot", "challenge", "actor_relevance", "partnership_profile", "event_sector",
        "actor_merge_log", "strategic_document", "strategic_entity", "actor_strategic_connection_check",
        "architecture_v2_cutover_attestation", "architecture_v2_cutover_baseline"]


def test_ledger_and_verify_carry_the_migration_checksum():
    digest = hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
    assert f"('810', 'migrations/proposed/deferred/810_remove_unused_tables.sql', '{digest}')" in (
        PACKAGE / "ledger.sql").read_text(encoding="utf-8")
    assert digest in (PACKAGE / "verify.sql").read_text(encoding="utf-8")


def test_files_are_lf_so_checksums_are_the_same_on_every_computer():
    for path in FILES:
        assert b"\r\n" not in path.read_bytes(), path.name


def test_it_drops_only_the_unused_tables_after_800():
    sql = MIGRATION.read_text(encoding="utf-8")
    dropped = re.findall(r"^DROP TABLE public\.(\w+);", sql, flags=re.MULTILINE)
    assert sorted(dropped) == sorted(REMOVED)
    assert re.findall(r"^DROP FUNCTION public\.(\w+)\(\);", sql, flags=re.MULTILINE) == FUNCTIONS
    for kept in KEPT:
        assert not re.search(rf"^DROP \w+ (public|compass)\.{kept}\b", sql, flags=re.MULTILINE), kept
    assert "810 needs 800" in sql and "never filled now has rows" in sql and "810 is already applied" in sql


def test_the_rollback_brings_back_every_table_function_and_grant():
    sql = ROLLBACK.read_text(encoding="utf-8")
    for table in REMOVED:
        assert re.search(rf"CREATE TABLE public\.{table} \(", sql), table
    for function in FUNCTIONS:
        assert f"CREATE OR REPLACE FUNCTION public.{function}()" in sql, function
    assert "COMMENT ON FUNCTION public.ghus_pre_cutover_data_loss_audit()" in sql
    assert "GRANT ALL ON TABLE public.review_queue TO service_role;" in sql
    assert sql.rstrip().endswith("COMMIT;")


def test_the_platform_no_longer_reads_the_removed_tables():
    platform = ROOT.parent
    for path in (platform / "src" / "browse.py", platform / "src" / "datafeed" / "contract.py"):
        assert "person_topic" not in path.read_text(encoding="utf-8").replace(
            "person_topic was never filled", ""), path.name
    resolver = (ROOT / "src" / "ML" / "entity_resolution" / "resolve_or_create.py").read_text(encoding="utf-8")
    assert "INSERT INTO review_queue" not in resolver
    decisions = (ROOT / "agents" / "enrichment" / "decisions.py").read_text(encoding="utf-8")
    assert "hub_center_review (" not in decisions and "FROM hub_center_review" not in decisions
