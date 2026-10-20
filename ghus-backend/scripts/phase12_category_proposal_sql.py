"""Generate migration 484 from the reviewed Phase 12 category proposal CSV.

The SQL is a pure function of `docs/evidence/phase12_category_proposals.csv`;
its header records the CSV SHA-256 so the applied migration can be traced to
the exact proposal file GHUS reviewed.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "docs/evidence/phase12_category_proposals.csv"
SQL_PATH = ROOT / "migrations/proposed/deferred/484_v2_phase12_category_proposals.sql"
TEMPLATE = ROOT / "migrations/proposed/deferred/templates/484_v2_phase12_category_proposals.sql.tmpl"
BATCH = "phase12_existing_canonical_2026_10"


def _literal(value: str | None) -> str:
    if value is None or value == "":
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def render(csv_bytes: bytes) -> str:
    rows = list(csv.DictReader(csv_bytes.decode("utf-8").splitlines()))
    values = ",\n    ".join(
        "(" + ",".join([
            _literal(row["actor_id"]) + "::uuid",
            _literal(row["proposed_category"]),
            _literal(row["proposed_category_type"]),
            _literal(row["confidence"]),
            _literal(row["evidence"]),
            _literal(row["category_note"]),
            "true" if row["is_true_aggregate"] == "True" else "false",
        ]) + ")"
        for row in sorted(rows, key=lambda item: item["actor_id"])
    )
    digest = hashlib.sha256(csv_bytes).hexdigest()
    return (TEMPLATE.read_text(encoding="utf-8")
            .replace("@@DIGEST@@", digest).replace("@@COUNT@@", str(len(rows)))
            .replace("@@VALUES@@", values).replace("@@BATCH@@", BATCH))


def main() -> int:
    SQL_PATH.write_text(render(CSV_PATH.read_bytes()), encoding="utf-8", newline="\n")
    print(f"wrote {SQL_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
