"""Remove from the Ecosystem Directory the Phase 1 rows that are not organizations.

    python -m scripts.remove_phase1_non_organizations --workbook PATH [--live]

The rows are exactly those on the "Not organizations" sheet of the clean Phase 1
workbook (``scripts.export_phase1_dataset``): aggregate categories, groups and
synthetic placeholders that describe themselves as such. Each goes through the
Directory's own Delete path, ``agents.review.admission.apply_directory_decision``:
a GHUS decision is recorded with the reason, the record is hidden from the
Directory, nothing is erased, and it can be restored. Dry-run by default.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "ghus-backend"
SHEET = "Not organizations"
REASON = "Phase 1 cleanup (4 Nov 2026): not an organization - {why}"


def rows_to_remove(workbook: Path) -> list[dict]:
    ws = load_workbook(workbook, read_only=True)[SHEET]
    rows = list(ws.iter_rows(values_only=True))
    header = list(rows[0])
    at = {name: header.index(name) for name in ("Name", "Why it is not an organization", "COMPASS ID")}
    return [{"name": r[at["Name"]], "why": r[at["Why it is not an organization"]],
             "actor_id": r[at["COMPASS ID"]]} for r in rows[1:] if r and r[at["COMPASS ID"]]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--live", action="store_true", help="record the removals; absent lists them")
    args = parser.parse_args(argv)
    rows = rows_to_remove(args.workbook)
    if not args.live:
        for row in rows:
            print(f"would remove: {row['name']} - {row['why']}")
        print(f"{len(rows)} would be removed (dry run; nothing written)")
        return 0
    # The platform's identity first, then the backend, which has its own "src" package.
    from src.identity import current_user

    who = current_user()
    for name in [m for m in sys.modules if m == "src" or m.startswith("src.")]:
        del sys.modules[name]
    sys.path.insert(0, str(BACKEND))
    from agents.collection.discovery_requests import open_session
    from agents.review.admission import apply_directory_decision

    counts: dict[str, int] = {}
    with open_session() as session:
        for row in rows:
            outcome = apply_directory_decision(session, {
                "decision_kind": "remove_from_directory", "entity_type": "actor",
                "entity_id": row["actor_id"], "reviewer": who,
                "reason": REASON.format(why=row["why"])})
            counts[outcome["status"]] = counts.get(outcome["status"], 0) + 1
    print({"removed_or_unchanged": counts, "rows": len(rows)})
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    raise SystemExit(main())
