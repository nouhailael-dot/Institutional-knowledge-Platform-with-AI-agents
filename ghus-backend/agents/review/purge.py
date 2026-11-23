"""The scheduled cleanup: permanently remove records deleted more than 30 days ago.

    python -m agents.review.purge            dry run: lists what is due and what would go
    python -m agents.review.purge --live     purges, one deletion per transaction

GHUS policy (17 Nov 2026; migration 710). Safe to run again at any time:
each deletion is purged in its own transaction through decisions.purge_record,
which skips what is already purged, restored or not yet due, and stops (blocked)
on a link the policy does not cover. One run at a time (an advisory lock). Live
needs REVIEW_ADMISSION_WRITES_ENABLED=true and --live (dry run otherwise).
Prints one JSON report.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from sqlalchemy import text

LOCK_KEY = 710_030   # one cleanup at a time across processes


def due_deletions(session, limit: int) -> list[str]:
    return [r[0] for r in session.execute(text(
        "SELECT deletion_id::text FROM compass.deleted_record WHERE restored_at IS NULL AND purged_at IS NULL "
        "AND purge_after <= now() ORDER BY purge_after LIMIT :limit"), {"limit": limit}).all()]


def run(session_factory, *, live: bool, limit: int = 100) -> dict:
    """Purge (or, dry, describe) every due deletion. ``session_factory`` opens a session."""
    from agents.enrichment.decisions import DeletionError, purge_record

    with session_factory() as lock_session:
        got = lock_session.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar()
        if not got:
            return {"live": live, "skipped": "another cleanup is running", "results": []}
        try:
            due = due_deletions(lock_session, limit)
            results = []
            for deletion_id in due:
                with session_factory() as session:
                    transaction = session.begin()
                    try:
                        outcome = purge_record(session, deletion_id=deletion_id, live=live)
                        if live and outcome["outcome"] == "purged":
                            transaction.commit()
                        else:
                            transaction.rollback()
                    except (DeletionError, Exception) as exc:  # noqa: BLE001 - one failure never stops the rest
                        transaction.rollback()
                        outcome = {"deletion_id": deletion_id, "outcome": "error",
                                   "reason": f"{type(exc).__name__}: {exc}"}
                    results.append(outcome)
        finally:
            lock_session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            lock_session.commit()          # its own (read-only) transaction ends cleanly
    counts: dict[str, int] = {}
    for r in results:
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    return {"live": live, "due": len(results), "outcomes": counts, "results": results}


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Permanently remove records deleted more than 30 days ago")
    parser.add_argument("--live", action="store_true", help="purge (default: dry run)")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)
    if args.live and os.getenv("REVIEW_ADMISSION_WRITES_ENABLED", "").lower() not in {"1", "true", "yes"}:
        parser.error("REVIEW_ADMISSION_WRITES_ENABLED=true is required for --live (fail-closed)")
    from src.db.session import SessionLocal

    report = run(SessionLocal, live=args.live, limit=max(1, min(args.limit, 1000)))
    json.dump(report, sys.stdout, sort_keys=True, default=str)
    sys.stdout.write("\n")
    return 1 if report.get("outcomes", {}).get("error") else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
