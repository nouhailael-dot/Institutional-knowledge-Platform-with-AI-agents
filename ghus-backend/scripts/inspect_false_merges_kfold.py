"""
inspect_false_merges.py — show WHICH pairs the model would wrongly auto-merge.

The k-fold reports how many false merges occur but not which pairs they are, so
the failure mode stays invisible. This scores every labeled pair with an
out-of-fold model and lists the negatives that land above the auto-merge
threshold — the pairs that would be silently merged in production.

Out-of-fold scoring matters: scoring a pair with a model that trained on it
gives an optimistically low score and hides the very errors we are looking for.

Also prints the precision/coverage curve across candidate thresholds, so you can
read off where precision reaches your 0.97 gate and what coverage costs.

    python scripts/inspect_false_merges.py \
        --actors data/exports/actors.csv \
        --gold   data/processed/entity_resolution_gold.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from src.ML.entity_resolution import er_common as ec
    from src.ML.entity_resolution.er_mismatch_features import mismatch_features, MISMATCH_FEATURE_COLS
    from src.ML.entity_resolution.er_description_features import description_features, DESC_FEATURE_COLS
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parent))
    import er_common as ec
    from src.ML.entity_resolution.er_mismatch_features import mismatch_features, MISMATCH_FEATURE_COLS
    from src.ML.entity_resolution.er_description_features import description_features, DESC_FEATURE_COLS


DROP = {"desc_both_present", "desc_sbert_sim", "numeric_mismatch"}
BASE = ["tfidf_name_sim", "sbert_name_sim", "acronym_match",
        "containment", "jaccard", "length_ratio"]


def build_features(g, actors):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sentence_transformers import SentenceTransformer

    corpus = actors["name"].map(ec.normalize_name).tolist()
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5),
                          sublinear_tf=True, min_df=1).fit(corpus)
    A = vec.transform(g.name_a.map(ec.normalize_name))
    B = vec.transform(g.name_b.map(ec.normalize_name))
    tfidf = np.asarray(A.multiply(B).sum(axis=1)).ravel()

    m = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    uniq = pd.concat([g.name_a, g.name_b]).unique().tolist()
    emb = m.encode(uniq, normalize_embeddings=True, batch_size=64, show_progress_bar=False)
    lut = {t: e for t, e in zip(uniq, emb)}
    sbert = np.array([float(np.dot(lut[a], lut[b])) for a, b in zip(g.name_a, g.name_b)])

    f = pd.DataFrame({"tfidf_name_sim": tfidf, "sbert_name_sim": sbert}, index=g.index)
    f = pd.concat([f, ec.name_features(g), mismatch_features(g),
                   description_features(g)], axis=1)
    import json
    cfg = json.loads(Path("config/er_production.json").read_text())
    cols = [c for c in cfg["features"] if c in f.columns]
    return f[cols], cols


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--actors", default="data/exports/actors.csv")
    ap.add_argument("--gold", default="data/processed/entity_resolution_gold.csv")
    ap.add_argument("--threshold", type=float, default=0.9475,
                    help="auto-merge threshold to inspect (k-fold mean)")
    ap.add_argument("--out", default="docs/ml/results/false_merges.csv")
    args = ap.parse_args()

    actors = ec.load_actors(args.actors)
    g = pd.read_csv(args.gold, dtype=str).fillna("")
    g.columns = [c.strip() for c in g.columns]
    lab = g["label"].str.strip().str.lower()
    g = g[lab.isin(ec._POSITIVE | ec._NEGATIVE)].copy()
    g["y"] = g["label"].str.strip().str.lower().isin(ec._POSITIVE).astype(int)
    g = ec.attach_hubs(g, actors)
    g = ec.attach_descriptions(g, actors)
    g = g.reset_index(drop=True)
    print(f"[data] {len(g)} pairs, {int(g.y.sum())} positives")

    X, cols = build_features(g, actors)
    y = g.y.to_numpy()
    Xv = X.to_numpy(float)

    # out-of-fold scores: every pair scored by a model that never saw it
    oof = np.zeros(len(g))
    for tr, te in StratifiedKFold(n_splits=5, shuffle=True, random_state=0).split(Xv, y):
        clf = make_pipeline(StandardScaler(),
                            LogisticRegression(max_iter=2000, class_weight="balanced"))
        clf.fit(Xv[tr], y[tr])
        oof[te] = clf.predict_proba(Xv[te])[:, 1]
    g["score"] = oof

    T = args.threshold
    false_merges = g[(g.y == 0) & (g.score >= T)].sort_values("score", ascending=False)
    true_merges = g[(g.y == 1) & (g.score >= T)]

    print(f"\n=== at threshold {T:.4f} ===")
    print(f"auto-merges: {len(false_merges) + len(true_merges)}  "
          f"(true {len(true_merges)}, FALSE {len(false_merges)})")
    prec = len(true_merges) / max(len(true_merges) + len(false_merges), 1)
    print(f"precision {prec:.3f} | coverage {len(true_merges)/max(int(y.sum()),1):.1%}")

    print(f"\n--- THE FALSE MERGES ({len(false_merges)}) ---")
    for _, r in false_merges.iterrows():
        print(f"\n  score {r.score:.4f}")
        print(f"    A: {str(r.name_a)[:70]}")
        print(f"    B: {str(r.name_b)[:70]}")
        note = str(r.get("notes", ""))[:100]
        if note:
            print(f"    labeled different because: {note}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    false_merges[["pair_id", "name_a", "name_b", "score", "notes"]].to_csv(out, index=False)
    print(f"\n[saved] {out}")

    # Aggregate labels ("Climate Tech Startups", "Carbon Capture Research Labs")
    # are category buckets, not organisations. Whether two are "the same" is a
    # judgement call even for a human, so they are excluded from auto-merge and
    # always routed to review.
    AGG = "aggregate actor label|hub-linked actor referenced"
    is_agg = (g.desc_a.str.contains(AGG, case=False, na=False) |
              g.desc_b.str.contains(AGG, case=False, na=False))
    print(f"\n[partition] aggregate-label pairs: {is_agg.sum()} of {len(g)}")
    real = g[~is_agg]
    print("=== curve on REAL ORGANISATIONS only ===")
    for t in np.arange(0.90, 0.995, 0.005):
        a = real[real.score >= t]
        tm = int((a.y == 1).sum()); fm = int((a.y == 0).sum())
        if tm + fm == 0: continue
        p = tm / (tm + fm)
        c = tm / max(int((real.y == 1).sum()), 1)
        flag = "  <-- >= 0.97" if p >= 0.97 else ""
        print(f"{t:>10.3f} {tm+fm:>6} {tm:>6} {fm:>6} {p:>7.3f} {c:>6.1%}{flag}")

    print("\n=== precision / coverage curve ===")
    print(f"{'threshold':>10} {'auto':>6} {'true':>6} {'false':>6} {'prec':>7} {'cov':>7}")
    for t in np.arange(0.90, 0.995, 0.005):
        a = g[g.score >= t]
        tm = int((a.y == 1).sum()); fm = int((a.y == 0).sum())
        if tm + fm == 0:
            continue
        p = tm / (tm + fm)
        c = tm / max(int(y.sum()), 1)
        flag = "  <-- precision >= 0.97" if p >= 0.97 else ""
        print(f"{t:>10.3f} {tm+fm:>6} {tm:>6} {fm:>6} {p:>7.3f} {c:>6.1%}{flag}")


if __name__ == "__main__":
    main()