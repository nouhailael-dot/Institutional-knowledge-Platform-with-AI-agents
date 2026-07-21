"""
apply_review_decisions.py — act on a completed review workbook.

Reads the workbook produced by export_review_queue.py and, for each decided row:

  same       -> merge the pair (winner = more complete record), method='human_review',
                and link the resulting merge_id back to the review row
  hierarchy  -> create an organization_hierarchy edge (parent = the contained name)
  different  -> record the decision only
  skip       -> left pending

Every decision is also appended to the gold CSV as a new labeled pair, so human
review keeps growing the training set. That is what eventually widens the
auto-merge band: the model learns from exactly the cases it could not decide.

DRY RUN BY DEFAULT.

    python scripts/apply_review_decisions.py --workbook docs/ml/results/review_queue.xlsx
    python scripts/apply_review_decisions.py --workbook ... --apply
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.db.session import SessionLocal
try:
    from actor_merge import merge_actors
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parent))
    from actor_merge import merge_actors

VALID = {"same", "different", "hierarchy", "skip"}
COMPLETENESS_FIELDS = [
    "actor_type", "actor_type_raw", "description", "website", "location_city",
    "state", "country", "primary_technical_focus", "technical_approach",
    "current_activities", "technology_ip_notes", "key_constraints",
    "estimated_trl", "primary_lifecycle_role", "source_id",
]


def toks(n):
    return set(re.sub(r"[^a-z0-9 ]", " ", str(n).lower()).split())


def completeness(conn, actor_id):
    row = conn.execute(text("SELECT * FROM actor WHERE actor_id = CAST(:a AS uuid)"),
                       {"a": actor_id}).mappings().first()
    if row is None:
        return -1
    return sum(1 for f in COMPLETENESS_FIELDS
               if row.get(f) is not None and str(row.get(f)).strip() != "")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workbook", default="docs/ml/results/review_queue.xlsx")
    ap.add_argument("--gold", default="data/processed/entity_resolution_gold.csv")
    ap.add_argument("--decided-by", default="human_review")
    ap.add_argument("--batch", default="sweep_review")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    df = pd.read_excel(args.workbook, sheet_name="Pairs to review", dtype=str).fillna("")
    df["decision"] = df["decision"].str.strip().str.lower()
    bad = df[(df.decision != "") & (~df.decision.isin(VALID))]
    if len(bad):
        print(f"[warn] {len(bad)} row(s) have an unrecognized decision; they will be ignored")
    decided = df[df.decision.isin(VALID - {"skip"})]
    print(f"[input] {len(df)} rows | decided: {len(decided)} "
          f"({decided.decision.value_counts().to_dict()})")
    if decided.empty:
        print("nothing decided yet."); return

    s = SessionLocal(); conn = s.connection()
    merges, edges, others = [], [], []
    for _, r in decided.iterrows():
        a, b, na, nb = r["actor_id_a"], r["actor_id_b"], r["name_a"], r["name_b"]
        if r["decision"] == "same":
            ca, cb = completeness(conn, a), completeness(conn, b)
            if ca > cb or (ca == cb and len(str(na)) >= len(str(nb))):
                winner, loser, wn, ln = a, b, na, nb
            else:
                winner, loser, wn, ln = b, a, nb, na
            merges.append((r["review_id"], winner, loser, wn, ln, float(r["score"])))
        elif r["decision"] == "hierarchy":
            ta, tb = toks(na), toks(nb)
            if ta < tb:
                edges.append((r["review_id"], a, b, na, nb))
            elif tb < ta:
                edges.append((r["review_id"], b, a, nb, na))
            else:
                others.append((r["review_id"], "hierarchy direction unclear", na, nb))
        else:
            others.append((r["review_id"], "different", na, nb))

    print(f"\n[plan] {len(merges)} merge(s):")
    for _, _, _, wn, ln, sc in merges[:20]:
        print(f"   {sc:.3f}  KEEP {str(wn)[:44]:<46} + {str(ln)[:44]}")
    print(f"\n[plan] {len(edges)} hierarchy edge(s):")
    for _, _, _, pn, cn in edges[:20]:
        print(f"   {str(pn)[:44]:<46} -> {str(cn)[:44]}")
    print(f"\n[plan] {len(others)} decision(s) recorded without a DB change")

    if not args.apply:
        s.close()
        print("\nDRY RUN — nothing written. Re-run with --apply.")
        return

    now = datetime.now(timezone.utc)
    done = failed = 0
    for rid, winner, loser, wn, ln, sc in merges:
        try:
            mid = merge_actors(SessionLocal, winner, loser, score=sc,
                               method="human_review", decided_by=args.decided_by)
            conn.execute(text(
                "UPDATE review_queue SET status='same', decided_by=:by, decided_at=:at, "
                "merge_id=CAST(:m AS uuid) WHERE review_id = CAST(:r AS uuid)"),
                {"by": args.decided_by, "at": now, "m": str(mid), "r": rid})
            done += 1
        except Exception as e:
            failed += 1
            print(f"   FAILED merge {ln[:40]} -> {wn[:40]}: {type(e).__name__}: {e}")
    for rid, pid, cid, pn, cn in edges:
        conn.execute(text(
            "INSERT INTO organization_hierarchy (parent_actor_id, child_actor_id, "
            "relationship_type) VALUES (CAST(:p AS uuid), CAST(:c AS uuid), 'sub_unit') "
            "ON CONFLICT DO NOTHING"), {"p": pid, "c": cid})
        conn.execute(text(
            "UPDATE review_queue SET status='hierarchy', decided_by=:by, decided_at=:at "
            "WHERE review_id = CAST(:r AS uuid)"), {"by": args.decided_by, "at": now, "r": rid})
    for rid, kind, _, _ in others:
        conn.execute(text(
            "UPDATE review_queue SET status='different', decided_by=:by, decided_at=:at "
            "WHERE review_id = CAST(:r AS uuid)"), {"by": args.decided_by, "at": now, "r": rid})
    s.commit(); s.close()
    print(f"\n[applied] {done} merged ({failed} failed), {len(edges)} hierarchy edge(s), "
          f"{len(others)} recorded")

    # append every decision to the gold set as new labels
    gold_path = Path(args.gold)
    gold = pd.read_csv(gold_path, dtype=str, keep_default_na=False)
    next_id = pd.to_numeric(gold["pair_id"], errors="coerce").max()
    next_id = 1 if pd.isna(next_id) else int(next_id) + 1
    rows = []
    for _, r in decided.iterrows():
        label = "same" if r["decision"] == "same" else "different"
        note = ("Confirmed duplicate via review queue." if r["decision"] == "same"
                else "Sub-unit relationship, not a duplicate." if r["decision"] == "hierarchy"
                else "Distinct organizations.")
        rows.append({"pair_id": next_id, "name_a": r["name_a"], "name_b": r["name_b"],
                     "tfidf_cosine": "", "band": "sweep_review", "match_reason": "",
                     "label": label, "notes": note, "reclassified": "",
                     "review_flag": ("sub-unit" if r["decision"] == "hierarchy" else ""),
                     "source_batch": args.batch,
                     "actor_id_a": r["actor_id_a"], "actor_id_b": r["actor_id_b"]})
        next_id += 1
    new = pd.concat([gold, pd.DataFrame(rows)[gold.columns]], ignore_index=True)
    new.to_csv(gold_path, index=False)
    print(f"[gold] appended {len(rows)} labeled pair(s) -> {gold_path} "
          f"(now {len(new)} rows). Re-run k-fold to see if the auto-merge band widens.")


if __name__ == "__main__":
    main()