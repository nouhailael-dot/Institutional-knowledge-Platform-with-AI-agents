"""Generate migration 486 (Phase 12 topic policy) from the GHUS-approved topic CSV.

486 must not run before GHUS approves `docs/evidence/phase12_topic_proposal.csv`.
Rows still marked needs_ghus_review are excluded from the generated SQL, so a
hub or topic without a deterministic basis is never applied by default.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "docs/evidence/phase12_topic_proposal.csv"
SQL_PATH = ROOT / "migrations/proposed/deferred/486_v2_phase12_topic_policy.sql"
TEMPLATE = ROOT / "migrations/proposed/deferred/templates/486_v2_phase12_topic_policy.sql.tmpl"
RADIUS_MILES = 200


def _literal(value: str) -> str:
    return "NULL" if value == "" else "'" + value.replace("'", "''") + "'"


def render(csv_bytes: bytes) -> str:
    rows = list(csv.DictReader(csv_bytes.decode("utf-8").splitlines()))
    approved = [row for row in rows if row["needs_ghus_review"] != "True"]
    topics = [row for row in approved if row["record_type"] == "topic"]
    hubs = [row for row in approved if row["record_type"] == "hub" and row["center_city"]]
    topic_values = ",\n    ".join(
        f"({_literal(row['topic_code'])},{_literal(row['topic_name'])})" for row in topics
    )
    hub_values = ",\n    ".join(
        "(" + ",".join([
            _literal(row["hub_id"]) + "::uuid", _literal(row["topic_code"]),
            _literal(row["center_city"]), _literal(row["center_state_code"]),
            row["center_latitude"], row["center_longitude"],
        ]) + ")"
        for row in sorted(hubs, key=lambda item: item["hub_id"])
    )
    digest = hashlib.sha256(csv_bytes).hexdigest()
    return (TEMPLATE.read_text(encoding="utf-8")
            .replace("@@DIGEST@@", digest).replace("@@TOPIC_COUNT@@", str(len(topics)))
            .replace("@@HUB_COUNT@@", str(len(hubs))).replace("@@RADIUS@@", str(RADIUS_MILES))
            .replace("@@TOPIC_VALUES@@", topic_values).replace("@@HUB_VALUES@@", hub_values))


def main() -> int:
    SQL_PATH.write_text(render(CSV_PATH.read_bytes()), encoding="utf-8", newline="\n")
    print(f"wrote {SQL_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
