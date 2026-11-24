"""The package for migration 730 (remove two unused tables) stays consistent.

See migrations/proposed/unused_tables_730/README.md.
"""

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFERRED = ROOT / "migrations" / "proposed" / "deferred"
PACKAGE = ROOT / "migrations" / "proposed" / "unused_tables_730"
MIGRATION = DEFERRED / "730_remove_unused_tables.sql"
ROLLBACK = DEFERRED / "rollback" / "730_remove_unused_tables.sql"
FILES = [MIGRATION, ROLLBACK, *(PACKAGE / n for n in ("preflight.sql", "ledger.sql", "verify.sql"))]


def test_ledger_and_verify_carry_the_migration_checksum():
    digest = hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
    assert f"('730', 'migrations/proposed/deferred/730_remove_unused_tables.sql', '{digest}')" in (
        PACKAGE / "ledger.sql").read_text(encoding="utf-8")
    assert digest in (PACKAGE / "verify.sql").read_text(encoding="utf-8")


def test_files_are_lf_so_checksums_are_the_same_on_every_computer():
    for path in FILES:
        assert b"\r\n" not in path.read_bytes(), path.name


def test_it_drops_only_the_two_unused_tables_and_keeps_challenge():
    sql = MIGRATION.read_text(encoding="utf-8")
    drops = re.findall(r"^DROP (VIEW|TABLE|FUNCTION) (public\.\w+)", sql, flags=re.MULTILINE)
    assert drops == [("VIEW", "public.actor_ranking"), ("TABLE", "public.organization_ranking"),
                     ("FUNCTION", "public.ghus_guard_ranking_is_university"), ("TABLE", "public.query_log")]
    assert "DROP TABLE public.challenge" not in sql and "DROP TABLE public.strategic_document" not in sql
    assert "has rows; it is not unused" in sql and "730 needs 720" in sql


def test_the_rollback_recreates_every_dropped_object():
    sql = ROLLBACK.read_text(encoding="utf-8")
    for created in ("CREATE FUNCTION public.ghus_guard_ranking_is_university()",
                    "CREATE TABLE public.organization_ranking", "CREATE VIEW public.actor_ranking",
                    "CREATE TABLE public.query_log", "organization_ranking_university_only",
                    "organization_ranking_append_only"):
        assert created in sql, created
