"""Generate migration 491 (GHUS decisions of 2026-10-06) from the category proposals.

GHUS decided: confirm every proposed category; reject every collection of
organizations (archive their hub memberships); retire the empty "Mining Hubs".
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "docs/evidence/phase12_category_proposals.csv"
SQL_PATH = ROOT / "migrations/proposed/deferred/491_v2_phase12_ghus_decisions.sql"
TEMPLATE = ROOT / "migrations/proposed/deferred/templates/491_v2_phase12_ghus_decisions.sql.tmpl"
DECIDER = "GHUS (approved by Ismail Sabbar, 2026-10-06)"


def render(csv_bytes: bytes) -> str:
    rows = sorted(csv.DictReader(csv_bytes.decode("utf-8").splitlines()),
                  key=lambda row: row["actor_id"])
    values = ",\n    ".join(
        "('{}'::uuid,{},{})".format(
            row["actor_id"],
            f"'{row['proposed_category']}'" if row["proposed_category"] else "NULL",
            "true" if row["is_true_aggregate"] == "True" else "false",
        )
        for row in rows
    )
    aggregates = sum(row["is_true_aggregate"] == "True" for row in rows)
    return (TEMPLATE.read_text(encoding="utf-8")
            .replace("@@DIGEST@@", hashlib.sha256(csv_bytes).hexdigest())
            .replace("@@DECIDER@@", DECIDER)
            .replace("@@CONFIRM_COUNT@@", str(len(rows) - aggregates))
            .replace("@@AGGREGATE_COUNT@@", str(aggregates))
            .replace("@@VALUES@@", values))


def main() -> int:
    SQL_PATH.write_text(render(CSV_PATH.read_bytes()), encoding="utf-8", newline="\n")
    print(f"wrote {SQL_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
