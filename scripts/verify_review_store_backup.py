"""Verify that a Review-store backup could actually be restored from.

A backup nobody has opened is a guess. This opens one, checks it is an intact
SQLite database with the Review schema, and reports what it would restore: how
many decisions, how many decided candidates, and how recent the newest decision
is.

It never writes to the backup and never touches the live store.

    python -m scripts.verify_review_store_backup /backups/review-20261009.sqlite3

Add --compare-live to measure the backup against the configured REVIEW_STORE_DB
and show how many decisions would be lost by restoring it. Exit status is 0 when
the backup is usable, 1 when it is not.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_TABLES = {"review_candidate", "review_decision"}
DECIDED = ("approved", "rejected_by_reviewer")


def _open_read_only(path: Path) -> sqlite3.Connection:
    """Open without creating, and without being able to modify, the file."""

    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def _summarise(path: Path) -> dict[str, object]:
    with _open_read_only(path) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {
            row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        missing = sorted(REQUIRED_TABLES - tables)
        if missing:
            return {"integrity": integrity, "missing_tables": missing}

        decisions = db.execute("SELECT count(*) FROM review_decision").fetchone()[0]
        newest = db.execute("SELECT max(decided_at) FROM review_decision").fetchone()[0]
        decided = db.execute(
            "SELECT count(*) FROM review_candidate WHERE status IN (?,?)", DECIDED
        ).fetchone()[0]
        pending = db.execute(
            "SELECT count(*) FROM review_candidate WHERE status='pending_review'"
        ).fetchone()[0]
        return {
            "integrity": integrity,
            "missing_tables": [],
            "decisions": decisions,
            "newest_decision": newest,
            "decided_candidates": decided,
            "pending_candidates": pending,
        }


def _age(newest: float | None) -> str:
    if not newest:
        return "no decisions recorded"
    when = datetime.fromtimestamp(float(newest), tz=timezone.utc)
    hours = (datetime.now(tz=timezone.utc) - when).total_seconds() / 3600
    return f"{when:%Y-%m-%d %H:%M UTC} ({hours:.1f} hours old)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path, help="the backup file to verify")
    parser.add_argument(
        "--compare-live", action="store_true",
        help="also read REVIEW_STORE_DB and report what restoring would lose",
    )
    args = parser.parse_args(argv)

    if not args.backup.is_file():
        print(f"FAIL: no such backup: {args.backup}")
        return 1

    try:
        summary = _summarise(args.backup)
    except sqlite3.DatabaseError as exc:
        print(f"FAIL: {args.backup} is not a readable SQLite database: {exc}")
        return 1

    print(f"backup            : {args.backup}")
    print(f"size              : {args.backup.stat().st_size:,} bytes")
    print(f"integrity_check   : {summary['integrity']}")

    if summary["missing_tables"]:
        print(f"FAIL: not a Review store - missing {', '.join(summary['missing_tables'])}")
        return 1
    if summary["integrity"] != "ok":
        print("FAIL: integrity check did not return ok; this backup is corrupt")
        return 1

    print(f"decisions         : {summary['decisions']}")
    print(f"newest decision   : {_age(summary['newest_decision'])}")
    print(f"decided candidates: {summary['decided_candidates']}")
    print(f"pending candidates: {summary['pending_candidates']}")

    if args.compare_live:
        live_path = os.environ.get("REVIEW_STORE_DB", "").strip()
        if not live_path:
            print("\nREVIEW_STORE_DB is not set, so there is nothing to compare against.")
        elif not Path(live_path).is_file():
            print(f"\nREVIEW_STORE_DB points at {live_path}, which does not exist.")
        else:
            live = _summarise(Path(live_path))
            lost = int(live.get("decisions") or 0) - int(summary["decisions"])
            print(f"\nlive store        : {live_path}")
            print(f"live decisions    : {live.get('decisions')}")
            if lost > 0:
                print(
                    f"RESTORING THIS BACKUP WOULD LOSE {lost} DECISION(S). "
                    "Take a fresh backup before restoring."
                )
            elif lost < 0:
                print(f"the backup holds {-lost} decision(s) the live store does not")
            else:
                print("the backup and the live store hold the same number of decisions")

    if not summary["decisions"]:
        print("\nWARNING: this backup records no decisions at all. If the store has "
              "been in use, this is the wrong file.")
    print("\nOK: this backup is intact and restorable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
