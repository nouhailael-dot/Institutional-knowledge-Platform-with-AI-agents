from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "migrations" / "proposed" / "additive_apply_2026-09-28"
SCRIPTS = PACKAGE / "scripts"


def test_additive_helpers_accept_only_libpq_environment_and_pgpassfile():
    powershell = "\n".join(
        path.read_text(encoding="utf-8") for path in SCRIPTS.glob("*.ps1")
    )
    python = "\n".join(
        path.read_text(encoding="utf-8") for path in SCRIPTS.glob("*.py")
    )
    assert "DatabaseUrl" not in powershell
    assert 'os.environ.get("V2_ADDITIVE_DATABASE_URL"' not in python
    assert "PGPASSFILE" in powershell
    assert "PGPASSFILE" in python


def test_additive_helper_errors_redact_connection_secrets(monkeypatch):
    path = SCRIPTS / "db_connection.py"
    spec = importlib.util.spec_from_file_location("additive_db_connection_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    secret = "not-a-real-password"
    raw_url = "postgresql://" + "user:" + secret + "@database.invalid/postgres"
    monkeypatch.setenv("DATABASE_URL", raw_url)
    message = module.redact_error(RuntimeError(f"failed to parse {raw_url}; password={secret}"))
    assert secret not in message
    assert raw_url not in message
    assert message.count("[REDACTED]") >= 1
    assert os.environ["DATABASE_URL"] == raw_url


def test_additive_manifest_covers_170_drift_and_every_file_180_through_350():
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in manifest["logical_migrations"]] == [
        "170", "180", "190", "200", "210", "220", "230", "240", "250",
        "260", "270", "280", "290", "300", "310", "320", "330", "340", "350",
    ]
    assert (PACKAGE / "sql" / "310_v2_hub_proposals_additive.sql").is_file()
    assert (PACKAGE / "sql" / "350_v2_record_creation_additive.sql").is_file()


def test_status_mapping_and_phase3_breaking_check_are_held_safely():
    actor = (PACKAGE / "versions" / "v2a01_actor_identity_additive.py").read_text(
        encoding="utf-8"
    )
    phase3 = (PACKAGE / "sql" / "350_v2_record_creation_additive.sql").read_text(
        encoding="utf-8"
    )
    deferred = (PACKAGE / "deferred" / "350_v2_record_creation_breaking.sql").read_text(
        encoding="utf-8"
    )
    assert "ghus_legacy_record_status" in actor
    assert "WHEN 'verified'" not in actor
    assert "WHEN 'rejected'" not in actor
    assert "ALTER TABLE review_item" not in phase3
    assert "ALTER TABLE review_item" in deferred
