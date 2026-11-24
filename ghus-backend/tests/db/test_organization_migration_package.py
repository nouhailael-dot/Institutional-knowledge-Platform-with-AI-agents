"""The package for migration 720 (actor -> organization names) stays consistent.

No database: checks bytes and text only. The rehearsal on a production copy is
described in migrations/proposed/organization_720/README.md.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFERRED = ROOT / "migrations" / "proposed" / "deferred"
PACKAGE = ROOT / "migrations" / "proposed" / "organization_720"
MIGRATION = DEFERRED / "720_organization_names.sql"
ROLLBACK = DEFERRED / "rollback" / "720_organization_names.sql"


def test_ledger_and_verify_carry_the_migration_checksum():
    digest = hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
    ledger = (PACKAGE / "ledger.sql").read_text(encoding="utf-8")
    assert f"('720', 'migrations/proposed/deferred/720_organization_names.sql', '{digest}')" in ledger
    assert ledger.count(digest) == 2                 # the insert and its postcondition
    assert digest in (PACKAGE / "verify.sql").read_text(encoding="utf-8")


def test_files_are_lf_so_checksums_are_the_same_on_every_computer():
    for path in [MIGRATION, ROLLBACK, *PACKAGE.glob("*.sql")]:
        assert b"\r\n" not in path.read_bytes(), path.name


def test_the_files_are_what_the_generator_makes_from_the_recorded_catalog():
    """Editing a generated file by hand would bypass the review: rebuild instead."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("generate_720", PACKAGE / "generate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    catalog = json.loads((PACKAGE / "catalog.json").read_text(encoding="utf-8"))
    catalog["relations"] = [tuple(r) for r in catalog["relations"]]
    built = module.build(catalog)
    assert built["migration"].encode() == MIGRATION.read_bytes()
    assert built["rollback"].encode() == ROLLBACK.read_bytes()
    for name in ("preflight", "verify", "ledger"):
        assert built[name].encode() == (PACKAGE / f"{name}.sql").read_bytes(), name


def test_every_old_name_gets_a_closed_stand_in_and_the_rollback_removes_it():
    body = MIGRATION.read_text(encoding="utf-8")
    rollback = ROLLBACK.read_text(encoding="utf-8")
    catalog = json.loads((PACKAGE / "catalog.json").read_text(encoding="utf-8"))
    assert len(catalog["relations"]) == 27
    for name, _kind in catalog["relations"]:
        assert f"CREATE VIEW public.{name} WITH (security_invoker = true)" in body, name
        assert f"REVOKE ALL ON public.{name} FROM anon, authenticated;" in body, name
        assert f"DROP VIEW public.{name};" in rollback, name
    # The originals are saved before anything changes, and restored by the rollback.
    assert body.index("INSERT INTO compass.migration_snapshot") < body.index("ALTER TABLE public.actor RENAME")
    assert "EXECUTE d.definition" in rollback


def test_internal_codes_and_the_session_key_are_left_for_stage_two():
    body = MIGRATION.read_text(encoding="utf-8")
    assert "edge.subject_type='actor'" in body                  # a type code, not a name
    assert "ghus_guard_notes_column" not in body                 # the guard reading ghus.actor_is_human stays
    assert "'actor_fact_id', f.organization_fact_id" in body     # the JSON key the code reads
