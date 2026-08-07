"""Driver — run the metered pilot. Reads gaps, calls the agent, writes proposals.

DRY RUN: proposals are appended to a local JSONL file. NOTHING is written to
Postgres. Each line is one proposal, shaped to match the `proposal` table so the
later (gated) DB sink is a trivial swap:
    entity_id, table_name, field, old_value, new_value,
    evidence_url, evidence_snippet, proposed_by, status, plus confidence + meta.

Usage:
    python -m src.enrich.run --field website --limit 5          # 5-actor probe
    python -m src.enrich.run --field country --limit 25
    python -m src.enrich.run --field website --tier ai_inferred # full tier

Start SMALL (--limit 3) to eyeball evidence quality before spending on the set.
"""

import argparse
import datetime as dt
import json
import sys

from src.enrich.agent import MODEL, enrich
from src.enrich.gaps import FIELDS, find_gaps

PROPOSED_BY = f"enrich-agent/{MODEL}"
DEFAULT_OUT = "proposals.jsonl"


def _row(actor: dict, field: str, p: dict) -> dict:
    """Shape one agent result into a proposal-table-shaped record."""
    return {
        "entity_id": str(actor["actor_id"]),
        "table_name": "actor",
        "field": field,
        "old_value": p.get("old_value"),
        "new_value": p.get("new_value") or None,
        "evidence_url": p.get("evidence_url") or None,
        "evidence_snippet": p.get("evidence_snippet") or None,
        "proposed_by": PROPOSED_BY,
        "status": "pending",
        # extra metadata (not columns on `proposal`, kept for the dry-run review)
        "_actor_name": actor.get("name"),
        "_found": bool(p.get("found")),
        "_confidence": p.get("confidence"),
        "_error": p.get("error"),
        "_created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Task 1A enrichment pilot (dry run).")
    ap.add_argument("--field", required=True, choices=sorted(FIELDS),
                    help="factual field to enrich")
    ap.add_argument("--limit", type=int, default=5,
                    help="max actors this run (default 5 — keep the pilot small)")
    ap.add_argument("--tier", default=None,
                    help="restrict to one verification tier (e.g. ai_inferred)")
    ap.add_argument("--out", default=DEFAULT_OUT, help="JSONL output path")
    args = ap.parse_args(argv)

    tiers = (args.tier,) if args.tier else ("ai_inferred", "phase_1", "needs_review")
    work = find_gaps(args.field, limit=args.limit, tiers=tiers)
    if not work:
        print("No actors match — nothing missing that field in the chosen tier(s).")
        return

    print(f"Pilot: {args.field} · {len(work)} actor(s) · model={MODEL} · "
          f"DRY RUN -> {args.out}\n")
    found = 0
    with open(args.out, "a", encoding="utf-8") as fh:
        for i, actor in enumerate(work, 1):
            name = actor.get("name")
            print(f"[{i}/{len(work)}] {name} … ", end="", flush=True)
            try:
                p = enrich(actor, args.field)
            except Exception as e:                       # hard API/transport error
                print(f"ERROR: {e}")
                p = {"found": False, "new_value": "", "evidence_url": "",
                     "evidence_snippet": "", "confidence": 0.0,
                     "old_value": actor.get(args.field), "error": str(e)}
            row = _row(actor, args.field, p)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            if row["_found"]:
                found += 1
                print(f"-> {row['new_value']}  (conf {row['_confidence']})")
            else:
                print("no confident value" + (f" [{p['error']}]" if p.get("error") else ""))

    print(f"\nDone. {found}/{len(work)} proposals with a cited value. "
          f"Review: {args.out}  (nothing written to Postgres)")


if __name__ == "__main__":
    sys.exit(main())
