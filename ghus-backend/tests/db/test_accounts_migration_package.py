"""The schema-owner package for migrations 700 and 710 stays consistent with the files.

No database: checks bytes and text only. The rehearsal on a production copy is
tests/db/rehearse_accounts_migrations.py.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFERRED = ROOT / "migrations" / "proposed" / "deferred"
PACKAGE = ROOT / "migrations" / "proposed" / "accounts_700_710"
FILES = {"700": DEFERRED / "700_compass_accounts.sql", "710": DEFERRED / "710_record_deletion_retention.sql"}
ROLLBACKS = [DEFERRED / "rollback" / "700_compass_accounts.sql", DEFERRED / "rollback" / "710_record_deletion_retention.sql"]


def test_ledger_checksums_match_the_committed_files():
    ledger = (PACKAGE / "ledger.sql").read_text(encoding="utf-8")
    for mid, path in FILES.items():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert f"('{mid}', 'migrations/proposed/deferred/{path.name}',\n     '{digest}')" in ledger, mid
        assert ledger.count(digest) == 2, f"{mid}: the insert and the postcondition both name it"


def test_files_are_lf_so_checksums_are_the_same_on_every_computer():
    for path in [*FILES.values(), *ROLLBACKS, *PACKAGE.glob("*.sql")]:
        assert b"\r\n" not in path.read_bytes(), path.name


def test_preflight_expects_exactly_what_710_checks():
    preflight = (PACKAGE / "preflight.sql").read_text(encoding="utf-8")
    body = FILES["710"].read_text(encoding="utf-8")
    hashes = set(re.findall(r"[0-9a-f]{32}", body.split("$pre$;")[0]))
    assert len(hashes) == 5                       # four guard bodies and actor_read's columns
    assert hashes <= set(re.findall(r"[0-9a-f]{32}", preflight))


def test_710_saves_what_its_rollback_restores():
    body = FILES["710"].read_text(encoding="utf-8")
    rollback = ROLLBACKS[1].read_text(encoding="utf-8")
    assert "CREATE TABLE compass.migration_snapshot" in body
    assert "pg_get_functiondef(p.oid)" in body and "pg_get_viewdef('public.actor_read'::regclass)" in body
    assert "EXECUTE saved.definition" in rollback and "DROP TABLE compass.migration_snapshot" in rollback
    assert "RAISE EXCEPTION '710 rollback: compass.deleted_record holds deletions; kept'" in rollback
