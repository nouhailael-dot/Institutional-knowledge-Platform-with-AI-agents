"""
create_hierarchy_edges.py — turn confirmed sub-unit pairs into hierarchy edges.

The backfill separated pairs a human labeled 'same' into three buckets. The
hierarchy bucket is NOT a duplicate: "UC Berkeley" and "UC Berkeley Chemistry"
are two real, distinct actors in a parent -> child relationship. That structure
currently exists nowhere in the database; this script writes it into
organization_hierarchy so the relationship is preserved instead of lost.

PARENT/CHILD direction: the name whose tokens are contained in the other is the
parent ("UC Berkeley" is the parent of "UC Berkeley Chemistry"). Rows where the
direction cannot be determined are skipped and reported, not guessed.

Merged-away actors are resolved to their canonical winner first, so an edge
never points at a soft-deleted row.

DRY RUN BY DEFAULT.

    python scripts/create_hierarchy_edges.py --pairs docs/ml/results/hierarchy_candidates.csv
    python scripts/create_hierarchy_edges.py --pairs ... --apply
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.db.session import SessionLocal

RELATIONSHIP_TYPE = "sub_unit"


def toks(name):
    return set(re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).split())


def direction(name_a, name_b):
    """Return (parent_name, child_name) or None if it cannot be determined."""
    ta, tb = toks(name_a), toks(name_b)
    if ta < tb:
        return name_a, name_b
    if tb < ta:
        return name_b, name_a
    return None


def canonical(conn, actor_id):
    """Follow merged_into_actor_id to the surviving actor."""
    seen = set()
    cur = actor_id
    for _ in range(10):
        row = conn.execute(text(
            "SELECT actor_id::text, name, merged_into_actor_id::text "
            "FROM actor WHERE actor_id = CAST(:id AS uuid)"), {"id": cur}).mappings().first()
        if row is None:
            return None, None
        if not row["merged_into_actor_id"]:
            return row["actor_id"], row["name"]
        if cur in seen:
            return None, None
        seen.add(cur)
        cur = row["merged_into_actor_id"]
    return None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pairs", default="docs/ml/results/hierarchy_candidates.csv")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    df = pd.read_csv(args.pairs, dtype=str).fillna("")
    print(f"[input] {len(df)} candidate sub-unit pairs")

    s = SessionLocal(); conn = s.connection()
    plan, skipped = [], []
    for _, r in df.iterrows():
        d = direction(r["name_a"], r["name_b"])
        if d is None:
            skipped.append((r["name_a"], r["name_b"], "direction unclear"))
            continue
        parent_name, child_name = d
        pid = r["actor_id_a"] if r["name_a"] == parent_name else r["actor_id_b"]
        cid = r["actor_id_b"] if r["name_a"] == parent_name else r["actor_id_a"]
        pid, pname = canonical(conn, pid)
        cid, cname = canonical(conn, cid)
        if not pid or not cid:
            skipped.append((parent_name, child_name, "actor missing"))
            continue
        if pid == cid:
            skipped.append((parent_name, child_name, "both resolve to the same actor"))
            continue
        exists = conn.execute(text(
            "SELECT 1 FROM organization_hierarchy "
            "WHERE parent_actor_id = CAST(:p AS uuid) AND child_actor_id = CAST(:c AS uuid)"),
            {"p": pid, "c": cid}).first()
        if exists:
            skipped.append((pname, cname, "edge already exists"))
            continue
        plan.append({"parent_actor_id": pid, "parent_name": pname,
                     "child_actor_id": cid, "child_name": cname})

    print(f"\n[plan] {len(plan)} hierarchy edge(s) to create:")
    for p in plan:
        print(f"   {p['parent_name'][:46]:<48} -> {p['child_name'][:46]}")
    if skipped:
        print(f"\n[skipped] {len(skipped)}:")
        for a, b, why in skipped:
            print(f"   [{why}] {a[:40]} || {b[:40]}")

    if not args.apply:
        s.close()
        print("\nDRY RUN — nothing written. Re-run with --apply to create the edges.")
        return

    for p in plan:
        conn.execute(text(
            "INSERT INTO organization_hierarchy "
            "(parent_actor_id, child_actor_id, relationship_type) "
            "VALUES (CAST(:p AS uuid), CAST(:c AS uuid), :t) ON CONFLICT DO NOTHING"),
            {"p": p["parent_actor_id"], "c": p["child_actor_id"], "t": RELATIONSHIP_TYPE})
    s.commit(); s.close()
    print(f"\n[done] created {len(plan)} hierarchy edge(s) with "
          f"relationship_type='{RELATIONSHIP_TYPE}'.")


if __name__ == "__main__":
    main()