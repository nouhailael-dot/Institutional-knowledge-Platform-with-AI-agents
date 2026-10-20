"""Safety gates of the Architecture V2 cutover release tool."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts import architecture_v2_release as release

PG_BIN = Path(os.environ.get("GHUS_PG_BIN", r"C:\Program Files\PostgreSQL\17\bin"))
TEMPLATE = os.environ.get("V2_PHASE12_FULL_DATABASE_URL", "")
GATE_DB = "ghus_v2_phase12_gate_test"
GATE_URL = f"postgresql://ghus_test@127.0.0.1:55432/{GATE_DB}"
live = pytest.mark.skipif(
    "127.0.0.1:55432/ghus_v2_phase12_full_test" not in TEMPLATE,
    reason="V2_PHASE12_FULL_DATABASE_URL (pre-500 full copy) is required",
)


def test_release_manifest_matches_files_and_rehearsed_order():
    built = release.verify()
    ids = [step["id"] for step in built["steps"]]
    assert ids[-1] == "500"
    assert ids.index("489") < ids.index("490") < ids.index("486") < ids.index("405")
    assert {step["stage"] for step in built["steps"]} <= set(release.STAGES)


def test_database_url_is_never_accepted_as_the_target(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://ghus_test@127.0.0.1:55432/x_test")
    with pytest.raises(RuntimeError, match="not DATABASE_URL"):
        release._target("DATABASE_URL", None)


def test_non_test_target_needs_matching_owner_approval(monkeypatch, tmp_path):
    monkeypatch.setenv("GHUS_RELEASE_TARGET", "postgresql://user@db.example.org:5432/postgres")
    with pytest.raises(RuntimeError, match="owner-approval is required"):
        release._target("GHUS_RELEASE_TARGET", None)
    wrong = tmp_path / "approval.json"
    wrong.write_text(json.dumps({"approved_by": "owner", "target_host": "db.example.org",
                                 "release_manifest_sha256": "0" * 64}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="does not match"):
        release._target("GHUS_RELEASE_TARGET", wrong)
    right = tmp_path / "ok.json"
    right.write_text(json.dumps({
        "approved_by": "owner", "target_host": "db.example.org",
        "release_manifest_sha256": release._sha256(release.RELEASE_MANIFEST),
    }), encoding="utf-8")
    assert release._target("GHUS_RELEASE_TARGET", right).endswith("/postgres")


@pytest.fixture
def gate_db():
    psql = [str(PG_BIN / "psql.exe"), "-w", "-h", "127.0.0.1", "-p", "55432", "-U", "ghus_test",
            "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-q", "-c"]
    subprocess.run(psql + [f"DROP DATABASE IF EXISTS {GATE_DB}"], check=True)
    subprocess.run(psql + [f"CREATE DATABASE {GATE_DB} TEMPLATE ghus_v2_phase12_full_test"],
                   check=True)
    try:
        yield GATE_URL
    finally:
        subprocess.run(psql + [f"DROP DATABASE IF EXISTS {GATE_DB}"], check=True)


@live
def test_topic_stage_refuses_without_ghus_approval(gate_db):
    with pytest.raises(RuntimeError, match="topic-approval"):
        release.apply("topic", gate_db, topic_approval=None)


@live
def test_migration_500_refuses_without_attestation_and_on_failing_live_audit(gate_db):
    from sqlalchemy import create_engine, text

    with pytest.raises(Exception, match="has not passed"):
        release.apply("cutover", gate_db, topic_approval=None)
    engine = create_engine(gate_db.replace("postgresql://", "postgresql+psycopg2://"))
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO architecture_v2_cutover_attestation"
                "(audit_name,artifact_sha256,passed,approved_by,approved_at) VALUES "
                "('pre_cutover_data_loss_audit',repeat('0',64),true,'gate test',now())"))
            # A row added after the baseline makes the live audit fail.
            connection.execute(text(
                "INSERT INTO event(event_id,name) VALUES (gen_random_uuid(),'gate test event')"))
    finally:
        engine.dispose()
    with pytest.raises(Exception, match="fails on the current data"):
        release.apply("cutover", gate_db, topic_approval=None)
