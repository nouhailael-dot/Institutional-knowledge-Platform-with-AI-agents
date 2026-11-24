"""The package for migration 750 (remove the unused tables) stays consistent.

See migrations/proposed/unused_tables_750/README.md.
"""

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFERRED = ROOT / "migrations" / "proposed" / "deferred"
PACKAGE = ROOT / "migrations" / "proposed" / "unused_tables_750"
MIGRATION = DEFERRED / "750_remove_unused_tables.sql"
ROLLBACK = DEFERRED / "rollback" / "750_remove_unused_tables.sql"
FILES = [MIGRATION, ROLLBACK, *(PACKAGE / n for n in ("preflight.sql", "ledger.sql", "verify.sql",
                                                     "restore_migration_snapshot.sql"))]
REMOVED = ["organization_ranking", "organization_evaluation", "event_scoring", "fetched_document",
           "canonical_write_audit", "contact_collection_authorization", "query_log", "migration_snapshot"]


def test_ledger_and_verify_carry_the_migration_checksum():
    digest = hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
    assert f"('750', 'migrations/proposed/deferred/750_remove_unused_tables.sql', '{digest}')" in (
        PACKAGE / "ledger.sql").read_text(encoding="utf-8")
    assert digest in (PACKAGE / "verify.sql").read_text(encoding="utf-8")


def test_files_are_lf_so_checksums_are_the_same_on_every_computer():
    for path in FILES:
        assert b"\r\n" not in path.read_bytes(), path.name


def test_it_drops_only_the_unused_tables_and_keeps_the_planned_ones():
    sql = MIGRATION.read_text(encoding="utf-8")
    dropped = re.findall(r"^DROP TABLE (?:public|compass)\.(\w+);", sql, flags=re.MULTILINE)
    assert sorted(dropped) == sorted(REMOVED)
    assert re.findall(r"^DROP VIEW public\.(\w+);", sql, flags=re.MULTILINE) == ["actor_ranking", "actor_evaluation"]
    for kept in ("challenge", "strategic_document", "strategic_entity", "organization_strategic_connection_check",
                 "organization_relevance"):
        assert f"DROP TABLE public.{kept};" not in sql
    assert "750 needs 720" in sql and "never filled now has rows" in sql


def test_the_rollback_and_the_snapshot_file_bring_everything_back():
    sql = ROLLBACK.read_text(encoding="utf-8")
    for table in REMOVED:
        assert re.search(rf"CREATE TABLE (public|compass)\.{table} \(", sql), table
    assert "CREATE VIEW public.actor_ranking" in sql and "CREATE VIEW public.actor_evaluation" in sql
    assert "CREATE FUNCTION public.ghus_guard_ranking_is_university()" in sql
    snapshot = (PACKAGE / "restore_migration_snapshot.sql").read_text(encoding="utf-8")
    assert snapshot.count("INSERT INTO compass.migration_snapshot") == 256
    assert "ON CONFLICT (migration_id, object_name) DO NOTHING" in snapshot
