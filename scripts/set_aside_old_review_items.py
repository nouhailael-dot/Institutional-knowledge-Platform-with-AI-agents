"""Take the old items off the Review page, without deciding or deleting them.

    python -m scripts.set_aside_old_review_items [--db PATH]           # preview
    python -m scripts.set_aside_old_review_items [--db PATH] --live    # set aside
    python -m scripts.set_aside_old_review_items [--db PATH] --restore # list again

GHUS, 2026-10-29: Review keeps only the recent work. The old items are:

  migration    checks raised on the Phase 1 data by the Architecture V2
               migration (before 2026-10-10): locations not placed, links with
               no source page, and a few others
  early_update value conflicts and protected changes from the first actor
               updates (before 2026-10-23)
  test_run     results of dry-run discovery runs
  test_import  Data Feed imports made to test the page ("Admission E2E",
               "browser test")

Each stays pending, with its history, in the review store; only the queue stops
listing it (``ReviewStore.set_aside``). Nothing canonical is written. Dry-run
by default.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.review.store import ReviewStore  # noqa: E402

REASON = "old_items_2026-10-29"
MIGRATION_BEFORE = datetime(2026, 10, 10, tzinfo=UTC).timestamp()
EARLY_UPDATE_BEFORE = datetime(2026, 10, 23, tzinfo=UTC).timestamp()
TEST_IMPORTS = ("Admission E2E", "browser test")


def group_of(row) -> str | None:
    """Which old group a pending row belongs to, or None to keep it listed."""
    run = str(row["source_run_id"] or "")
    description = str(row["source_description"] or "")
    meta = json.loads(row["agent_metadata"] or "{}")
    created = float(row["created_at"] or 0)
    if run.startswith("datafeed:") and any(word in description for word in TEST_IMPORTS):
        return "test_import"
    if "dry_run" in description:
        return "test_run"
    if run.startswith("v2-review"):
        if created < MIGRATION_BEFORE:
            return "migration"
        if meta.get("review_kind") in ("fact_conflict", "pending_update") \
                and created < EARLY_UPDATE_BEFORE:
            return "early_update"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=os.environ.get("REVIEW_STORE_DB")
                        or str(ROOT / ".demo" / "review-demo.sqlite3"))
    parser.add_argument("--live", action="store_true", help="set the old items aside")
    parser.add_argument("--restore", action="store_true", help="list them again")
    args = parser.parse_args(argv)
    store = ReviewStore(Path(args.db))
    if args.restore:
        print(f"listed again: {store.restore_set_aside(REASON) if args.live else 'dry run'}")
        return 0
    with store.connect() as db:
        rows = db.execute(
            "SELECT candidate_id, source_run_id, source_description, agent_metadata, created_at "
            "FROM review_candidate WHERE status='pending_review' AND folded_into IS NULL"
        ).fetchall()
    chosen = {row["candidate_id"]: group for row in rows if (group := group_of(row))}
    counts = Counter(chosen.values())
    print(f"listed now: {len(rows)}; old: {len(chosen)} {dict(counts)}; "
          f"stays listed: {len(rows) - len(chosen)}")
    if not args.live:
        print("dry run: nothing changed (add --live)")
        return 0
    print(f"set aside: {store.set_aside(list(chosen), reason=REASON)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
