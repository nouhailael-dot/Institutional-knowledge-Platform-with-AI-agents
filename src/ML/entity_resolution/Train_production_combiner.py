"""
train_production_combiner.py — freeze the validated ER model for production.

What it does (and why):
  Your eval/k-fold scripts train the combiner, print metrics, then discard it.
  This script trains the SAME winning model (combiner_name_hub) ONCE on ALL
  labeled pairs and SAVES it to disk, so production scores new actor pairs with
  the exact model your k-fold validated — no retraining, no drift.

Outputs:
  models/er_combiner_v1.joblib   — the trained model (load with joblib.load)
  config/er_production.json       — frozen thresholds + provenance

Run (repo root, venv active):
  python scripts/train_production_combiner.py \
      --actors data/exports/actors.csv \
      --gold   data/processed/entity_resolution_gold.csv
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from datetime import date

import numpy as np
import pandas as pd
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

# reuse the shared module (same folder or importable)
try:
    from . import er_common as ec
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parent))
    import er_common as ec

# feature order is FROZEN here — production must build features in this exact order
FEATURES = ["tfidf_name_sim", "sbert_name_sim", "acronym_match",
            "containment", "jaccard", "length_ratio", "hub_overlap"]
HIGH_THRESHOLD = 0.945   # from k-fold (fold-mean 0.943, rounded up for margin)


def load_gold(path):
    g = pd.read_csv(path, dtype=str).fillna("")
    g.columns = [c.strip() for c in g.columns]
    lab = g["label"].str.strip().str.lower()
    g = g[lab.isin(ec._POSITIVE | ec._NEGATIVE)].copy()
    g["y"] = g["label"].str.strip().str.lower().isin(ec._POSITIVE).astype(int)
    for c in ("actor_id_a", "actor_id_b"):
        if c not in g.columns:
            g[c] = ""
    return g.reset_index(drop=True)


def tfidf_name_sim(pairs, actors):
    corpus = actors["name"].map(ec.normalize_name).tolist()
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True,
                          min_df=1, lowercase=True).fit(corpus)
    A = vec.transform(pairs.name_a.map(ec.normalize_name))
    B = vec.transform(pairs.name_b.map(ec.normalize_name))
    return np.asarray(A.multiply(B).sum(axis=1)).ravel(), vec


def sbert_name_sim(pairs, model_name="sentence-transformers/all-MiniLM-L6-v2"):
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(model_name)
    uniq = pd.concat([pairs.name_a, pairs.name_b]).unique().tolist()
    emb = model.encode(uniq, normalize_embeddings=True, batch_size=64, show_progress_bar=False)
    lut = {t: e for t, e in zip(uniq, emb)}
    return np.array([float(np.dot(lut[a], lut[b])) for a, b in zip(pairs.name_a, pairs.name_b)])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--actors", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--low-threshold", type=float, default=None,
                    help="LOW zone cutoff from your three-zone eval (thresholds.json)")
    ap.add_argument("--model-out", default="models/er_combiner_v1.joblib")
    ap.add_argument("--config-out", default="config/er_production.json")
    args = ap.parse_args()

    actors = ec.load_actors(args.actors)
    g = load_gold(args.gold)
    g = ec.attach_hubs(g, actors)
    y = g["y"].to_numpy()
    print(f"[data] training on ALL {len(g)} labeled pairs ({int(y.sum())} positives)")

    # build the 7 features in the frozen order
    tfidf, tfidf_vec = tfidf_name_sim(g, actors)
    sbert = sbert_name_sim(g)
    feats = pd.DataFrame({"tfidf_name_sim": tfidf, "sbert_name_sim": sbert}, index=g.index)
    feats = pd.concat([feats, ec.name_features(g), ec.hub_feature(g)], axis=1)
    X = feats[FEATURES].to_numpy(float)

    clf = make_pipeline(StandardScaler(),
                        LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0))
    clf.fit(X, y)
    print("[train] fitted combiner_name_hub on all labels")

    # bundle everything production needs to reproduce features + score
    bundle = {"model": clf, "features": FEATURES, "tfidf_vectorizer": tfidf_vec,
              "sbert_model_name": "sentence-transformers/all-MiniLM-L6-v2",
              "high_threshold": HIGH_THRESHOLD, "low_threshold": args.low_threshold}
    Path(args.model_out).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, args.model_out)
    print(f"[saved] model bundle -> {args.model_out}")

    cfg = {
        "model": "combiner_name_hub",
        "model_file": args.model_out,
        "features": FEATURES,
        "high_threshold": HIGH_THRESHOLD,
        "low_threshold": 0.45981815523962793,
        "min_precision": 0.97,
        "validated_on": {"pairs": int(len(g)), "positives": int(y.sum()),
                         "pooled_precision": 1.0, "coverage": 0.085},
        "frozen_date": date.today().isoformat(),
        "notes": ("Auto-merge approved for the high-confidence tail only. Do NOT lower "
                  "high_threshold to chase coverage without re-running k-fold. Hubs are IN "
                  "the auto-merge decision (validated at 117 positives)."),
    }
    Path(args.config_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.config_out).write_text(json.dumps(cfg, indent=2))
    print(f"[saved] frozen config -> {args.config_out}")
    print("\nTo score new pairs later:  bundle = joblib.load('%s')" % args.model_out)


if __name__ == "__main__":
    main()