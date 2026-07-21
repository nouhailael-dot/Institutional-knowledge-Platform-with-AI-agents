"""
Mine a duplicate-enriched second batch for labeling.

The Week-1 sampler was built to give a *representative* spread across similarity
bands, which is why only ~7 of 300 turned out to be true duplicates — too few
positives to evaluate on. This script does the opposite: it casts a net
specifically for duplicate-SHAPED pairs so the labeling yield of real `same`
cases is high. Heuristics (high recall for dupes):

  - acronym match            NREL  ==  National Renewable Energy Laboratory
  - name containment         Center for Watershed Sciences  in  UC Davis Center for Watershed Sciences
  - high token overlap       Carbon Capture Research Labs  ~  Carbon capture material research labs

Pairs already present in entity_resolution_gold.csv are excluded, so you only
label new pairs. Output uses band='dup_candidate' — that tag survives into the
merged gold set, so the evaluation step can keep the representative bands and the
enriched batch distinct.

Needs the DB, no API key. Run from the repo root, venv active:
    python scripts/build_duplicate_candidates.py
    python scripts/build_duplicate_candidates.py --jaccard-min 0.5 --max 200
"""

import argparse
import csv
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # repo root on path

# Connectors are dropped when forming an acronym (so "...of Technology" -> ...T),
# but content words are KEPT (so National Renewable Energy Laboratory -> NREL).
CONNECTOR_STOP = {"the", "of", "and", "for", "at", "in", "de", "la", "le",
                  "du", "des", "a", "&"}
# Generic words dropped when forming Jaccard token sets, so overlap reflects the
# distinctive part of the name rather than "research / lab / center / university".
CONTENT_STOP = CONNECTOR_STOP | {
    "research", "lab", "labs", "laboratory", "laboratories", "center", "centers",
    "centre", "institute", "institutes", "program", "programs", "university",
    "department", "national", "school", "college"}


def _norm(s: str) -> str:
    s = re.sub(r"\([^)]*\)", "", (s or "").lower())
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _acronym(norm: str) -> str:
    return "".join(t[0] for t in norm.split() if t and t not in CONNECTOR_STOP)


def _content_tokens(norm: str) -> frozenset:
    return frozenset(t for t in norm.split() if t and t not in CONTENT_STOP)


def duplicate_candidate_pairs(names, *, jaccard_min=0.6):
    """Return {(i, j): reason} for pairs that look like duplicates by name."""
    n = len(names)
    norm = [_norm(x) for x in names]
    compact = [x.replace(" ", "") for x in norm]
    acro = [_acronym(x) for x in norm]
    toks = [_content_tokens(x) for x in norm]
    out = {}
    for i in range(n):
        ci, ai, ti = compact[i], acro[i], toks[i]
        if not ci:
            continue
        for j in range(i + 1, n):
            cj, aj, tj = compact[j], acro[j], toks[j]
            if not cj:
                continue
            short, lng = (ci, cj) if len(ci) <= len(cj) else (cj, ci)
            if len(short) >= 5 and short in lng:
                out[(i, j)] = "containment"; continue
            if len(ai) >= 3 and ai == cj or len(aj) >= 3 and aj == ci:
                out[(i, j)] = "acronym"; continue
            if ti and tj:
                jac = len(ti & tj) / len(ti | tj)
                if jac >= jaccard_min:
                    out[(i, j)] = f"jaccard={jac:.2f}"
    return out


def build_rows(actor_ids, names, docs, exclude_pairs, start_pair_id,
               *, jaccard_min=0.6, max_out=150):
    """Pure (no DB): generate candidates, drop excluded, rank, cap → row dicts."""
    from sklearn.metrics.pairwise import cosine_similarity
    from src.ML.entity_resolution.text_features import tfidf_matrix

    cands = duplicate_candidate_pairs(names, jaccard_min=jaccard_min)
    _, matrix = tfidf_matrix(docs)
    sim = cosine_similarity(matrix)

    rank = {"containment": 3, "acronym": 3}  # name-overlap reasons are the dup goldmine
    scored = []
    for (i, j), reason in cands.items():
        key = frozenset((str(actor_ids[i]), str(actor_ids[j])))
        if key in exclude_pairs:
            continue
        pri = rank.get(reason, 2)
        scored.append((pri, float(sim[i, j]), i, j, reason))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

    rows = []
    for k, (_, cos, i, j, reason) in enumerate(scored[:max_out]):
        rows.append({
            "pair_id": start_pair_id + k,
            "actor_id_a": str(actor_ids[i]), "name_a": names[i],
            "actor_id_b": str(actor_ids[j]), "name_b": names[j],
            "tfidf_cosine": round(cos, 4), "band": "dup_candidate",
            "label": "", "notes": reason,
        })
    return rows


def load_existing(gold_path):
    """Return (excluded actor-pair set, next pair_id) from the existing gold file."""
    excluded, max_id = set(), 0
    p = pathlib.Path(gold_path)
    if p.exists():
        for r in csv.DictReader(p.open(encoding="utf-8")):
            excluded.add(frozenset((r["actor_id_a"], r["actor_id_b"])))
            max_id = max(max_id, int(r["pair_id"]))
    return excluded, max_id + 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="data/processed/entity_resolution_gold.csv")
    ap.add_argument("--out", default="data/processed/entity_resolution_dup_candidates.csv")
    ap.add_argument("--jaccard-min", type=float, default=0.6)
    ap.add_argument("--max", type=int, default=150)
    args = ap.parse_args()

    from src.db.session import SessionLocal
    from src.ML.entity_resolution.text_features import build_actor_documents

    excluded, next_id = load_existing(args.gold)
    print(f"Excluding {len(excluded)} already-labeled pairs; new pair_ids start at {next_id}.")

    session = SessionLocal()
    try:
        actor_ids, names, docs = build_actor_documents(session)
        rows = build_rows(actor_ids, names, docs, excluded, next_id,
                          jaccard_min=args.jaccard_min, max_out=args.max)
    finally:
        session.close()

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["pair_id", "actor_id_a", "name_a",
                                           "actor_id_b", "name_b", "tfidf_cosine",
                                           "band", "label", "notes"])
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    print(f"Wrote {len(rows)} candidate pairs to {out}")
    print(f"Reasons: {dict(Counter(r['notes'].split('=')[0] for r in rows))}")
    print("Label these (same/different), then append the labeled rows to "
          "entity_resolution_gold.csv. The band stays 'dup_candidate' so they "
          "remain distinguishable from the representative 300.")


if __name__ == "__main__":
    main()