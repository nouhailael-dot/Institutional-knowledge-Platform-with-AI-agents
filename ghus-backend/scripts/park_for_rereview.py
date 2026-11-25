"""Park every verified organization, event and person for the team's re-review (25 Nov 2026).

    python -m scripts.park_for_rereview --by "Ismail Sabbar"                 # dry run
    python -m scripts.park_for_rereview --by "Ismail Sabbar" --live --backup FILE.csv
    python -m scripts.park_for_rereview --by "Ismail Sabbar" --restore FILE.csv [--live]

Dry run by default: it says how many would be parked and writes nothing. With
--live it first writes the backup (every record's id, name and previous status),
then parks them in one transaction through decisions.park_for_rereview, the
approved writer. --restore puts back the records of a backup that nobody has
verified or rejected since (decisions.restore_after_rereview).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REASON = "Re-review: every record is checked again by the team (GHUS, 25 Nov 2026)."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--by", required=True, help="who decided the re-review")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--backup", type=Path, help="CSV written before a live park")
    parser.add_argument("--restore", type=Path, help="CSV of an earlier park to undo")
    args = parser.parse_args(argv)
    if args.live and not args.restore and not args.backup:
        parser.error("--live needs --backup FILE.csv (the previous statuses are kept there first)")

    sys.path.insert(0, str(ROOT))
    from agents.collection.discovery_requests import open_session
    from agents.enrichment.decisions import park_for_rereview, restore_after_rereview

    session = open_session()
    try:
        if args.restore:
            with args.restore.open(encoding="utf-8", newline="") as handle:
                records = list(csv.DictReader(handle))
            result = restore_after_rereview(session, records=records, decided_by=args.by,
                                            live=args.live)
        else:
            result = park_for_rereview(session, decided_by=args.by, reason=REASON, live=args.live)
            if args.live:
                # The backup is written before the transaction commits: if it cannot
                # be written, nothing is parked.
                args.backup.parent.mkdir(parents=True, exist_ok=True)
                with args.backup.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=["entity_type", "entity_id", "name",
                                                                "previous_status"])
                    writer.writeheader()
                    writer.writerows(result["records"])
        if args.live:
            session.commit()
        else:
            session.rollback()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    summary = {k: v for k, v in result.items() if k != "records"}
    print(json.dumps(summary, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
