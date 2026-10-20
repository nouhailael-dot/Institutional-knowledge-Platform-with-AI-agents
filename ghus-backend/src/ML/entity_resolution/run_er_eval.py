"""
run_er_eval.py — GHUS Entity Resolution evaluation (evidence-driven order).

Models compared (all thresholds selected on TRAIN, reported on TEST):
  tfidf_name         — char_wb 3-5 TF-IDF cosine over the NAME. The baseline to
                       beat. (TF-IDF recomputed fresh; the gold's stored
                       tfidf_cosine column is ignored to avoid leakage.)
  sbert_name         — all-MiniLM-L6-v2 cosine over the NAME only.
  combiner_name      — logistic regression over name signals only:
                       tfidf_name_sim, sbert_name_sim, acronym, containment,
                       jaccard, length_ratio.
  combiner_name_hub  — combiner_name + hub_overlap. Run alongside the name-only
                       combiner so the hub contribution is isolated: compare the
                       two auto-merge-coverage numbers to see exactly what hubs
                       add (and check the learned hub_overlap coefficient sign).

Descriptions and location are intentionally excluded: ~1% coverage on gold
pairs, 0/70 on the duplicate pairs, so they cannot help.

Selection metric = auto-merge coverage at precision >= --min-precision (0.97),
NOT F1. Note the auto-merge precision CONFIDENCE INTERVAL: the test split has
~21 positives, so the point estimate is noisy.

Usage (repo root, venv active):
  python -m src.ML.entity_resolution.run_er_eval \
      --actors data/exports/actors.csv \
      --gold   data/processed/entity_resolution_gold.csv \
      --split  data/processed/entity_resolution_split.csv \
      --out    docs/ml/results/er_eval
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

try:
    from . import er_common as ec
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parent))
    import er_common as ec


def tfidf_name_sim(p, actors):
    """Char n-gram cosine over normalized names. Fresh fit (no leakage)."""
    corpus = (actors["name"].map(ec.normalize_name).tolist() if actors is not None
              else pd.concat([p.name_a, p.name_b]).map(ec.normalize_name).unique().tolist())
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True,
                          min_df=1, lowercase=True)
    vec.fit(corpus)
    A = vec.transform(p.name_a.map(ec.normalize_name))
    B = vec.transform(p.name_b.map(ec.normalize_name))
    return np.asarray(A.multiply(B).sum(axis=1)).ravel()


def sbert_name_sim(p, model_name="sentence-transformers/all-MiniLM-L6-v2"):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("[warn] sentence-transformers not installed — sbert_name and its "
              "combiner feature will be skipped (pip install sentence-transformers)")
        return None
    model = SentenceTransformer(model_name)
    uniq = pd.concat([p.name_a, p.name_b]).unique().tolist()
    emb = model.encode(uniq, normalize_embeddings=True, batch_size=64, show_progress_bar=False)
    lut = {t: e for t, e in zip(uniq, emb)}
    return np.array([float(np.dot(lut[a], lut[b])) for a, b in zip(p.name_a, p.name_b)])


def fit_combiner(feat_cols, X, y_tr, tr_mask):
    clf = make_pipeline(StandardScaler(),
                        LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0))
    clf.fit(X[tr_mask], y_tr)
    scores = clf.predict_proba(X)[:, 1]
    lr = clf.named_steps["logisticregression"]
    coefs = sorted(zip(feat_cols, lr.coef_[0]), key=lambda x: -abs(x[1]))
    return scores, coefs


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--actors", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--split", required=True)
    ap.add_argument("--out", default="docs/ml/results/er_eval")
    ap.add_argument("--min-precision", type=float, default=0.97)
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    actors = ec.load_actors(args.actors)
    pairs = ec.load_gold_with_split(args.gold, args.split)
    pairs = ec.attach_hubs(pairs, actors)
    tr = (pairs["split"] == "train").values
    te = (pairs["split"] == "test").values
    y = pairs["y"].to_numpy()
    y_tr, y_te = y[tr], y[te]
    print(f"[data] {len(pairs)} pairs | {tr.sum()} train / {te.sum()} test | "
          f"positives: {int(y_tr.sum())} train / {int(y_te.sum())} test")

    # features
    f_tfidf = tfidf_name_sim(pairs, actors)
    f_sbert = sbert_name_sim(pairs)
    lex = ec.name_features(pairs)
    hub = ec.hub_feature(pairs)
    hub_cov = float(((pairs.hubs_a.str.strip() != "") & (pairs.hubs_b.str.strip() != "")).mean())
    print(f"[signal] hub present both sides: {hub_cov:.0%} of pairs")

    feats = pd.DataFrame({"tfidf_name_sim": f_tfidf}, index=pairs.index)
    if f_sbert is not None:
        feats["sbert_name_sim"] = f_sbert
    feats = pd.concat([feats, lex, hub], axis=1)

    # model scores
    scores, extra = {}, {}
    scores["tfidf_name"] = f_tfidf
    if f_sbert is not None:
        scores["sbert_name"] = f_sbert

    name_cols = [c for c in ["tfidf_name_sim", "sbert_name_sim", "acronym_match",
                             "containment", "jaccard", "length_ratio"] if c in feats.columns]
    Xn = feats[name_cols].to_numpy(float)
    scores["combiner_name"], coefs_n = fit_combiner(name_cols, Xn, y_tr, tr)
    extra["combiner_name"] = "weights: " + ", ".join(f"{n}={c:+.2f}" for n, c in coefs_n)

    hub_cols = name_cols + ["hub_overlap"]
    Xh = feats[hub_cols].to_numpy(float)
    scores["combiner_name_hub"], coefs_h = fit_combiner(hub_cols, Xh, y_tr, tr)
    extra["combiner_name_hub"] = "weights: " + ", ".join(f"{n}={c:+.2f}" for n, c in coefs_h)

    print("\n[combiner_name] learned weights (standardized):")
    for n, c in coefs_n:
        print(f"    {n:<16}{c:+.3f}")
    print("[combiner_name_hub] learned weights:")
    for n, c in coefs_h:
        print(f"    {n:<16}{c:+.3f}")
    hub_w = dict(coefs_h).get("hub_overlap", 0.0)
    print(f"\n[hub check] hub_overlap coefficient = {hub_w:+.3f} "
          f"({'helps' if hub_w > 0.05 else 'hurts' if hub_w < -0.05 else 'negligible'})")

    # evaluate
    reports = []
    for name, s in scores.items():
        rep = ec.evaluate(name, y_tr, s[tr], y_te, s[te], min_p=args.min_precision)
        if name in extra:
            rep.notes = (rep.notes + " | " if rep.notes else "") + extra[name]
        reports.append(rep)
        ec.save_pr_curve(y_te, s[te], out / f"pr_test_{name}.csv")

    table = ec.to_frame(reports)
    pd.set_option("display.width", 240); pd.set_option("display.max_columns", 40)
    print("\n===== MODEL COMPARISON (metrics on TEST, thresholds from TRAIN) =====")
    print(table.round(3).to_string(index=False))
    print(f"\nSelect on automerge_coverage at precision >= {args.min_precision} (not F1). "
          "Read am_prec_ci — only ~21 test positives.")
    print("Hub verdict: compare combiner_name vs combiner_name_hub auto-merge coverage, "
          "and the hub_overlap sign above.")

    table.to_csv(out / "results_summary.csv", index=False)
    wide = pairs[["pair_id", "name_a", "name_b", "y", "split"]].copy()
    for name, s in scores.items():
        wide[f"score_{name}"] = s
    wide = pd.concat([wide, feats], axis=1)
    wide.to_csv(out / "pair_scores.csv", index=False)
    (out / "thresholds.json").write_text(json.dumps(
        {r.model: {"high_auto_merge": r.automerge_threshold, "low_different": r.low_threshold,
                   "best_f1": r.f1_threshold} for r in reports}, indent=2))
    print(f"\n[saved] {out}/results_summary.csv, pair_scores.csv, thresholds.json, pr_test_*.csv")


if __name__ == "__main__":
    main()
