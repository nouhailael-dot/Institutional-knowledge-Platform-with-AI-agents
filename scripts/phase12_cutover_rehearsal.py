"""Rehearse the whole Architecture V2 cutover on a fresh local restore of the full dump.

LOCAL REHEARSAL ONLY. The target database name is fixed to
`ghus_v2_phase12_rehearsal_test` on 127.0.0.1:55432 and is dropped and recreated.
Supabase is never contacted.

Decisions that only GHUS can make do not exist yet. To prove the schema can
reach migration 500, this rehearsal applies clearly labelled TEST-ONLY
stand-ins for them (category confirmations, aggregate dispositions, the empty
"Mining Hubs" hub, topic approval and the cutover attestation). Every stand-in
is recorded in the evidence file and must be replaced by real GHUS decisions
before the production cutover.

Every migration stage runs through scripts/architecture_v2_release.py, exactly as
the schema owner will run it: baseline -> expand -> gazetteer -> backfill ->
validate -> data-loss audit (Python and SQL function, must pass) -> topic (TEST-ONLY
approval) -> TEST-ONLY decisions -> contract -> TEST-ONLY attestation -> cutover
-> every SQL stage re-run (must be a no-op) -> invariants.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parents[1]
DATABASE = "ghus_v2_phase12_rehearsal_test"
HOST, PORT, ROLE = "127.0.0.1", 55432, "ghus_test"
DUMP = Path(r"C:\Users\Ismail\GHUS-data\backups\ghus_production_full_20260928T170256Z.dump")
DUMP_SHA256 = "08d9ce68efae470f553cb4d8b0324c0c570f7037450d8af38b5a43da07bf424b"
PG_BIN = Path(os.environ.get("GHUS_PG_BIN", r"C:\Program Files\PostgreSQL\17\bin"))
EVIDENCE = ROOT / "docs/evidence/phase12_cutover_rehearsal_2026-10-06.json"
AUDIT = ROOT / "docs/evidence/pre_cutover_data_loss_audit_rehearsal_2026-10-06.json"
TEST_ONLY = "TEST-ONLY rehearsal stand-in for a GHUS decision"
TEST_ONLY_SQL = ROOT / "tests/fixtures/phase12_rehearsal_test_only_decisions.sql"
TOPIC_CSV = ROOT / "docs/evidence/phase12_topic_proposal.csv"
URL = f"postgresql://{ROLE}@{HOST}:{PORT}/{DATABASE}"


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.update({
        "V2_TEST_DATABASE_URL": URL,
        "V2_PHASE12_POLICY_DATABASE_URL": URL,
        "GHUS_REHEARSAL_DATABASE_URL": URL,
        # Never let any imported module fall back to the production .env URL.
        "DATABASE_URL": "postgresql://blocked@127.0.0.1:1/blocked_test",
    })
    return env


def _run(args: list[str], log: list[str]) -> str:
    completed = subprocess.run(args, cwd=ROOT, env=_env(), text=True, capture_output=True,
                               check=False)
    output = (completed.stdout + completed.stderr).strip()
    log.append(f"$ {' '.join(Path(a).name if i == 0 else a for i, a in enumerate(args))}\n{output}")
    if completed.returncode != 0:
        raise RuntimeError(f"step failed: {args[1:3]}\n{output}")
    return output


def _psql(sql: str, database: str = DATABASE) -> None:
    subprocess.run([str(PG_BIN / "psql.exe"), "-w", "-h", HOST, "-p", str(PORT), "-U", ROLE,
                    "-d", database, "-v", "ON_ERROR_STOP=1", "-q", "-c", sql],
                   check=True, capture_output=True, text=True)


def _connect():
    return psycopg2.connect(URL, application_name="ghus_phase12_rehearsal")


def _scalar(sql: str):
    with _connect() as connection, connection.cursor() as cursor:
        cursor.execute(sql)
        return cursor.fetchone()[0]


def _invariants() -> dict[str, int]:
    return {table: _scalar(f"SELECT count(*) FROM {table}")
            for table in ("actor", "hub", "hub_actor", "event")}


def _sql_audit() -> list[dict[str, object]]:
    with _connect() as connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SELECT check_name,source_rows,destination_rows,passed "
                       "FROM ghus_pre_cutover_data_loss_audit()")
        return [dict(row) for row in cursor.fetchall()]


def _test_only_decisions() -> dict[str, object]:
    """Stand-ins for decisions GHUS has not made yet. Rehearsal database only."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from agents.review.admission import apply_category_decisions

    with _connect() as connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("""
            SELECT review_item_id::text, payload->>'proposed_category' category
            FROM review_item WHERE review_kind='category_doubt' AND status='pending'
              AND payload->>'is_true_aggregate'='false'
        """)
        proposals = cursor.fetchall()
    engine = create_engine(URL)
    try:
        with Session(engine) as session:
            confirmed = apply_category_decisions(session, {
                "decision_kind": "confirm_category", "reviewer": TEST_ONLY,
                "idempotency_key": "phase12-rehearsal-categories",
                "notes": TEST_ONLY,
                "items": [{"review_item_id": row["review_item_id"],
                           "actor_category": row["category"]} for row in proposals],
            })
    finally:
        engine.dispose()
    with _connect() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM review_item WHERE review_kind='category_doubt' "
                       "AND status='pending' AND payload->>'is_true_aggregate'='true'")
        aggregates = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM hub WHERE topic_id IS NULL")
        empty_hubs = cursor.fetchone()[0]
        cursor.execute(TEST_ONLY_SQL.read_text(encoding="utf-8"), {"who": TEST_ONLY})
        connection.commit()
    return {"categories_confirmed": confirmed["resolved"], "aggregates_stood_in": aggregates,
            "empty_hubs_stood_in": empty_hubs, "label": TEST_ONLY}


