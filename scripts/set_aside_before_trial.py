"""Start the team trial with an empty Review queue, without deciding or deleting anything.

    python -m scripts.set_aside_before_trial --db PATH                    # preview
    python -m scripts.set_aside_before_trial --db PATH --live             # set aside
    python -m scripts.set_aside_before_trial --db PATH --restore --live   # list again

GHUS, 10 Nov 2026 (hosted 10-day trial): every item still pending in Review
when the trial starts is taken off the page, so each tester's Review shows only
what their own searches produce from then on. Optionally, ``--before`` takes
off only what was raised before a given time (ISO date or date-time, UTC);
the default is now.

Each item stays pending, with its history, in the Review store
(``ReviewStore.set_aside``); decided items are never touched. Because a later
sync never lists a set-aside item again, the queue stays clean across restarts.
Nothing canonical is written; the shared database is not read. Dry-run by
default. ``--restore --live`` lists every one of them again.

--db defaults to REVIEW_STORE_DB, or the store on the hosted disk when
GHUS_DATA_DIR is set.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.review.store import ReviewStore  # noqa: E402

REASON = "before_trial_2026-11"


def default_db(environ=os.environ) -> str | None:
    if environ.get("REVIEW_STORE_DB"):
        return environ["REVIEW_STORE_DB"]
    if environ.get("GHUS_DATA_DIR"):
        return str(Path(environ["GHUS_DATA_DIR"]) / "review-store" / "review-shared.sqlite3")
    return None


def cutoff(text: str | None) -> float:
    if not text:
        return datetime.now(UTC).timestamp()
    when = datetime.fromisoformat(text)
    return (when if when.tzinfo else when.replace(tzinfo=UTC)).timestamp()


def pending_before(store: ReviewStore, before: float) -> list[tuple[str, str]]:
    """(candidate_id, run kind) of every listed pending item raised before ``before``."""
    with store.connect() as db:
        rows = db.execute(
            "SELECT candidate_id, source_run_id FROM review_candidate "
            "WHERE status='pending_review' AND folded_into IS NULL AND created_at < ?",
            (before,)).fetchall()
    return [(row["candidate_id"], str(row["source_run_id"] or "").split(":")[0].split("-")[0] or "other")
            for row in rows]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=default_db())
    parser.add_argument("--before", help="only items raised before this ISO time (UTC); default now")
    parser.add_argument("--live", action="store_true", help="really change the store")
    parser.add_argument("--restore", action="store_true", help="list the set-aside items again")
    args = parser.parse_args(argv)
    if not args.db:
        parser.error("--db is required (no REVIEW_STORE_DB or GHUS_DATA_DIR in the environment)")
    path = Path(args.db)
    if not path.is_file():
        print(f"no Review store at {path}")
        return 1
    store = ReviewStore(path)
    if args.restore:
        print(f"listed again: {store.restore_set_aside(REASON) if args.live else 'dry run (add --live)'}")
        return 0
    chosen = pending_before(store, cutoff(args.before))
    print(f"store: {path}")
    print(f"pending and listed now: {len(chosen)} by run kind {dict(Counter(k for _, k in chosen))}")
    if not args.live:
        print("dry run: nothing changed (add --live)")
        return 0
    print(f"set aside: {store.set_aside([cid for cid, _ in chosen], reason=REASON)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
