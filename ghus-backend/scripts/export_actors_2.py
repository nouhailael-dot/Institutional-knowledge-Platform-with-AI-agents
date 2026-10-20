"""
export_actors.py — export canonical actors for the ER pipeline.

CRITICAL: excludes merged-away actors (merged_into_actor_id IS NOT NULL).
After the backfill, the old export is stale: it still contains rows that have
been merged into a canonical actor. Feeding those back into candidate generation
would resurrect duplicates that were just resolved.

Columns: actor_id, name, description, location, hubs

Run (repo root, venv active, DATABASE_URL set):
    python scripts/export_actors.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.db.session import SessionLocal

SQL = """
SELECT
    a.actor_id::text AS actor_id,
    a.name           AS name,
    COALESCE(a.description, '') AS description,
    TRIM(BOTH ', ' FROM CONCAT_WS(', ', a.location_city, a.state, a.country)) AS location,
    COALESCE(STRING_AGG(DISTINCT h.name, '; '), '') AS hubs
FROM actor a
LEFT JOIN hub_actor ha ON ha.actor_id = a.actor_id
LEFT JOIN hub h        ON h.hub_id = ha.hub_id
WHERE a.merged_into_actor_id IS NULL        -- canonical actors only
GROUP BY a.actor_id, a.name, a.description, a.location_city, a.state, a.country
ORDER BY a.name;
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data/exports/actors.csv")
    args = ap.parse_args()

    s = SessionLocal()
    try:
        df = pd.read_sql(text(SQL), s.connection())
    finally:
        s.close()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)

    print(f"[export] {len(df)} canonical actors -> {out}")
    for col in ("description", "location", "hubs"):
        share = float((df[col].astype(str).str.strip() != "").mean())
        print(f"[export] {col:<12} non-empty: {share:5.0%}")
    dup = int(df["name"].str.lower().str.strip().duplicated().sum())
    print(f"[export] exact-duplicate names remaining: {dup}")


if __name__ == "__main__":
    main()