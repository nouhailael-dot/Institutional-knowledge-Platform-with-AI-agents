"""List the Phase 12 true aggregates for a GHUS disposition decision.

Read-only. Writes `docs/evidence/phase12_aggregate_disposition_proposal.csv`.
It proposes options; it never decides one. Migration 495 (category NOT NULL)
cannot validate until GHUS records a disposition for every row.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path
from urllib.parse import urlsplit

import psycopg2
from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/evidence/phase12_aggregate_disposition_proposal.csv"
EXPECTED_DATABASE = "ghus_v2_phase12_full_test"
OPTIONS = "convert_to_network_parent | keep_as_legacy_collection_excluded_from_actor_views"


def _url() -> str:
    raw = os.environ.get("V2_PHASE12_FULL_DATABASE_URL", "").strip()
    parsed = urlsplit(raw)
    if (parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port != 55432
            or parsed.path.removeprefix("/") != EXPECTED_DATABASE):
        raise RuntimeError("aggregate dispositions accept only the local full-dump copy")
    return raw


def main() -> int:
    connection = psycopg2.connect(_url(), application_name="ghus_phase12_aggregates")
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT a.actor_id::text, a.name, audit.legacy_category legacy_value,
                       a.website, r.payload->>'aggregate_evidence' evidence,
                       count(h.hub_id) hub_memberships,
                       string_agg(DISTINCT hub.name, '; ') hubs
                FROM review_item r
                JOIN actor a ON a.actor_id = r.entity_id
                JOIN actor_category_migration_audit audit ON audit.actor_id = a.actor_id
                LEFT JOIN hub_actor h ON h.actor_id = a.actor_id
                LEFT JOIN hub ON hub.hub_id = h.hub_id
                WHERE r.review_kind = 'category_doubt'
                  AND (r.payload->>'is_true_aggregate')::boolean
                GROUP BY 1,2,3,4,5 ORDER BY a.name
            """)
            rows = cursor.fetchall()
        connection.rollback()
    finally:
        connection.close()
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "actor_id", "name", "legacy_value", "website", "hub_memberships", "hubs",
            "evidence", "disposition_options", "ghus_decision",
        ])
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "disposition_options": OPTIONS, "ghus_decision": ""})
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({len(rows)} aggregates)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
