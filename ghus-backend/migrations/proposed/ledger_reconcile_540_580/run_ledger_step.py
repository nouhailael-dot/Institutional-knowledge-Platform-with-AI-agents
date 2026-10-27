"""Run one step of the 540-580 ledger reconciliation with psql.

Steps:
    preflight   read-only GO/NO-GO checks
    export      read-only CSV export of the whole ledger (backup)
    reconcile   insert the five ledger rows
    verify      read-only post-checks
    rollback    remove exactly the five rows (needs --reconciled-at)
    restore     LAST RESORT: make the ledger equal an export CSV (needs --backup,
                --execute; it has no dry run because it loads a temp table)
    fingerprint read-only schema fingerprint to JSON; --compare another JSON

Dry run by default. Every session is opened with
default_transaction_read_only=on, so reconcile and rollback evaluate all their
preconditions and are then refused by the database before writing anything.
Only --execute opens a writable session; against Supabase it also needs
--confirm reconcile-ledger-540-580.

Before connecting it checks that each migration file is committed and that the
committed bytes, the working file and the scripts' checksums all agree.

Targets: --target supabase (DATABASE_URL in the backend .env; never printed)
or --target local:<ghus_v2_*_test database> on 127.0.0.1:55432.
Every run is logged under runs/.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PSQL = Path(os.environ.get("PG_BIN", r"C:\Program Files\PostgreSQL\17\bin")) / "psql.exe"
CONFIRM = "reconcile-ledger-540-580"
MIGRATIONS = {
    "540": ("agents/sql/540_v2_actor_update_subscription.sql",
            "8a6f1dbec788694c2eca45b9e5f10b363da6a74197e40a60eaf8ac48805d6907"),
    "550": ("agents/sql/550_v2_discovery_requests.sql",
            "56dc21550fd74771915b84794a29068081f5eff367810409ad2cf95885d0e46d"),
    "560": ("agents/sql/560_v2_agent_auto_verification.sql",
            "d52c855edf804b319cf77ca4f5919d76462d0436e4a884455467e8bd0e566c4a"),
    "570": ("agents/sql/570_v2_actor_update_requests.sql",
            "ee0f192baf82ca0649fe2edc4516f41a518f4deaa6a8696b3505250ffeb01190"),
    "580": ("agents/sql/580_v2_event_people_requests.sql",
            "63d7419e7b9511e12e7e339745bff3903c72f3ff13b55bd078aadb3f467b5f11"),
}
SCRIPTS = {
    "preflight": "preflight_540_580.sql",
    "export": "export_ledger.sql",
    "reconcile": "reconcile_ledger_540_580.sql",
    "verify": "verify_540_580.sql",
    "rollback": "rollback_reconcile_ledger_540_580.sql",
    "restore": "restore_ledger_from_backup.sql",
}
WRITES = {"reconcile", "rollback", "restore"}


def check_files(allow_uncommitted: bool) -> list[str]:
    """Committed bytes == working bytes == checksum in every script."""
    problems = []
    scripts = {name: (HERE / f).read_text(encoding="utf-8") for name, f in SCRIPTS.items()}
    for mid, (rel, want) in MIGRATIONS.items():
        work = hashlib.sha256((REPO / rel).read_bytes()).hexdigest()
        head = subprocess.run(["git", "-C", str(REPO), "show", f"HEAD:{rel}"], capture_output=True)
        committed = hashlib.sha256(head.stdout).hexdigest() if head.returncode == 0 else None
        if committed is None and not allow_uncommitted:
            problems.append(f"{mid}: {rel} is not committed")
        if committed is not None and committed != want:
            problems.append(f"{mid}: committed checksum {committed} != {want}")
        if work != want:
            problems.append(f"{mid}: working file checksum {work} != {want} (line endings?)")
        for name in ("reconcile", "rollback", "verify", "preflight"):
            if want not in scripts[name]:
                problems.append(f"{mid}: checksum missing from {SCRIPTS[name]}")
        print(f"  {mid} {rel} committed={'yes' if committed else 'NO'} sha256={work[:16]}..."
              f" {'ok' if work == want and committed in (want, None) else 'MISMATCH'}")
    return problems


def connection_env(target: str, read_only: bool) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env.update(PGCLIENTENCODING="UTF8", PGCONNECT_TIMEOUT="30", LC_MESSAGES="C")
    if target.startswith("local:"):
        db = target.split(":", 1)[1]
        if not (db.startswith("ghus_v2_") and db.endswith("_test")):
            sys.exit("local targets are ghus_v2_*_test databases only")
        env.update(PGHOST="127.0.0.1", PGPORT="55432", PGUSER="ghus_test", PGDATABASE=db)
    elif target == "supabase":
        from dotenv import dotenv_values
        from urllib.parse import unquote, urlsplit
        sys.path.insert(0, str(REPO))
        from src.db.session import _public_ipv4_addresses
        url = urlsplit(re.sub(r"^postgresql\+\w+://", "postgresql://",
                              dotenv_values(REPO / ".env")["DATABASE_URL"]))
        port = url.port or 5432
        env.update(PGHOST=url.hostname, PGHOSTADDR=_public_ipv4_addresses(url.hostname, port)[0],
                   PGPORT=str(port), PGUSER=unquote(url.username or ""),
                   PGPASSWORD=unquote(url.password or ""), PGDATABASE=url.path.lstrip("/") or "postgres",
                   PGSSLMODE="require")
    else:
        sys.exit("--target is supabase or local:<db>")
    if read_only:
        env["PGOPTIONS"] = "-c default_transaction_read_only=on"
    return env


def fingerprint(env: dict) -> dict:
    import psycopg
    sys.path.insert(0, str(HERE / "evidence"))
    import catalog_fingerprint as cf
    params = dict(host=env["PGHOST"], port=env["PGPORT"], user=env["PGUSER"], dbname=env["PGDATABASE"],
                  options="-c default_transaction_read_only=on", connect_timeout=30)
    if "PGHOSTADDR" in env:
        params.update(hostaddr=env["PGHOSTADDR"], password=env["PGPASSWORD"], sslmode="require")
    with psycopg.connect(**params) as c:
        return {k: sorted(v) for k, v in cf.snapshot(lambda q: c.execute(q).fetchall()).items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=[*SCRIPTS, "fingerprint"])
    ap.add_argument("--target", default="supabase")
    ap.add_argument("--execute", action="store_true", help="open a writable session")
    ap.add_argument("--confirm", default="")
    ap.add_argument("--reconciled-at", default="")
    ap.add_argument("--backup", default="", help="restore: the ledger_backup_*.csv to restore")
    ap.add_argument("--out", default="")
    ap.add_argument("--compare", default="")
    ap.add_argument("--allow-uncommitted", action="store_true",
                    help="local rehearsal only: accept a migration file not yet committed")
    a = ap.parse_args()

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    runs = HERE / "runs"
    runs.mkdir(exist_ok=True)
    print(f"step={a.step} target={a.target} mode={'EXECUTE' if a.execute else 'dry-run/read-only'}")

    if a.target == "supabase" and a.allow_uncommitted:
        sys.exit("--allow-uncommitted is for local rehearsals only")
    problems = check_files(a.allow_uncommitted)
    if problems:
        print("NO-GO: migration files and checksums disagree:\n  " + "\n  ".join(problems))
        return 2
    if a.execute and a.step not in WRITES:
        sys.exit(f"{a.step} never writes; drop --execute")
    if a.execute and a.target == "supabase" and a.confirm != CONFIRM:
        sys.exit(f"writing to Supabase needs --confirm {CONFIRM}")

    env = connection_env(a.target, read_only=not a.execute)

    if a.step == "fingerprint":
        fp = fingerprint(env)
        out = Path(a.out or runs / f"{stamp}_fingerprint_{a.target.replace(':', '_')}.json")
        out.write_text(json.dumps(fp, indent=1), encoding="utf-8")
        print("fingerprint", {k: len(v) for k, v in fp.items()}, "->", out)
        if a.compare:
            sys.path.insert(0, str(HERE / "evidence"))
            import catalog_fingerprint as cf
            d = cf.diff(json.loads(Path(a.compare).read_text(encoding="utf-8")), fp)
            print("schema differences:", json.dumps(d, indent=1) if d else "none")
            return 1 if d else 0
        return 0

    cmd = [str(PSQL), "-X", "-v", "ON_ERROR_STOP=1", "-f", str(HERE / SCRIPTS[a.step])]
    if a.step == "export":
        cmd[1:1] = ["-v", f"backup_file=ledger_backup_{stamp}.csv"]
    stdin = None
    if a.step == "restore":
        if not (a.execute and a.backup):
            sys.exit("restore needs --backup <ledger_backup_*.csv> and --execute (no dry run)")
        cmd[1:1] = ["-v", f"backup_file={Path(a.backup).name}"]
        stdin = open(a.backup, "rb")
    if a.step == "rollback":
        if not a.reconciled_at:
            sys.exit("rollback needs --reconciled-at <applied_at printed by the reconciliation>")
        cmd[1:1] = ["-v", f"reconciled_at={a.reconciled_at}"]
    log = runs / f"{stamp}_{a.step}_{a.target.replace(':', '_')}{'' if a.execute else '_dryrun'}.log"
    r = subprocess.run(cmd, env=env, cwd=runs, stdin=stdin, capture_output=True)
    output = (r.stdout + r.stderr).decode("utf-8", errors="replace")
    log.write_text(output, encoding="utf-8")
    print(output)
    print(f"psql exit {r.returncode}; log {log}")

    if a.step in WRITES and not a.execute:
        if r.returncode == 0:
            print("DRY RUN OK: nothing to change; nothing changed.")
            return 0
        refused = "read-only transaction" in output
        failed_precondition = "precondition failed" in output or "refused" in output
        if refused and not failed_precondition:
            print("DRY RUN OK: every precondition passed; the write was refused by the "
                  "read-only session; nothing changed.")
            return 0
        print("DRY RUN: the step would not succeed (see output); nothing changed.")
        return 1
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
