"""
Build the entity-resolution labeling set (Week 1 of the handoff plan).

With ~900 actors there are ~405K possible pairs, almost all obvious non-dupes,
so random sampling would yield a labeling set with almost no real duplicates in
it. Instead we stratify:

  - TF-IDF cosine over the actor documents splits pairs into high / mid / low bands.
  - A lexical pass (acronym match + substring containment) adds duplicate-looking
    pairs that TF-IDF misses — e.g. "MIT" vs "Massachusetts Institute of Technology",
    where the surface tokens barely overlap.

We then sample ~100 from the probable band (high cosine + lexical), ~100 from the
ambiguous mid band, and ~100 from the clearly-different low band, and write them
out with empty `label`/`notes` columns for you to fill.

This needs the DB but NO Claude API key. Run from the repo root, venv active:
    python scripts/build_entity_resolution_dataset.py
    python scripts/build_entity_resolution_dataset.py --n-high 120 --high 0.50
"""

import argparse
import csv
import pathlib
import random
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # repo root on path

STOP = {"the", "of", "and", "for", "at", "in", "de", "la", "le", "du", "des", "a"}


def _norm_name(s: str) -> str:
    s = re.sub(r"\([^)]*\)", "", (s or "").lower())   # drop parentheticals
    s = re.sub(r"[^a-z0-9 ]", " ", s)                  # keep alphanumerics
    return re.sub(r"\s+", " ", s).strip()


def _acronym(norm: str) -> str:
    return "".join(t[0] for t in norm.split() if t and t not in STOP)


def lexical_candidate_pairs(names) -> set:
    """Index pairs (i, j) with i<j that look like duplicates by name alone."""
    n = len(names)
    norm = [_norm_name(x) for x in names]
    compact = [x.replace(" ", "") for x in norm]
    acro = [_acronym(x) for x in norm]
    pairs = set()
    for i in range(n):
        ci, ai = compact[i], acro[i]
        if not ci:
            continue
        for j in range(i + 1, n):
            cj, aj = compact[j], acro[j]
            if not cj:
                continue
            short, lng = (ci, cj) if len(ci) <= len(cj) else (cj, ci)
            if len(short) >= 4 and short in lng:        # substring containment
                pairs.add((i, j)); continue
            if len(ai) >= 3 and ai == cj:               # acronym of i == name j
                pairs.add((i, j)); continue
            if len(aj) >= 3 and aj == ci:               # acronym of j == name i
                pairs.add((i, j))
    return pairs


def build_candidate_pairs(actor_ids, names, docs, *, n_high=100, n_mid=100,
                          n_low=100, high=0.55, mid_low=0.20, seed=42):
    """Pure (no DB): TF-IDF + bands + lexical injection + sampling → list of row dicts."""
    from sklearn.metrics.pairwise import cosine_similarity
    from src.ML.entity_resolution.text_features import tfidf_matrix

    rng = random.Random(seed)
    _, matrix = tfidf_matrix(docs)
    sim = cosine_similarity(matrix)
    n = len(names)

    high_pairs, mid_pairs, low_pairs = [], [], []
    for i in range(n):
        for j in range(i + 1, n):
            s = float(sim[i, j])
            if s >= high:
                high_pairs.append((i, j, s, "high"))
            elif s >= mid_low:
                mid_pairs.append((i, j, s, "mid"))
            else:
                low_pairs.append((i, j, s, "low"))

    # Inject lexical look-alikes into the probable pool if TF-IDF didn't catch them.
    already = {(i, j) for i, j, _, _ in high_pairs}
    for (i, j) in lexical_candidate_pairs(names):
        if (i, j) not in already:
            high_pairs.append((i, j, float(sim[i, j]), "lexical"))

    def take(pool, k):
        return pool if len(pool) <= k else rng.sample(pool, k)

    chosen = take(high_pairs, n_high) + take(mid_pairs, n_mid) + take(low_pairs, n_low)
    rows = []
    for pid, (i, j, s, band) in enumerate(chosen, 1):
        rows.append({
            "pair_id": pid,
            "actor_id_a": str(actor_ids[i]), "name_a": names[i],
            "actor_id_b": str(actor_ids[j]), "name_b": names[j],
            "tfidf_cosine": round(s, 4), "band": band,
            "label": "", "notes": "",
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/processed/entity_resolution_pairs.csv")
    ap.add_argument("--n-high", type=int, default=100)
    ap.add_argument("--n-mid", type=int, default=100)
    ap.add_argument("--n-low", type=int, default=100)
    ap.add_argument("--high", type=float, default=0.55, help="cosine >= this is 'probable'")
    ap.add_argument("--mid-low", type=float, default=0.20, help="cosine >= this is 'ambiguous'")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    from src.db.session import SessionLocal
    from src.ML.entity_resolution.text_features import build_actor_documents

    session = SessionLocal()
    try:
        actor_ids, names, docs = build_actor_documents(session)
        print(f"Actors: {len(actor_ids)}  (~{len(actor_ids) * (len(actor_ids) - 1) // 2} pairs)")
        rows = build_candidate_pairs(
            actor_ids, names, docs,
            n_high=args.n_high, n_mid=args.n_mid, n_low=args.n_low,
            high=args.high, mid_low=args.mid_low, seed=args.seed,
        )
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
    bands = Counter(r["band"] for r in rows)
    print(f"Wrote {len(rows)} pairs to {out}")
    print(f"Bands: {dict(bands)}")
    print("Next: open the CSV, fill the 'label' column with 'same' or 'different' "
          "for each pair, then save it as data/processed/entity_resolution_gold.csv")


if __name__ == "__main__":
    main()