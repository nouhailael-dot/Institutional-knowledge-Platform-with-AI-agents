#!/usr/bin/env python3
"""
src/ml/entity_resolution/embedding_models.py  —  Week 3 of the Phase 4 ER plan.

Evaluate one or more sentence-embedding models for entity resolution on the
SAME held-out split as the TF-IDF baseline, so every F1 is directly comparable.

Why this version:
- Embeds per ACTOR, not per pair. Each actor's document (name + description +
  location + hubs) is embedded once; pair cosine is a vectorized dot product.
- The optional embedding dump is keyed by actor_id, so it loads straight into
  the planned `actor.embedding vector(384)` column for RAG (no re-embedding).
- Runs several models in one invocation (--model a b c) -> one comparison table.
- Degrades cleanly: no --actors export -> scores on names; missing optional
  columns are ignored; single-class guards everywhere.

Usage
-----
    pip install pandas numpy scikit-learn sentence-transformers
    python src/ml/entity_resolution/embedding_models.py \
        --gold   data/processed/entity_resolution_gold.csv \
        --split-file data/processed/entity_resolution_split.csv \
        --actors data/exports/actors.csv \
        --model  all-MiniLM-L6-v2 all-mpnet-base-v2 \
        --baseline-f1 0.694 \
        --results-out docs/ml/entity_resolution_results.md \
        --dump-embeddings data/processed/actor_embeddings.npz
"""
import argparse, os, json, sys
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import precision_recall_curve, average_precision_score


# --------------------------------------------------------------- data
def load_gold(path):
    if not os.path.exists(path):
        sys.exit(f"gold file not found: {path}")
    g = pd.read_csv(path); g.columns = [c.strip() for c in g.columns]
    for c in ("name_a", "name_b", "label"):
        if c not in g.columns:
            sys.exit(f"{path}: missing required column '{c}'")
    g["label"] = g["label"].astype(str).str.strip().str.lower()
    g = g[g["label"].isin(["same", "different"])].copy().reset_index(drop=True)
    g["y"] = (g["label"] == "same").astype(int)
    if "source_batch" not in g.columns:
        g["source_batch"] = "all"
    return g


def load_actor_docs(actors_path):
    """actor_id -> document string. Returns ({}, False) if no usable export."""
    if not actors_path:
        return {}, False
    if not os.path.exists(actors_path):
        print(f"note: {actors_path} not found; scoring on names only.")
        return {}, False
    a = pd.read_csv(actors_path); a.columns = [c.strip() for c in a.columns]
    if "actor_id" not in a.columns or "name" not in a.columns:
        print(f"note: {actors_path} lacks actor_id/name; scoring on names only.")
        return {}, False
    extra = [c for c in ("description", "location", "hubs") if c in a.columns]
    a["__doc"] = a[["name"] + extra].fillna("").astype(str).agg(" ".join, axis=1).str.strip()
    return dict(zip(a["actor_id"].astype(str), a["__doc"])), bool(extra)


def entity_key_doc(actor_id, name, doc_map):
    """Key by actor_id when the export has it; otherwise key by name."""
    aid = None if actor_id is None else str(actor_id)
    if aid and aid != "nan" and aid in doc_map:
        return aid, doc_map[aid]
    return "name::" + str(name), str(name)


def build_entities(g, doc_map):
    keys_a, keys_b, docs = [], [], {}
    has_ids = {"actor_id_a", "actor_id_b"} <= set(g.columns)
    for r in g.itertuples(index=False):
        aid_a = getattr(r, "actor_id_a", None) if has_ids else None
        aid_b = getattr(r, "actor_id_b", None) if has_ids else None
        ka, da = entity_key_doc(aid_a, r.name_a, doc_map)
        kb, db = entity_key_doc(aid_b, r.name_b, doc_map)
        keys_a.append(ka); keys_b.append(kb); docs[ka] = da; docs[kb] = db
    return keys_a, keys_b, docs


