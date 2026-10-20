"""
run_er_kfold.py — stabilize the auto-merge threshold with k-fold CV.

Why this exists
---------------
The single 315/135 split estimates the auto-merge band on ~21 test positives —
in practice only 1-3 pairs land in the band, so the "precision >= 0.97" behind
it is unverifiable (its bootstrap CI is built on 3 points). This harness rotates
every one of the 450 pairs through a held-out fold, so the auto-merge threshold
is chosen on ~56 positives per fold and evaluated on the rest, and the POOLED
auto-merge precision is measured over all ~70 positives.

What it answers
---------------
1. How WIDE is the safe auto-merge band on average (pooled coverage)?
2. How STABLE is the threshold across folds (mean +/- std, min..max)? A tight
   spread => deployable; a wide spread => the band is fragile and you need more
   labeled positives before trusting auto-merge.
3. Does hub_overlap help ROBUSTLY (across folds), not just on one split?

Protocol (no leakage)
---------------------
TF-IDF vocabulary/IDF and SBERT are unsupervised/pretrained, so features are
built once on all pairs. Only the SUPERVISED parts — the logistic-regression
combiner and the auto-merge threshold — are fit on each fold's TRAIN portion and
applied to its held-out TEST fold.

Usage (repo root or scripts/, venv active):
  python scripts/run_er_kfold.py \
      --actors data/exports/actors.csv \
      --gold   data/processed/entity_resolution_gold.csv \
      --folds 5 --repeats 1 \
      --out    docs/ml/results/er_kfold
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
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from er_mismatch_features import mismatch_features, MISMATCH_FEATURE_COLS
from er_description_features import description_features, DESC_FEATURE_COLS

try:
    from . import er_common as ec
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parent))
    import er_common as ec


# ---- features (same definitions as run_er_eval; kept here so this file is
#      self-contained and robust to import-path differences) -----------------
def tfidf_name_sim(pairs, actors):
    corpus = actors["name"].map(ec.normalize_name).tolist()
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True,
                          min_df=1, lowercase=True).fit(corpus)
    A = vec.transform(pairs.name_a.map(ec.normalize_name))
    B = vec.transform(pairs.name_b.map(ec.normalize_name))
    return np.asarray(A.multiply(B).sum(axis=1)).ravel()


def sbert_name_sim(pairs, model_name="sentence-transformers/all-MiniLM-L6-v2"):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("[warn] sentence-transformers missing — running WITHOUT the SBERT "
              "feature (install it to match production).")
        return None
    model = SentenceTransformer(model_name)
    uniq = pd.concat([pairs.name_a, pairs.name_b]).unique().tolist()
    emb = model.encode(uniq, normalize_embeddings=True, batch_size=64, show_progress_bar=False)
    lut = {t: e for t, e in zip(uniq, emb)}
    return np.array([float(np.dot(lut[a], lut[b])) for a, b in zip(pairs.name_a, pairs.name_b)])


def load_gold(gold_path):
    g = pd.read_csv(gold_path, dtype=str).fillna("")
    g.columns = [c.strip() for c in g.columns]
    lab = g["label"].str.strip().str.lower()
    g = g[lab.isin(ec._POSITIVE | ec._NEGATIVE)].copy()
    g["y"] = g["label"].str.strip().str.lower().isin(ec._POSITIVE).astype(int)
    for c in ("actor_id_a", "actor_id_b", "source_batch", "pair_id"):
        if c not in g.columns:
            g[c] = ""
    return g.reset_index(drop=True)


def combiner_scores_cv(X, y, strat, n_splits, seed):
    """Return OOF auto-merge decisions + per-fold thresholds.

    For each fold: fit LogReg on train, pick the smallest train threshold with
    precision >= MIN_PRECISION, apply to the held-out fold. Collect, per pair:
    its out-of-fold probability, and whether it was auto-merged under its own
    fold's threshold.
    """
    oof_score = np.full(len(y), np.nan)
    oof_auto = np.zeros(len(y), dtype=int)
    fold_rows = []
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    for k, (tr, te) in enumerate(skf.split(X, strat), 1):
        clf = make_pipeline(StandardScaler(),
                            LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0))
        clf.fit(X[tr], y[tr])
        s_tr = clf.predict_proba(X[tr])[:, 1]
        s_te = clf.predict_proba(X[te])[:, 1]
        oof_score[te] = s_te

        high = ec._automerge_threshold(y[tr], s_tr, ec.MIN_PRECISION)
        if high is not None:
            auto = s_te >= high
            oof_auto[te] = auto.astype(int)
            p, r, _, tp, fp, _ = ec._prf(y[te], s_te, high)
            fold_rows.append(dict(fold=k, threshold=round(high, 4),
                                  test_pos=int(y[te].sum()), auto_n=int(auto.sum()),
                                  true_merges=tp, false_merges=fp,
                                  coverage=round(r, 3), precision=round(p, 3)))
        else:
            fold_rows.append(dict(fold=k, threshold=np.nan, test_pos=int(y[te].sum()),
                                  auto_n=0, true_merges=0, false_merges=0,
                                  coverage=0.0, precision=np.nan))
    return oof_score, oof_auto, pd.DataFrame(fold_rows)


def pooled_stats(y, oof_auto):
    tp = int(((oof_auto == 1) & (y == 1)).sum())
    fp = int(((oof_auto == 1) & (y == 0)).sum())
    pos = int((y == 1).sum())
    precision = tp / (tp + fp) if tp + fp else float("nan")
    coverage = tp / pos if pos else float("nan")
    return dict(auto_total=tp + fp, true_merges=tp, false_merges=fp,
                pooled_precision=precision, pooled_coverage=coverage)


def bootstrap_pooled_precision(y, oof_auto, n_boot=5000, seed=13):
    rng = np.random.default_rng(seed)
    n = len(y); vals = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        a = oof_auto[idx] == 1
        d = int(a.sum())
        if d:
            vals.append(float((a & (y[idx] == 1)).sum() / d))
    return (float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))) if vals else (np.nan, np.nan)


def run_model(label, feat_cols, feats, y, strat, folds, repeats, seed0, out):
    X = feats[feat_cols].to_numpy(float)
    all_fold_tables, thr_all = [], []
    agg_auto = np.zeros(len(y), dtype=int)  # pooled over the first repeat for CI
    for rep in range(repeats):
        seed = seed0 + rep
        oof_score, oof_auto, ft = combiner_scores_cv(X, y, strat, folds, seed)
        ft["repeat"] = rep
        all_fold_tables.append(ft)
        thr_all.extend([t for t in ft["threshold"].tolist() if not np.isnan(t)])
        if rep == 0:
            agg_auto = oof_auto
            oof0 = oof_score
    folds_df = pd.concat(all_fold_tables, ignore_index=True)
    ps = pooled_stats(y, agg_auto)
    lo, hi = bootstrap_pooled_precision(y, agg_auto)
    thr_arr = np.array(thr_all, dtype=float)
    summary = dict(
        model=label,
        threshold_mean=round(float(np.mean(thr_arr)), 4) if len(thr_arr) else np.nan,
        threshold_std=round(float(np.std(thr_arr)), 4) if len(thr_arr) else np.nan,
        threshold_min=round(float(np.min(thr_arr)), 4) if len(thr_arr) else np.nan,
        threshold_max=round(float(np.max(thr_arr)), 4) if len(thr_arr) else np.nan,
        pooled_coverage=round(ps["pooled_coverage"], 3),
        pooled_precision=round(ps["pooled_precision"], 3) if ps["pooled_precision"] == ps["pooled_precision"] else np.nan,
        precision_ci=f"[{lo:.2f},{hi:.2f}]",
        auto_total=ps["auto_total"], true_merges=ps["true_merges"], false_merges=ps["false_merges"],
    )
    folds_df.to_csv(out / f"kfold_folds_{label}.csv", index=False)
    return summary, folds_df


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--actors", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--repeats", type=int, default=1,
                    help="repeat CV with different shuffles for a tighter stability read")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="docs/ml/results/er_kfold")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    actors = ec.load_actors(args.actors)
    g = load_gold(args.gold)
    g = ec.attach_hubs(g, actors)
    g = ec.attach_descriptions(g, actors)
    y = g["y"].to_numpy()
    print(f"[data] {len(g)} pairs | positives: {int(y.sum())} | "
          f"{args.folds}-fold x {args.repeats} repeat(s) => "
          f"~{int(y.sum())//args.folds} positives per held-out fold")

    f_tfidf = tfidf_name_sim(g, actors)
    f_sbert = sbert_name_sim(g)
    feats = pd.DataFrame({"tfidf_name_sim": f_tfidf}, index=g.index)
    if f_sbert is not None:
        feats["sbert_name_sim"] = f_sbert
    feats = pd.concat([feats, ec.name_features(g), ec.hub_feature(g),
                   mismatch_features(g), description_features(g)], axis=1)
    base_cols = [c for c in ["tfidf_name_sim", "sbert_name_sim", "acronym_match",
                         "containment", "jaccard", "length_ratio"] + MISMATCH_FEATURE_COLS + DESC_FEATURE_COLS
             if c in feats.columns]
    strat = g["y"].astype(str).to_numpy()  # stratify folds by label

    summaries = []
    s_name, _ = run_model("combiner_name", base_cols, feats, y, strat,
                          args.folds, args.repeats, args.seed, out)
    summaries.append(s_name)
    s_hub, folds_hub = run_model("combiner_name_hub", base_cols + ["hub_overlap"], feats, y,
                                 strat, args.folds, args.repeats, args.seed, out)
    summaries.append(s_hub)

    table = pd.DataFrame(summaries)
    pd.set_option("display.width", 220); pd.set_option("display.max_columns", 30)
    print("\n===== K-FOLD AUTO-MERGE STABILITY (pooled over all pairs) =====")
    print(table.to_string(index=False))
    print("\nPer-fold detail for combiner_name_hub:")
    print(folds_hub.to_string(index=False))

    # verdict
    hub = next(s for s in summaries if s["model"] == "combiner_name_hub")
    spread = hub["threshold_max"] - hub["threshold_min"]
    print("\n----- read -----")
    print(f"threshold: mean {hub['threshold_mean']}  spread {spread:.3f} "
          f"({hub['threshold_min']}..{hub['threshold_max']})")
    print(f"pooled auto-merge precision: {hub['pooled_precision']} {hub['precision_ci']} "
          f"over {hub['auto_total']} auto-merges ({hub['false_merges']} false)")
    print(f"pooled coverage: {hub['pooled_coverage']:.0%} of the {int(y.sum())} true duplicates")
    stable = spread <= 0.05
    prec_ok = hub["pooled_precision"] == hub["pooled_precision"] and hub["pooled_precision"] >= 0.97
    print(f"\nthreshold {'STABLE' if stable else 'UNSTABLE'} (spread "
          f"{'<=' if stable else '>'} 0.05); pooled precision "
          f"{'>= 0.97 OK' if prec_ok else 'below 0.97 / thin'}.")
    if stable and prec_ok:
        print("=> lock HIGH threshold near the mean; proceed to merge execution.")
    else:
        print("=> band is fragile on 70 positives: mine more dup_candidates and re-label "
              "before trusting auto-merge (build_duplicate_candidates.py).")

    table.to_csv(out / "kfold_summary.csv", index=False)
    (out / "kfold_verdict.json").write_text(json.dumps(
        {"stable": bool(stable), "precision_ok": bool(prec_ok), **hub}, indent=2, default=str))
    print(f"\n[saved] {out}/kfold_summary.csv, kfold_folds_*.csv, kfold_verdict.json")


if __name__ == "__main__":
    main()