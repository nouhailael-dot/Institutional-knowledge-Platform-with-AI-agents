"""Rehearse migrations 700 (Compass accounts) and 710 (record deletion, 30-day
retention) together on an isolated copy of production, before the schema owner
applies them to Supabase.

    python -m tests.db.rehearse_accounts_migrations --database ghus_phase7_prodcopy_test

The copy is a local restore of the latest Supabase backup (pg_dump), so the
catalog is production's. Steps, each checked:

  1. fingerprint the catalog (tables, columns, constraints, indexes, triggers,
     functions, views, row security, schema grants)
  2. apply 700, then 710, exactly as committed (checksums printed)
  3. functional checks: compass tables all row-secured with no browser grants,
     seeded roles, the four Architecture V2 guards still refuse, the purge door
     opens only for a due deletion, actor_read hides a pending deletion, the
     deletion ledger cannot be deleted or rewritten, two pending deletions of one
     record are impossible, every foreign key to a deletable record is covered
     by the purge policy (none would block or be emptied by surprise)
  4. ledger rows for 700 and 710 (as the schema owner will record them)
  5. rollback 710 refuses while a deletion exists
  6. rollback 710, then 700: the catalog is identical to step 1
  7. apply both again: identical to after step 2

Refuses anything but a local *_test database on port 55432. Never reads DATABASE_URL.
Prints one JSON report; exit 1 on any failed check.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[2]
DEFERRED = ROOT / "migrations" / "proposed" / "deferred"
FILES = {
    "700": DEFERRED / "700_compass_accounts.sql",
    "710": DEFERRED / "710_record_deletion_retention.sql",
    "rollback_700": DEFERRED / "rollback" / "700_compass_accounts.sql",
    "rollback_710": DEFERRED / "rollback" / "710_record_deletion_retention.sql",
}
GUARDS = ("ghus_guard_no_delete", "ghus_reject_mutation", "ghus_guard_sector_link_append_only",
          "ghus_guard_subscription_run_append_only")
COMPASS_TABLES = {"permission", "role", "role_permission", "user_profile", "invitation", "audit_event",
                  "record_owner", "usage_event", "notification", "deleted_record"}
SCHEMAS = ("public", "compass")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(conn, schemas=SCHEMAS) -> dict[str, str]:
    queries = {
        "tables": """SELECT n.nspname, c.relname, c.relkind, c.relrowsecurity FROM pg_class c
                     JOIN pg_namespace n ON n.oid = c.relnamespace
                     WHERE n.nspname = ANY(%s) AND c.relkind IN ('r','v','m','p','S')""",
        "columns": """SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default
                      FROM information_schema.columns WHERE table_schema = ANY(%s)""",
        "constraints": """SELECT n.nspname, c.conrelid::regclass::text, c.conname, pg_get_constraintdef(c.oid)
                          FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace
                          WHERE n.nspname = ANY(%s)""",
        "indexes": "SELECT schemaname, indexname, indexdef FROM pg_indexes WHERE schemaname = ANY(%s)",
        "triggers": """SELECT n.nspname, t.tgname, pg_get_triggerdef(t.oid) FROM pg_trigger t
                       JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace
                       WHERE NOT t.tgisinternal AND n.nspname = ANY(%s)""",
        "functions": """SELECT n.nspname, p.proname, pg_get_function_identity_arguments(p.oid), md5(p.prosrc)
                        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = ANY(%s)""",
        "views": """SELECT schemaname, viewname, md5(definition) FROM pg_views WHERE schemaname = ANY(%s)""",
        "schemas": "SELECT nspname, nspacl::text FROM pg_namespace WHERE nspname = ANY(%s)",
    }
    out = {}
    for name, query in queries.items():
        rows = sorted(tuple(str(v) for v in r) for r in conn.execute(query, (list(schemas),)).fetchall())
        out[name] = hashlib.sha256(json.dumps(rows).encode()).hexdigest()[:16]
    return out


def run_file(conn, key: str) -> None:
    conn.execute(FILES[key].read_text(encoding="utf-8"))


def refused(conn, sql: str, params=None, *, setting: tuple[str, str] | None = None) -> bool:
    """True when the statement raises (and leaves the connection usable). ``setting``
    is set (transaction-local) first, in the same transaction."""
    try:
        with conn.transaction():
            if setting:
                conn.execute("SELECT set_config(%s, %s, true)", setting)
            conn.execute(sql, params)
        return False
    except psycopg.Error:
        return True


def script_refused(conn, key: str) -> bool:
    """Run a whole migration file (it has its own BEGIN/COMMIT); True when it raises."""
    try:
        run_file(conn, key)
        return False
    except psycopg.Error:
        if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
            conn.execute("ROLLBACK")
        return True


class Rollback(Exception):
    pass


def functional_checks(conn) -> dict[str, bool]:
    ok: dict[str, bool] = {}
    tables = {r[0]: r[1] for r in conn.execute(
        "SELECT c.relname, c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'compass' AND c.relkind = 'r'").fetchall()}
    ok["compass_tables_present"] = COMPASS_TABLES <= set(tables)
    ok["compass_tables_row_secured"] = all(tables.values())
    browser = [r[0] for r in conn.execute(
        "SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated')").fetchall()]
    ok["no_browser_grant_on_compass"] = all(not conn.execute(
        "SELECT has_schema_privilege(%s, 'compass', 'USAGE')", (role,)).fetchone()[0] for role in browser)
    ok["roles_seeded"] = {r[0] for r in conn.execute("SELECT code FROM compass.role").fetchall()} == \
        {"admin", "editor", "viewer"}
    ok["no_user_or_invitation_created"] = conn.execute(
        "SELECT (SELECT count(*) FROM compass.user_profile) + (SELECT count(*) FROM compass.invitation)"
    ).fetchone()[0] == 0

    actor_id, name = conn.execute(
        "SELECT actor_id::text, name FROM actor_read ORDER BY name LIMIT 1").fetchone()
    # The guards still refuse every other delete and update.
    ok["actor_delete_refused"] = refused(conn, "DELETE FROM actor WHERE actor_id = %s::uuid", (actor_id,))
    fact = conn.execute("SELECT actor_fact_id::text FROM actor_fact LIMIT 1").fetchone()
    ok["fact_update_refused"] = fact is None or refused(
        conn, "UPDATE actor_fact SET fact_type = fact_type WHERE actor_fact_id = %s::uuid", (fact[0],))
    ok["door_closed_without_deletion"] = refused(
        conn, "DELETE FROM actor WHERE actor_id = %s::uuid", (actor_id,),
        setting=("ghus.permanent_delete", str(uuid.uuid4())))

    # Inside one transaction that is rolled back: a synthetic account and deletions.
    try:
        with conn.transaction():
            user_id = str(uuid.uuid4())
            conn.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s)",
                         (user_id, f"rehearsal-{user_id[:8]}@example.test"))
            conn.execute("INSERT INTO compass.user_profile (user_id, email, full_name, role_code, status) "
                         "VALUES (%s, %s, 'Rehearsal (synthetic)', 'editor', 'active')",
                         (user_id, f"rehearsal-{user_id[:8]}@example.test"))
            before = conn.execute("SELECT count(*) FROM actor_read").fetchone()[0]
            pending = conn.execute(
                "INSERT INTO compass.deleted_record (entity_type, entity_id, name, snapshot, deleted_by, purge_after) "
                "VALUES ('actor', %s::uuid, %s, '{}'::jsonb, %s::uuid, now() + interval '30 days') "
                "RETURNING deletion_id::text", (actor_id, name, user_id)).fetchone()[0]
            ok["actor_read_hides_pending"] = conn.execute(
                "SELECT count(*) FROM actor_read").fetchone()[0] == before - 1
            ok["one_pending_deletion_per_record"] = refused(
                conn, "INSERT INTO compass.deleted_record (entity_type, entity_id, name, snapshot, deleted_by, "
                      "purge_after) VALUES ('actor', %s::uuid, 'x', '{}'::jsonb, %s::uuid, now() + interval '30 days')",
                (actor_id, user_id))
            ok["deadline_at_least_30_days"] = refused(
                conn, "INSERT INTO compass.deleted_record (entity_type, entity_id, name, snapshot, deleted_by, "
                      "purge_after) VALUES ('event', %s::uuid, 'x', '{}'::jsonb, %s::uuid, now() + interval '29 days')",
                (str(uuid.uuid4()), user_id))
            conn.execute("SELECT set_config('ghus.permanent_delete', %s, true)", (pending,))
            ok["door_closed_before_deadline"] = conn.execute("SELECT compass.purge_door_open()").fetchone()[0] is False
            ok["deletion_ledger_kept"] = refused(
                conn, "DELETE FROM compass.deleted_record WHERE deletion_id = %s::uuid", (pending,))
            ok["deletion_who_when_fixed"] = refused(
                conn, "UPDATE compass.deleted_record SET purge_after = now() + interval '90 days' "
                      "WHERE deletion_id = %s::uuid", (pending,))
            due = conn.execute(
                "INSERT INTO compass.deleted_record (entity_type, entity_id, name, snapshot, deleted_by, deleted_at, "
                "purge_after) VALUES ('event', %s::uuid, 'Due (synthetic)', '{}'::jsonb, %s::uuid, "
                "now() - interval '31 days', now() - interval '1 day') RETURNING deletion_id::text",
                (str(uuid.uuid4()), user_id)).fetchone()[0]
            conn.execute("SELECT set_config('ghus.permanent_delete', %s, true)", (due,))
            ok["door_opens_only_for_a_due_deletion"] = conn.execute(
                "SELECT compass.purge_door_open()").fetchone()[0] is True
            conn.execute("SELECT set_config('ghus.permanent_delete', '', true)")
            ok["restore_refused_after_deadline"] = refused(
                conn, "UPDATE compass.deleted_record SET restored_at = now(), restored_by = %s::uuid "
                      "WHERE deletion_id = %s::uuid", (user_id, due))
            raise Rollback
    except Rollback:
        pass
    ok["rehearsal_rows_rolled_back"] = conn.execute(
        "SELECT (SELECT count(*) FROM compass.deleted_record) + (SELECT count(*) FROM compass.user_profile)"
    ).fetchone()[0] == 0
    return ok


def purge_policy_covers_production(dsn: str) -> dict:
    """Every foreign key to an organization, person, event or hub is in the purge policy."""
    sys.path.insert(0, str(ROOT))
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from agents.enrichment.decisions import DELETABLE, _unplanned_links

    engine = create_engine(dsn.replace("postgresql://", "postgresql+psycopg://"))
    with Session(engine) as session:
        gaps = {kind: _unplanned_links(session, kind) for kind in DELETABLE}
    engine.dispose()
    return gaps


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", required=True, help="a local *_test database (a copy of production)")
    args = parser.parse_args(argv)
    if not args.database.endswith("_test"):
        parser.error("only a *_test database")
    dsn = f"postgresql://ghus_test@127.0.0.1:55432/{args.database}"
    report: dict = {"database": args.database,
                    "checksums": {k: sha256(v) for k, v in FILES.items()}, "checks": {}}
    checks = report["checks"]
    with psycopg.connect(dsn, autocommit=True) as conn:
        checks["copy_has_no_compass_schema"] = conn.execute(
            "SELECT to_regnamespace('compass') IS NULL").fetchone()[0]
        checks["copy_has_auth_users"] = conn.execute("SELECT to_regclass('auth.users') IS NOT NULL").fetchone()[0]
        report["ledger_before"] = [r[0] for r in conn.execute(
            "SELECT migration_id FROM architecture_v2_migration_ledger ORDER BY applied_at DESC LIMIT 5").fetchall()]
        f0 = fingerprint(conn)
        guards_before = {g: conn.execute("SELECT md5(prosrc) FROM pg_proc WHERE proname = %s", (g,)).fetchone()[0]
                         for g in GUARDS}
        p0 = fingerprint(conn, ("public",))
        run_file(conn, "700")
        f1 = fingerprint(conn)
        p1 = fingerprint(conn, ("public",))
        checks["700_leaves_public_untouched"] = p1 == p0
        run_file(conn, "710")
        f2 = fingerprint(conn)
        p2 = fingerprint(conn, ("public",))
        report["710_public_changes"] = sorted(k for k in p1 if p1[k] != p2[k])
        checks["710_changes_in_public_only_guards_and_actor_read"] = set(report["710_public_changes"]) <=             {"functions", "views"}
        changed = {k for k in f0 if f0[k] != f1[k]}
        report["700_changes"] = sorted(changed)
        report["710_changes"] = sorted(k for k in f1 if f1[k] != f2[k])
        checks.update(functional_checks(conn))
        report["purge_policy_gaps"] = purge_policy_covers_production(dsn)
        checks["purge_policy_covers_every_foreign_key"] = not any(report["purge_policy_gaps"].values())

        # The ledger rows the schema owner records, exactly as they will be written.
        for mid, key in (("700", "700"), ("710", "710")):
            conn.execute("INSERT INTO architecture_v2_migration_ledger (migration_id, source_path, source_sha256) "
                         "VALUES (%s, %s, %s) ON CONFLICT (migration_id) DO NOTHING",
                         (mid, str(FILES[key].relative_to(ROOT)).replace("\\", "/"), sha256(FILES[key])))
        checks["ledger_rows_recorded"] = conn.execute(
            "SELECT count(*) FROM architecture_v2_migration_ledger WHERE (migration_id, source_sha256) IN "
            "((%s, %s), (%s, %s))", ("700", sha256(FILES["700"]), "710", sha256(FILES["710"]))).fetchone()[0] == 2

        # Rollback refuses while a deletion exists.
        user_id = str(uuid.uuid4())
        conn.execute("INSERT INTO auth.users (id, email) VALUES (%s, 'rb@example.test')", (user_id,))
        conn.execute("INSERT INTO compass.user_profile (user_id, email, full_name, role_code, status) "
                     "VALUES (%s, 'rb@example.test', 'Rollback check', 'editor', 'active')", (user_id,))
        actor_id = conn.execute("SELECT actor_id::text FROM actor_read LIMIT 1").fetchone()[0]
        conn.execute("INSERT INTO compass.deleted_record (entity_type, entity_id, name, snapshot, deleted_by, "
                     "purge_after) VALUES ('actor', %s::uuid, 'x', '{}'::jsonb, %s::uuid, now() + interval '30 days')",
                     (actor_id, user_id))
        checks["rollback_710_refuses_with_deletions"] = script_refused(conn, "rollback_710")
        # Clean the synthetic rows (the guard keeps deletions: drop it for this cleanup only).
        conn.execute("ALTER TABLE compass.deleted_record DISABLE TRIGGER deleted_record_guard")
        conn.execute("DELETE FROM compass.deleted_record")
        conn.execute("ALTER TABLE compass.deleted_record ENABLE TRIGGER deleted_record_guard")
        conn.execute("DELETE FROM compass.user_profile WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM auth.users WHERE id = %s", (user_id,))

        run_file(conn, "rollback_710")
        checks["rollback_710_restores_exactly"] = fingerprint(conn) == f1
        checks["guards_restored_byte_for_byte"] = all(
            conn.execute("SELECT md5(prosrc) FROM pg_proc WHERE proname = %s", (g,)).fetchone()[0] == guards_before[g]
            for g in GUARDS)
        run_file(conn, "rollback_700")
        checks["rollback_700_restores_exactly"] = fingerprint(conn) == f0
        conn.execute("DELETE FROM architecture_v2_migration_ledger WHERE migration_id IN ('700', '710')")

        run_file(conn, "700")
        run_file(conn, "710")
        checks["reapply_identical"] = fingerprint(conn) == f2
    report["ok"] = all(checks.values())
    json.dump(report, sys.stdout, indent=2, sort_keys=True, default=str)
    sys.stdout.write("\n")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