def get_split(g, split_file, test_size, seed):
    if split_file and os.path.exists(split_file):
        s = pd.read_csv(split_file); m = dict(zip(s["pair_id"].astype(str), s["split"]))
        g["split"] = g["pair_id"].astype(str).map(m)
        if g["split"].isna().any():
            sys.exit("split file does not cover all gold pairs; delete it to regenerate.")
        return g
    strat = g["label"] + "|" + g["source_batch"].astype(str)
    tr, te = train_test_split(g.index, test_size=test_size, random_state=seed, stratify=strat)
    g["split"] = "train"; g.loc[te, "split"] = "test"
    if split_file:
        os.makedirs(os.path.dirname(split_file) or ".", exist_ok=True)
        g[["pair_id", "split"]].to_csv(split_file, index=False)
    return g


# embedding
def encode_documents(model_name, docs):
    """docs: {entity_key: text} -> ({entity_key: vector}, dim)."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        sys.exit("sentence-transformers not installed. Run: pip install sentence-transformers")
    try:
        model = SentenceTransformer(model_name)
    except Exception as e:
        sys.exit(f"could not load model '{model_name}': {e}")
    keys = list(docs)
    emb = model.encode([docs[k] for k in keys], normalize_embeddings=True,
                       batch_size=64, show_progress_bar=True)
    emb = np.asarray(emb, dtype="float32")
    return {k: emb[i] for i, k in enumerate(keys)}, emb.shape[1]


def pair_cosines(keys_a, keys_b, vecs):
    A = np.vstack([vecs[k] for k in keys_a])
    B = np.vstack([vecs[k] for k in keys_b])
    return np.einsum("ij,ij->i", A, B)   # L2-normalized vectors -> dot == cosine


# metrics
def tune_threshold(scores, y):
    if len(set(y)) < 2:
        return 0.5
    p, r, t = precision_recall_curve(y, scores)
    f1 = np.divide(2 * p * r, p + r, out=np.zeros_like(p), where=(p + r) > 0)
    return float(t[int(np.nanargmax(f1[:-1]))]) if len(t) else 0.5


def evaluate(scores, y, thr):
    pred = (scores >= thr).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum()); fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum()); tn = int(((pred == 0) & (y == 0)).sum())
    P = tp / (tp + fp) if tp + fp else 0.0
    R = tp / (tp + fn) if tp + fn else 0.0
    F = 2 * P * R / (P + R) if P + R else 0.0
    AP = float(average_precision_score(y, scores)) if len(set(y)) > 1 else float("nan")
    return dict(threshold=thr, precision=P, recall=R, f1=F, average_precision=AP,
                tp=tp, fp=fp, fn=fn, tn=tn)


def precision_target(scores, y, target):
    if len(set(y)) < 2:
        return None
    p, r, t = precision_recall_curve(y, scores)
    ok = np.where(p[:-1] >= target)[0]
    if not len(ok):
        return None
    i = ok[np.argmax(r[:-1][ok])]
    return dict(threshold=float(t[i]), precision=float(p[i]), recall=float(r[i]))


def confusion(m):
    return (f"        pred_same  pred_diff\n"
            f"  same   {m['tp']:>6}     {m['fn']:>6}\n"
            f"  diff   {m['fp']:>6}     {m['tn']:>6}")


# --------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="data/processed/entity_resolution_gold.csv")
    ap.add_argument("--split-file", default="data/processed/entity_resolution_split.csv")
    ap.add_argument("--actors", default=None)
    ap.add_argument("--model", nargs="+", default=["all-MiniLM-L6-v2"],
                    help="one or more SentenceTransformer model names")
    ap.add_argument("--test-size", type=float, default=0.30)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--precision-target", type=float, default=0.97)
    ap.add_argument("--baseline-f1", type=float, default=None)
    ap.add_argument("--results-out", default=None)
    ap.add_argument("--dump-embeddings", default=None,
                    help=".npz path; saves actor_id-keyed vectors for the FIRST model")
    args = ap.parse_args()

    g = load_gold(args.gold)
    doc_map, used_desc = load_actor_docs(args.actors)
    keys_a, keys_b, docs = build_entities(g, doc_map)
    g = get_split(g, args.split_file, args.test_size, args.seed)
    tr = (g.split == "train").values
    te = (g.split == "test").values
    ytr, yte = g["y"].values[tr], g["y"].values[te]

    print(f"gold {len(g)} pairs (same={int(g.y.sum())}, different={int((1-g.y).sum())}) | "
          f"{tr.sum()} train / {te.sum()} test | {len(docs)} unique entities | "
          f"docs: {'name + description/location/hubs' if used_desc else 'name only'}")

    results = {}
    for mi, model_name in enumerate(args.model):
        print(f"\nencoding with '{model_name}' ...")
        vecs, dim = encode_documents(model_name, docs)
        scores = pair_cosines(keys_a, keys_b, vecs)
        thr = tune_threshold(scores[tr], ytr)
        results[model_name] = dict(test=evaluate(scores[te], yte, thr), dim=dim, scores=scores)
        if mi == 0 and args.dump_embeddings:
            ids = [k for k in docs if not k.startswith("name::")]
            if ids:
                os.makedirs(os.path.dirname(args.dump_embeddings) or ".", exist_ok=True)
                mat = np.vstack([vecs[k] for k in ids])
                np.savez_compressed(args.dump_embeddings,
                                    actor_id=np.array(ids, dtype=object), embedding=mat)
                csv_path = os.path.splitext(args.dump_embeddings)[0] + ".csv"
                pd.DataFrame({"actor_id": ids,
                              "embedding": [json.dumps(v.tolist()) for v in mat]}
                             ).to_csv(csv_path, index=False)
                print(f"dumped {len(ids)} actor_id-keyed embeddings (dim {dim}) -> "
                      f"{args.dump_embeddings} and {csv_path}")
            else:
                print("note: names-only run (no actor_ids); skipped embedding dump.")

    print("\n" + "=" * 70)
    print("SENTENCE-BERT — entity resolution, held-out TEST metrics")
    print("=" * 70)
    print(f"{'model':<26}{'dim':>5}{'F1':>8}{'P':>8}{'R':>8}{'AP':>8}{'thr':>8}")
    for name in sorted(results, key=lambda n: -results[n]["test"]["f1"]):
        m = results[name]["test"]
        print(f"{name:<26}{results[name]['dim']:>5}{m['f1']:>8.3f}{m['precision']:>8.3f}"
              f"{m['recall']:>8.3f}{m['average_precision']:>8.3f}{m['threshold']:>8.3f}")

    best = max(results, key=lambda n: results[n]["test"]["f1"])
    bm = results[best]["test"]
    print(f"\nbest by F1: {best}")
    print(confusion(bm))
    if args.baseline_f1 is not None:
        d = bm["f1"] - args.baseline_f1
        verdict = "beats" if d > 0.01 else ("ties" if abs(d) <= 0.01 else "loses to")
        print(f"\nvs TF-IDF baseline (F1={args.baseline_f1:.3f}): {bm['f1']:.3f} "
              f"({d:+.3f}) -> {verdict} the baseline.")
    pt = precision_target(results[best]["scores"][te], yte, args.precision_target)
    if pt:
        print(f"auto-merge @ precision>={args.precision_target}: thr={pt['threshold']:.3f} "
              f"recall={pt['recall']:.3f}  (pairs below -> Claude/human review)")
    else:
        print(f"no threshold reaches precision {args.precision_target} on test for {best}.")

    if args.results_out:
        os.makedirs(os.path.dirname(args.results_out) or ".", exist_ok=True)
        with open(args.results_out, "a") as f:
            f.write("\n## Sentence-BERT comparison (Week 3)\n\n")
            f.write(f"- Documents: {'name + description/location/hubs' if used_desc else 'name only'}\n")
            f.write(f"- Held-out test: {int(te.sum())} pairs (same={int(yte.sum())})\n\n")
            f.write("| model | dim | F1 | P | R | AP | thr |\n|---|---|---|---|---|---|---|\n")
            for name in sorted(results, key=lambda n: -results[n]["test"]["f1"]):
                m = results[name]["test"]
                f.write(f"| {name} | {results[name]['dim']} | {m['f1']:.3f} | "
                        f"{m['precision']:.3f} | {m['recall']:.3f} | "
                        f"{m['average_precision']:.3f} | {m['threshold']:.3f} |\n")
            f.write(f"\nBest: **{best}** (F1={bm['f1']:.3f}). "
                    f"Method tag for `actor_merge_log.merge_method`: `sbert`.\n")
        print(f"\nappended results to {args.results_out}")


if __name__ == "__main__":
    main()