def main() -> int:
    log: list[str] = []
    started = datetime.now(UTC).isoformat()
    if not DATABASE.endswith("_rehearsal_test"):
        raise RuntimeError("rehearsal target must be a *_rehearsal_test database")
    digest = hashlib.sha256(DUMP.read_bytes()).hexdigest()
    if digest != DUMP_SHA256:
        raise RuntimeError("dump checksum mismatch")

    _psql(f"DROP DATABASE IF EXISTS {DATABASE}", "postgres")
    _psql(f"CREATE DATABASE {DATABASE}", "postgres")
    _psql("CREATE SCHEMA extensions; CREATE EXTENSION pgcrypto SCHEMA extensions; "
          'CREATE EXTENSION "uuid-ossp" SCHEMA extensions;')
    restore = subprocess.run([str(PG_BIN / "pg_restore.exe"), "-w", "-h", HOST, "-p", str(PORT),
                              "-U", ROLE, "-d", DATABASE, "--schema=public", "--no-owner",
                              "--no-privileges", str(DUMP)], capture_output=True, text=True,
                             check=False)
    restore_errors = [line for line in restore.stderr.splitlines() if "search_doc" not in line and "public.vector" not in line
                      and ("error" in line.casefold() or "erreur" in line.casefold())
                      and "ignor" not in line.casefold()]
    if restore_errors:
        raise RuntimeError("unexpected restore errors:\n" + "\n".join(restore_errors))
    baseline = _invariants()

    release = [sys.executable, "-m", "scripts.architecture_v2_release", "apply"]
    target = ["--database-url-env", "GHUS_REHEARSAL_DATABASE_URL"]
    for stage in ("baseline", "expand", "gazetteer", "backfill", "validate"):
        _run(release + [stage] + target, log)
    _run([sys.executable, "scripts/phase12_policy_proof.py"], log)
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    sql_audit = _sql_audit()
    if not audit["passed"] or not all(row["passed"] for row in sql_audit):
        raise RuntimeError("data-loss audit failed; migration 500 must not run")
    audit_sha256 = hashlib.sha256(AUDIT.read_bytes()).hexdigest()

    with tempfile.TemporaryDirectory() as scratch:
        approval = Path(scratch) / "topic_approval.json"
        approval.write_text(json.dumps({
            "approved_by": TEST_ONLY,
            "topic_proposal_sha256": hashlib.sha256(TOPIC_CSV.read_bytes()).hexdigest(),
        }), encoding="utf-8")
        _run(release + ["topic"] + target + ["--topic-approval", str(approval)], log)
    stand_ins = _test_only_decisions()
    _run(release + ["contract"] + target, log)
    with _connect() as connection, connection.cursor() as cursor:
        cursor.execute("""
            INSERT INTO architecture_v2_cutover_attestation
              (audit_name,artifact_sha256,passed,approved_by,approved_at,details)
            VALUES ('pre_cutover_data_loss_audit',%s,true,%s,now(),%s)
        """, (audit_sha256, "TEST-ONLY local rehearsal attestation (not a GHUS approval)",
              json.dumps({"audit_file": AUDIT.name, "database": DATABASE})))
        connection.commit()
    before_500 = _invariants()
    _run(release + ["cutover"] + target, log)
    rerun = "\n".join(
        _run(release + [stage] + target, log)
        for stage in ("expand", "backfill", "validate", "contract", "cutover")
    )
    after_500 = _invariants()
    legacy_columns = _scalar("""
        SELECT count(*) FROM information_schema.columns WHERE table_schema='public'
          AND table_name='actor' AND column_name IN ('actor_type','verification_status',
          'record_status','state','primary_technical_focus','funding_summary')
    """)
    legacy_tables = _scalar("""
        SELECT count(*) FROM information_schema.tables WHERE table_schema='public'
          AND table_name IN ('organization_hierarchy','actor_profile','actor_capability_fact')
    """)
    expected = {"actor": 965, "hub": 49, "hub_actor": 821, "event": 356}
    evidence = {
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "database": DATABASE,
        "production_contacted": False,
        "dump_sha256": digest,
        "restore_skipped": "search_doc (pgvector not installed locally; derived index)",
        "row_counts": {"restored": baseline, "before_500": before_500, "after_500": after_500},
        "invariants_hold": baseline == before_500 == after_500 == expected,
        "data_loss_audit_passed_before_500": audit["passed"],
        "sql_audit_function_before_500": sql_audit,
        "data_loss_audit_sha256": audit_sha256,
        "test_only_stand_ins": stand_ins,
        "attestation": "TEST-ONLY local rehearsal attestation (not a GHUS approval)",
        "migration_500_applied": legacy_columns == 0 and legacy_tables == 0,
        "manifest_rerun_noop": all(line.startswith("skipped") for line in rerun.splitlines()
                                   if line.strip()),
        "manifest_rerun_lines": len(rerun.splitlines()),
        "log": log,
    }
    EVIDENCE.write_text(json.dumps(evidence, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in evidence.items() if k != "log"}, indent=2, default=str))
    ok = (evidence["invariants_hold"] and evidence["migration_500_applied"]
          and evidence["manifest_rerun_noop"])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
