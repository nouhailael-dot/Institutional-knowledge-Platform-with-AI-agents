"""
run_description_eval.py — re-evaluate all ER models with descriptions + metadata.

Implements Phases 2–8 of the revised roadmap in one harness:
  * tfidf_name        — name-only reference, recomputed here so every model in the
                        table is measured under identical conditions (this number
                        will differ slightly from the historical 0.694, which used
                        the original baseline's vectorizer config).
  * tfidf_name_desc   — weighted blend w*sim(name) + (1-w)*sim(description);
                        w is tuned on TRAIN, name stays dominant (w >= 0.5).
  * sbert_name        — all-MiniLM-L6-v2 on the raw name.
  * sbert_doc         — all-MiniLM-L6-v2 on the combined structured document
                        (Name / Description / Location / Hub).
  * combiner          — logistic regression over TF-IDF sims + SBERT sims +
                        lexical blocking features, trained on TRAIN.

All thresholds (best-F1, auto-merge HIGH, review LOW) are selected on TRAIN
and reported on TEST. Selection metric = auto-merge coverage at precision
>= --min-precision (default 0.97), per the revised evaluation strategy.

Usage (from repo root):
  python -m src.ML.entity_resolution.run_description_eval \
      --actors data/exports/actors.csv \
      --gold data/processed/entity_resolution_gold.csv \
      --split data/processed/entity_resolution_split.csv \
      --out docs/ml/results/description_eval \
      --models tfidf_name,tfidf_name_desc,sbert_name,sbert_doc,combiner
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

# allow running both as a module and as a plain script
try:
    from ML.entity_resolution import er_common as ec
except ImportError:  # pragma: no cover
    sys.path.append(str(Path(__file__).resolve().parent))
    

NAME_WEIGHT_GRID = [0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95]


# ---------------------------------------------------------------------------
# Similarity computation
# ---------------------------------------------------------------------------
def _rowwise_cosine(A, B) -> np.ndarray:
    """Cosine between row i of A and row i of B (TF-IDF output is L2-normalized)."""
    return np.asarray(A.multiply(B).sum(axis=1)).ravel()


def tfidf_sims(texts_a: pd.Series, texts_b: pd.Series, corpus: list[str],
               analyzer: str, ngram_range: tuple[int, int]) -> np.ndarray:
    vec = TfidfVectorizer(analyzer=analyzer, ngram_range=ngram_range,
                          lowercase=True, min_df=1)
    vec.fit(corpus)
    return _rowwise_cosine(vec.transform(texts_a.tolist()), vec.transform(texts_b.tolist()))


def compute_tfidf_features(p: pd.DataFrame, actors: pd.DataFrame | None) -> pd.DataFrame:
    """Name similarity (char n-grams — robust to abbreviations/typos, close to the
    original baseline family) and description similarity (word n-grams)."""
    name_corpus = (actors["name"].tolist() if actors is not None
                   else pd.concat([p.name_a, p.name_b]).unique().tolist())
    desc_corpus = ([d for d in (actors["description"].tolist() if actors is not None
                                else pd.concat([p.description_a, p.description_b]).unique().tolist())
                    if str(d).strip()] or ["placeholder"])

    out = pd.DataFrame(index=p.index)
    out["tfidf_name_sim"] = tfidf_sims(p.name_a.map(ec.normalize_name),
                                       p.name_b.map(ec.normalize_name),
                                       [ec.normalize_name(x) for x in name_corpus],
                                       analyzer="char_wb", ngram_range=(3, 5))
    has_desc = (p.description_a.str.strip() != "") & (p.description_b.str.strip() != "")
    desc_sim = np.zeros(len(p))
    if has_desc.any():
        desc_sim[has_desc.values] = tfidf_sims(
            p.loc[has_desc, "description_a"], p.loc[has_desc, "description_b"],
            desc_corpus, analyzer="word", ngram_range=(1, 2))
    out["tfidf_desc_sim"] = desc_sim
    return out


def tune_name_weight(y_train: np.ndarray, name_sim: np.ndarray, desc_sim: np.ndarray,
                     min_precision: float) -> tuple[float, str]:
    """Pick w on TRAIN: maximize auto-merge coverage at precision>=min_p, tie-break F1.
    w >= 0.5 keeps the name the dominant lexical feature."""
    best = None
    for w in NAME_WEIGHT_GRID:
        s = w * name_sim + (1 - w) * desc_sim
        thr = ec.pick_automerge_threshold(y_train, s, min_precision)
        cov = 0.0
        if thr is not None:
            _, cov, _, _, _, _ = ec._prf(y_train, s, thr)
        f1_thr = ec.pick_best_f1_threshold(y_train, s)
        _, _, f1, _, _, _ = ec._prf(y_train, s, f1_thr)
        key = (cov, f1)
        if best is None or key > best[0]:
            best = (key, w)
    w = best[1]
    return w, f"name_weight={w} (train-tuned)"


def compute_sbert_features(p: pd.DataFrame, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
                           ) -> pd.DataFrame | None:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("[warn] sentence-transformers not installed — skipping SBERT models "
              "(pip install sentence-transformers)")
        return None
    model = SentenceTransformer(model_name)

    def sims(texts_a: pd.Series, texts_b: pd.Series) -> np.ndarray:
        uniq = pd.concat([texts_a, texts_b]).unique().tolist()
        emb = model.encode(uniq, normalize_embeddings=True, show_progress_bar=False,
                           batch_size=64)
        lut = {t: e for t, e in zip(uniq, emb)}
        return np.array([float(np.dot(lut[a], lut[b])) for a, b in zip(texts_a, texts_b)])

    out = pd.DataFrame(index=p.index)
    out["sbert_name_sim"] = sims(p.name_a, p.name_b)
    out["sbert_doc_sim"] = sims(p.doc_a, p.doc_b)
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--actors", default=None, help="data/exports/actors.csv (recommended)")
    ap.add_argument("--gold", required=True)
    ap.add_argument("--split", default=None)
    ap.add_argument("--out", default="docs/ml/results/description_eval")
    ap.add_argument("--models",
                    default="tfidf_name,tfidf_name_desc,sbert_name,sbert_doc,combiner")
    ap.add_argument("--min-precision", type=float, default=0.97)
    ap.add_argument("--low-zone-min-recall", type=float, default=0.98)
    args = ap.parse_args()

    ec.CONFIG["min_precision"] = args.min_precision
    ec.CONFIG["low_zone_min_recall"] = args.low_zone_min_recall
    wanted = [m.strip() for m in args.models.split(",") if m.strip()]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- load ----
    actors = ec.load_actors(args.actors) if args.actors else None
    if actors is not None:
        for col in ("description", "location", "hubs"):
            share = float((actors[col].str.strip() != "").mean())
            print(f"[actors] {col:<12} non-empty for {share:5.0%} of {len(actors)} actors")
    else:
        print("[warn] no --actors file: only name-based models are meaningful.")

    pairs = ec.load_gold(args.gold, args.split)
    pairs = ec.attach_actor_fields(pairs, actors)
    ec.coverage_report(pairs)
    tr, te = pairs["split"] == "train", pairs["split"] == "test"
    y = pairs["label"].to_numpy()
    y_tr, y_te = y[tr.values], y[te.values]
    print(f"[data] {int(tr.sum())} train / {int(te.sum())} test pairs "
          f"({y_tr.mean():.0%} / {y_te.mean():.0%} positive)")

    # ---- features ----
    feats = compute_tfidf_features(pairs, actors)
    sbert = compute_sbert_features(pairs) if any(m.startswith("sbert") or m == "combiner"
                                                 for m in wanted) else None
    if sbert is not None:
        feats = pd.concat([feats, sbert], axis=1)
    lex = ec.lexical_features(pairs)
    feats = pd.concat([feats, lex], axis=1)

    # ---- model scores ----
    scores: dict[str, np.ndarray] = {}
    notes: dict[str, str] = {}
    if "tfidf_name" in wanted:
        scores["tfidf_name"] = feats["tfidf_name_sim"].to_numpy()
    if "tfidf_name_desc" in wanted:
        w, note = tune_name_weight(y_tr, feats["tfidf_name_sim"].to_numpy()[tr.values],
                                   feats["tfidf_desc_sim"].to_numpy()[tr.values],
                                   args.min_precision)
        scores["tfidf_name_desc"] = (w * feats["tfidf_name_sim"]
                                     + (1 - w) * feats["tfidf_desc_sim"]).to_numpy()
        notes["tfidf_name_desc"] = note
    if sbert is not None and "sbert_name" in wanted:
        scores["sbert_name"] = feats["sbert_name_sim"].to_numpy()
    if sbert is not None and "sbert_doc" in wanted:
        scores["sbert_doc"] = feats["sbert_doc_sim"].to_numpy()
    if "combiner" in wanted:
        feat_cols = [c for c in ["tfidf_name_sim", "tfidf_desc_sim", "sbert_name_sim",
                                 "sbert_doc_sim", "acronym_match", "containment", "jaccard",
                                 "length_ratio", "location_match", "hub_overlap",
                                 "both_have_desc"] if c in feats.columns]
        X = feats[feat_cols].to_numpy(dtype=float)
        clf = make_pipeline(StandardScaler(),
                            LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0))
        clf.fit(X[tr.values], y_tr)
        scores["combiner"] = clf.predict_proba(X)[:, 1]
        lr = clf.named_steps["logisticregression"]
        coefs = sorted(zip(feat_cols, lr.coef_[0]), key=lambda x: -abs(x[1]))
        notes["combiner"] = "top features: " + ", ".join(f"{n}={c:+.2f}" for n, c in coefs[:5])
        print("[combiner] learned feature weights (standardized):")
        for n, c in coefs:
            print(f"           {n:<16} {c:+.3f}")

    # ---- evaluate ----
    reports = []
    for name, s in scores.items():
        rep = ec.evaluate_model(name, y_tr, s[tr.values], y_te, s[te.values])
        if name in notes:
            rep.notes = (rep.notes + " | " if rep.notes else "") + notes[name]
        reports.append(rep)
        ec.save_pr_curve(y_te, s[te.values], out_dir / f"pr_curve_test_{name}.csv")

    table = ec.reports_to_frame(reports)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 50)
    print("\n================ MODEL COMPARISON (all metrics on TEST, thresholds from TRAIN) ================")
    print(table.round(3).to_string(index=False))
    print(f"\nSelection metric: automerge_coverage at precision >= {args.min_precision} "
          "(NOT f1). review_share = fraction of test pairs a human must look at.")

    # ---- persist ----
    table.to_csv(out_dir / "results_summary.csv", index=False)
    wide = pairs[["key_a", "key_b", "label", "split"]].copy()
    for name, s in scores.items():
        wide[f"score_{name}"] = s
    wide = pd.concat([wide, feats], axis=1)
    wide.to_csv(out_dir / "pair_scores.csv", index=False)
    thresholds = {r.model: {"high_auto_merge": r.automerge_threshold,
                            "low_different": r.low_threshold,
                            "best_f1": r.f1_threshold} for r in reports}
    (out_dir / "thresholds.json").write_text(json.dumps(thresholds, indent=2))
    print(f"\n[saved] {out_dir}/results_summary.csv, pair_scores.csv, thresholds.json, pr_curve_test_*.csv")


if __name__ == "__main__":
    main()
