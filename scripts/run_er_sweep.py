"""
run_er_sweep.py — the ER router: sweep all canonical actors for duplicates.

This is the piece that finds duplicates NOBODY has labeled. The gold set covers
586 pairs; this scores every plausible pair among the ~899 canonical actors with
the frozen production combiner and routes each one by the three decision zones:

    score >= high_threshold          -> AUTO MERGE   (irreversible-ish, but logged)
    low_threshold <= score < high    -> REVIEW QUEUE (a human decides)
    score <  low_threshold           -> DISCARD      (treated as different)

Candidate generation (so we score ~thousands of pairs, not 400k):
  * TF-IDF char n-gram cosine over names, keep pairs above --cand-threshold
  * plus lexical blocking: acronym match, token containment, Jaccard overlap
    (these catch NREL <-> National Renewable Energy Laboratory, which cosine misses)

Pairs already labeled in the gold set are skipped, and merged-away actors are
excluded, so the sweep only surfaces genuinely new work.

DRY RUN BY DEFAULT. --apply writes review rows and (with --auto-merge) executes
the high-confidence merges.

    python scripts/run_er_sweep.py --actors data/exports/actors.csv \
        --gold data/processed/entity_resolution_gold.csv
    python scripts/run_er_sweep.py --actors ... --gold ... --apply
    python scripts/run_er_sweep.py --actors ... --gold ... --apply --auto-merge
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from itertools import combinations
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.db.session import SessionLocal
try:
    from src.ML.entity_resolution import er_common as ec
    from actor_merge import merge_actors
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parent))
    import er_common as ec
    from actor_merge import merge_actors
try:
    from src.ML.entity_resolution.er_mismatch_features import mismatch_features
except ImportError:
    from src.ML.entity_resolution.er_mismatch_features import mismatch_features
try:
    from src.ML.entity_resolution.er_description_features import description_features
except ImportError:
    from src.ML.entity_resolution.er_description_features import description_features


def load_bundle(path):
    b = joblib.load(path)
    if not isinstance(b, dict) or "model" not in b:
        raise SystemExit(f"{path} is not a model bundle from train_production_combiner.py")
    return b


def candidate_pairs(actors, vec, cand_threshold, max_per_actor):
    """TF-IDF neighbours + lexical blocking. Returns {(i, j)} with i < j."""
    names = actors["name"].map(ec.normalize_name).tolist()
    X = vec.transform(names)
    S = (X @ X.T).toarray()
    np.fill_diagonal(S, 0.0)

    pairs = set()
    for i in range(len(names)):
        idx = np.argsort(-S[i])[:max_per_actor]
        for j in idx:
            if S[i, j] >= cand_threshold:
                pairs.add((min(i, int(j)), max(i, int(j))))

    # lexical blocking — catches acronym/containment pairs cosine ranks low
    toks = [ec.tokens(n) for n in actors["name"]]
    acro = [ec.normalize_name(n).replace(" ", "") for n in actors["name"]]
    for i, j in combinations(range(len(names)), 2):
        if (i, j) in pairs:
            continue
        ti, tj = toks[i], toks[j]
        if not ti or not tj:
            continue
        if ec.acronym_match(actors["name"].iat[i], actors["name"].iat[j]):
            pairs.add((i, j)); continue
        inter = len(ti & tj)
        if inter and inter / min(len(ti), len(tj)) >= 0.85:      # containment
            pairs.add((i, j)); continue
        if inter and inter / len(ti | tj) >= 0.6:                # jaccard
            pairs.add((i, j))
    return sorted(pairs)


def build_features(actors, pairs, bundle):
    """Recreate the EXACT feature set the production model was trained on."""
    ia = [p[0] for p in pairs]; ib = [p[1] for p in pairs]
    df = pd.DataFrame({
        "name_a": actors["name"].iloc[ia].values,
        "name_b": actors["name"].iloc[ib].values,
        "hubs_a": actors["hubs"].iloc[ia].values,
        "hubs_b": actors["hubs"].iloc[ib].values,
        "desc_a": actors["description"].iloc[ia].values,
        "desc_b": actors["description"].iloc[ib].values,
    })
    vec = bundle["tfidf_vectorizer"]
    A = vec.transform(df.name_a.map(ec.normalize_name))
    B = vec.transform(df.name_b.map(ec.normalize_name))
    tfidf = np.asarray(A.multiply(B).sum(axis=1)).ravel()

    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(bundle["sbert_model_name"])
    uniq = pd.concat([df.name_a, df.name_b]).unique().tolist()
    emb = model.encode(uniq, normalize_embeddings=True, batch_size=64, show_progress_bar=False)
    lut = {t: e for t, e in zip(uniq, emb)}
    sbert = np.array([float(np.dot(lut[a], lut[b])) for a, b in zip(df.name_a, df.name_b)])

    feats = pd.DataFrame({"tfidf_name_sim": tfidf, "sbert_name_sim": sbert})
    feats = pd.concat([feats, ec.name_features(df), ec.hub_feature(df),
                       mismatch_features(df), description_features(df)], axis=1)
    missing = [c for c in bundle["features"] if c not in feats.columns]
    if missing:
        raise SystemExit(f"feature mismatch: bundle expects {missing} which were not built")
    return df, feats[bundle["features"]]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--actors", default="data/exports/actors.csv")
    ap.add_argument("--gold", default="data/processed/entity_resolution_gold.csv")
    ap.add_argument("--bundle", default="models/er_combiner_v1.joblib")
    ap.add_argument("--config", default="config/er_production.json")
    ap.add_argument("--cand-threshold", type=float, default=0.35)
    ap.add_argument("--max-per-actor", type=int, default=25)
    ap.add_argument("--apply", action="store_true", help="write review_queue rows")
    ap.add_argument("--auto-merge", action="store_true",
                    help="also execute merges above high_threshold (requires --apply)")
    ap.add_argument("--out", default="docs/ml/results/sweep")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    cfg = json.loads(Path(args.config).read_text())
    bundle = load_bundle(args.bundle)
    HIGH = float(cfg["high_threshold"]); LOW = float(cfg["low_threshold"])
    print(f"[config] model={cfg['model']}  HIGH={HIGH}  LOW={LOW}")

    actors = ec.load_actors(args.actors).reset_index(drop=True)
    print(f"[data] {len(actors)} canonical actors")

    pairs = candidate_pairs(actors, bundle["tfidf_vectorizer"],
                            args.cand_threshold, args.max_per_actor)
    print(f"[candidates] {len(pairs)} pairs generated "
          f"(of {len(actors)*(len(actors)-1)//2} possible)")

    # drop pairs already labeled in the gold set
    known = set()
    if Path(args.gold).exists():
        g = pd.read_csv(args.gold, dtype=str).fillna("")
        for _, r in g.iterrows():
            known.add(frozenset((r.get("actor_id_a", ""), r.get("actor_id_b", ""))))
    ids = actors["actor_id"].tolist()
    pairs = [(i, j) for i, j in pairs if frozenset((ids[i], ids[j])) not in known]
    print(f"[candidates] {len(pairs)} after removing already-labeled pairs")
    if not pairs:
        print("nothing to do."); return

    df, X = build_features(actors, pairs, bundle)
    scores = bundle["model"].predict_proba(X.to_numpy(float))[:, 1]

    df["actor_id_a"] = [ids[i] for i, _ in pairs]
    df["actor_id_b"] = [ids[j] for _, j in pairs]
    df["score"] = scores
    df["zone"] = np.where(scores >= HIGH, "auto_merge",
                  np.where(scores >= LOW, "review", "discard"))
    df = df.sort_values("score", ascending=False).reset_index(drop=True)

    counts = df["zone"].value_counts().to_dict()
    print(f"\n[zones] {counts}")
    print(f"[zones] review load: {counts.get('review',0)} pairs "
          f"({counts.get('review',0)/max(len(df),1):.0%} of candidates)")

    df.to_csv(out / "sweep_scores.csv", index=False)
    top = df[df.zone == "auto_merge"]
    print(f"\n--- AUTO-MERGE candidates ({len(top)}) ---")
    for _, r in top.head(25).iterrows():
        print(f"   {r['score']:.3f}  {r['name_a'][:44]:<46} || {r['name_b'][:44]}")
    rev = df[df.zone == "review"]
    print(f"\n--- top REVIEW pairs ({len(rev)} total) ---")
    for _, r in rev.head(15).iterrows():
        print(f"   {r['score']:.3f}  {r['name_a'][:44]:<46} || {r['name_b'][:44]}")

    if not args.apply:
        print(f"\nDRY RUN — nothing written. Scores saved to {out}/sweep_scores.csv")
        print("Re-run with --apply to populate review_queue "
              "(add --auto-merge to also execute the high-confidence merges).")
        return

    s = SessionLocal(); conn = s.connection()
    inserted = 0
    for _, r in rev.iterrows():
        a, b = sorted([r["actor_id_a"], r["actor_id_b"]])
        conn.execute(text(
            "INSERT INTO review_queue (review_id, actor_id_a, actor_id_b, score, model, "
            "features, status) VALUES (CAST(:rid AS uuid), CAST(:a AS uuid), CAST(:b AS uuid), "
            ":s, :m, :f, 'pending') ON CONFLICT ON CONSTRAINT uq_review_pair DO NOTHING"),
            {"rid": str(uuid.uuid4()), "a": a, "b": b, "s": float(r["score"]),
             "m": cfg["model"],
             "f": json.dumps({k: float(X.iloc[r.name][k]) for k in bundle["features"]})})
        inserted += 1
    s.commit(); s.close()
    print(f"\n[applied] {inserted} pair(s) queued for review")

    if args.auto_merge and len(top):
        print(f"[auto-merge] executing {len(top)} merge(s) ...")
        done = failed = 0
        for _, r in top.iterrows():
            # keep the more complete record: more hubs, then longer name
            a, b = r["actor_id_a"], r["actor_id_b"]
            na, nb = r["name_a"], r["name_b"]
            winner, loser = (a, b) if len(str(r["hubs_a"])) >= len(str(r["hubs_b"])) else (b, a)
            if winner == a and len(nb) > len(na) and str(r["hubs_a"]) == str(r["hubs_b"]):
                winner, loser = b, a
            try:
                merge_actors(SessionLocal, winner, loser, score=float(r["score"]),
                             method="auto", decided_by="er_sweep")
                done += 1
            except Exception as e:
                failed += 1
                print(f"   FAILED {na[:40]} / {nb[:40]}: {type(e).__name__}: {e}")
        print(f"[auto-merge] {done} merged, {failed} failed")
    elif len(top):
        print(f"[auto-merge] {len(top)} pair(s) above HIGH were NOT merged "
              f"(pass --auto-merge to execute)")


if __name__ == "__main__":
    main()