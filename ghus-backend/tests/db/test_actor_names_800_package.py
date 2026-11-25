"""The package for migration 800 (organization -> actor names, back again) stays consistent.

No database: checks bytes and text only. The rehearsal on a copy of production is
described in migrations/proposed/actor_800/README.md.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFERRED = ROOT / "migrations" / "proposed" / "deferred"
PACKAGE = ROOT / "migrations" / "proposed" / "actor_800"
MIGRATION = DEFERRED / "800_actor_names.sql"
ROLLBACK = DEFERRED / "rollback" / "800_actor_names.sql"


def _catalog() -> dict:
    catalog = json.loads((PACKAGE / "catalog.json").read_text(encoding="utf-8"))
    catalog["relations"] = [tuple(r) for r in catalog["relations"]]
    return catalog


def test_ledger_and_verify_carry_the_migration_checksum():
    digest = hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
    ledger = (PACKAGE / "ledger.sql").read_text(encoding="utf-8")
    assert f"('800', 'migrations/proposed/deferred/800_actor_names.sql', '{digest}')" in ledger
    assert ledger.count(digest) == 2
    assert digest in (PACKAGE / "verify.sql").read_text(encoding="utf-8")
    assert _catalog()["sha256"] == digest


def test_files_are_lf_so_checksums_are_the_same_on_every_computer():
    for path in [MIGRATION, ROLLBACK, *PACKAGE.glob("*.sql")]:
        assert b"\r\n" not in path.read_bytes(), path.name


def test_the_files_are_what_the_generator_makes_from_the_recorded_catalog():
    """Editing a generated file by hand would bypass the review: rebuild instead."""
    spec = importlib.util.spec_from_file_location("generate_800", PACKAGE / "generate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    built = module.build(_catalog())
    assert built["migration"].encode() == MIGRATION.read_bytes()
    assert built["rollback"].encode() == ROLLBACK.read_bytes()
    for name in ("preflight", "verify", "ledger"):
        assert built[name].encode() == (PACKAGE / f"{name}.sql").read_bytes(), name


def test_every_stand_in_goes_before_the_renames_and_comes_back_in_the_rollback():
    body = MIGRATION.read_text(encoding="utf-8")
    rollback = ROLLBACK.read_text(encoding="utf-8")
    stand_ins = [s["name"] for s in _catalog()["stand_ins"]]
    assert len(stand_ins) == 26
    first_rename = body.index("ALTER TABLE public.organization RENAME TO actor;")
    for name in stand_ins:
        assert body.index(f"DROP VIEW public.{name};") < first_rename, name
        assert f"CREATE VIEW public.{name} WITH (security_invoker=true)" in rollback, name
        assert f"REVOKE ALL ON public.{name} FROM anon, authenticated;" in rollback, name
    # Saved before anything changes; restored by the rollback.
    assert body.index("INSERT INTO compass.migration_snapshot") < body.index("DROP VIEW public.")
    assert "EXECUTE d.definition" in rollback


def test_nothing_nouhaila_built_is_dropped():
    """Only names change: no table, column or data is removed, and the template view stays."""
    body = MIGRATION.read_text(encoding="utf-8")
    assert not re.search(r"DROP (TABLE|COLUMN|SCHEMA)|DELETE FROM|TRUNCATE|ALTER TABLE \S+ DROP", body)
    dropped_views = set(re.findall(r"DROP VIEW public\.(\w+);", body))
    assert dropped_views == {s["name"] for s in _catalog()["stand_ins"]}
    assert "ALTER VIEW public.organization_template RENAME TO actor_template;" in body
    # The label people read keeps saying Organization.
    assert "Corporate Organization" not in body or "UPDATE" not in body.split("Corporate Organization")[0][-200:]


def test_the_rewritten_functions_no_longer_name_organization():
    body = MIGRATION.read_text(encoding="utf-8")
    functions = body.split("-- 5. Functions")[1].split("-- 6.")[0]
    created = re.findall(r"CREATE OR REPLACE FUNCTION public\.(\w+)", functions)
    assert len(created) == 9 and not [f for f in created if "organization" in f]
    for definition in re.split(r"(?=CREATE OR REPLACE FUNCTION)", functions)[1:]:
        assert "organization" not in definition.split("$function$")[1], definition[:80]
