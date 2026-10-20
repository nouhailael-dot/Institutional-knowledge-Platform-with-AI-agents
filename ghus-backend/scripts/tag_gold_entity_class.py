"""
tag_gold_entity_class.py — add an entity_class column to the gold set.

WHY
~23% of the actor table (199 of 872) is not organisations but aggregate category
labels: "Water-Tech Startups (Arizona)", "Carbon Capture Research Labs". Whether
two such labels are "the same" is a judgement call even for a human, and those
pairs are where the model's remaining errors cluster.

The labels are still valuable training data -- they teach the model what
similar-but-different looks like -- so nothing is deleted. This adds a column so
precision can be reported for organisations and aggregates SEPARATELY, and so
the sweep can exclude aggregates from auto-merge at runtime.

entity_class values:
    organization  both sides are real named organisations
    aggregate     at least one side is a category label

Classification uses the actor table's actor_type when available (authoritative),
falling back to description markers left by enrichment, then to a name pattern.

DRY RUN BY DEFAULT — prints the split without writing.

    python scripts/tag_gold_entity_class.py --gold data/processed/entity_resolution_gold.csv
    python scripts/tag_gold_entity_class.py --gold ... --apply
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.db.session import SessionLocal

DESC_MARKERS = "aggregate actor label|group of related organizations"

# Category-label name patterns: a plural bucket noun with no proper-noun anchor.
# "Battery Material Startups", "Carbon Capture Research Labs", "Mineral
# Processing Facilities" -- these name a CLASS of organisation, not one.
_BUCKET_TAIL = re.compile(
    r"\b(startups|companies|firms|labs|laboratories|programs|programmes|"
    r"facilities|centers|centres|institutes|initiatives|projects|groups|"
    r"organizations|organisations|providers|manufacturers|producers|"
    r"incubators|accelerators|clusters|networks)\s*(\([^)]*\))?\s*$", re.I)


def looks_like_bucket(name: str) -> bool:
    n = (name or "").strip()
    if not _BUCKET_TAIL.search(n):
        return False
    # A proper-noun anchor (an institution name) means it is a real unit:
    # "UC Berkeley Water Center" is an organisation; "Water-Tech Startups" is not.
    anchors = ("university", "univ", "institute of", "national", "u.s.", "us ",
               "department of energy", "nasa", "noaa", "nih", "nsf")
    return not any(a in n.lower() for a in anchors)


def load_actor_classes(session) -> dict:
    """actor_id -> 'aggregate' | 'organization', from the DB.

    Two signals only: the actor_type tag (authoritative) and the description
    marker written by enrichment. The earlier name-pattern fallback was dropped
    after it misclassified real departments ("Northwestern Environmental
    Engineering") as category labels.
    """
    rows = session.execute(text("""
        SELECT actor_id::text AS actor_id,
               COALESCE(actor_type, '')  AS actor_type,
               COALESCE(description, '') AS description,
               name
          FROM actor
    """)).mappings().all()

    out = {}
    for r in rows:
        if r["actor_type"].strip().lower() == "aggregate":
            out[r["actor_id"]] = "aggregate"
        elif re.search(DESC_MARKERS, r["description"], re.I):
            out[r["actor_id"]] = "aggregate"
        else:
            out[r["actor_id"]] = "organization"
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gold", default="data/processed/entity_resolution_gold.csv")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    g = pd.read_csv(args.gold, dtype=str, keep_default_na=False)
    g.columns = [c.strip() for c in g.columns]
    print(f"[gold] {len(g)} pairs")

    s = SessionLocal()
    try:
        cls = load_actor_classes(s)
    finally:
        s.close()
    n_agg = sum(1 for v in cls.values() if v == "aggregate")
    print(f"[db]   {len(cls)} actors, {n_agg} classified aggregate "
          f"({n_agg/max(len(cls),1):.0%})")

    def pair_class(row):
        a = cls.get(str(row.get("actor_id_a", "")).strip())
        b = cls.get(str(row.get("actor_id_b", "")).strip())
        if a is None:
            a = "organization"
        if b is None:
            b = "organization"
        return "aggregate" if "aggregate" in (a, b) else "organization"

    g["entity_class"] = g.apply(pair_class, axis=1)

    print("\n[split] pairs by class and label:")
    print(pd.crosstab(g["entity_class"], g["label"].str.strip().str.lower()).to_string())

    agg = g[g.entity_class == "aggregate"]
    print(f"\n[split] aggregate pairs: {len(agg)} ({len(agg)/len(g):.0%})")
    print("  examples:")
    for _, r in agg.head(6).iterrows():
        print(f"    [{r['label']:<9}] {str(r['name_a'])[:38]:<40} || {str(r['name_b'])[:38]}")

    if not args.apply:
        print(f"\nDRY RUN — {args.gold} unchanged. Re-run with --apply to add the column.")
        return

    g.to_csv(args.gold, index=False, quoting=csv.QUOTE_MINIMAL)
    print(f"\n[saved] entity_class column added -> {args.gold}")
    print("Next: report precision separately per class, and have run_er_sweep.py "
          "demote aggregate pairs from auto_merge to review.")


if __name__ == "__main__":
    main()