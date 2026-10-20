#!/usr/bin/env python3
"""
src/ml/entity_resolution/baseline_tfidf.py  —  Week 2 of the Phase 4 ER plan.

The TF-IDF baseline: the number every later model (sentence-BERT, the
fine-tuned domain embedding, hybrid+rerank) has to beat.

What it does
------------
1. Loads the hand-labeled gold set (data/processed/entity_resolution_gold.csv).
2. Builds a TF-IDF vectorizer over each actor's "document" (name + description
   + location + hub context if an actors export is given; name only otherwise).
3. Scores every gold pair by cosine similarity of the two documents.
4. Creates ONE held-out test split (stratified by label + source_batch) and
   saves it, so sentence-BERT / hybrid evaluate on the SAME test set later.
5. Tunes the decision threshold on the TRAIN split (max F1), then reports
   precision / recall / F1 / confusion matrix / average precision on the
   untouched TEST split.

Usage
-----
    pip install pandas numpy scikit-learn
    python src/ml/entity_resolution/baseline_tfidf.py \
        --gold   data/processed/entity_resolution_gold.csv \
        --actors data/exports/actors.csv \
        --results-out docs/ml/entity_resolution_baseline.md

The threshold-tuning and metric helpers are kept here for a self-contained
baseline; they can later move to src/ml/common/metrics.py and
src/ml/entity_resolution/evaluator.py for reuse by the other models.
"""

"""
PATCH for baseline_tfidf.py — fixes #1 (name-join fallback) and #2 (name not
swamped by description). Drop these two functions in to REPLACE the existing
`build_docs` and `tfidf_cosine`, and make the two edits in main() marked below.

Everything else in your file (load_gold, get_split, tune_threshold, evaluate,
precision_target, fmt, report writing) stays exactly as-is.
"""

import argparse, json, os
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import train_test_split
from sklearn.metrics import precision_recall_curve, average_precision_score


# ---------------------------------------------------------------- data
def load_gold(path):
    g = pd.read_csv(path)
    g.columns = [c.strip() for c in g.columns]
    for c in ("name_a", "name_b", "label"):
        if c not in g.columns:
            raise SystemExit(f"{path}: missing required column '{c}'")
    g["label"] = g["label"].astype(str).str.strip().str.lower()
    g = g[g["label"].isin(["same", "different"])].copy().reset_index(drop=True)
    g["y"] = (g["label"] == "same").astype(int)
    if "source_batch" not in g.columns:
        g["source_batch"] = "all"
    return g


def _norm(s):
    import re, unicodedata
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9\s]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def build_docs(g, actors_path):
    """Return (name_a, name_b, desc_a, desc_b, used_desc).

    desc_* fold description + location + hubs into one context string (empty if
    unavailable). Actor fields are joined by actor_id when the gold has id
    columns, otherwise by normalized name — so descriptions attach in BOTH cases.
    """
    name_a = g["name_a"].astype(str)
    name_b = g["name_b"].astype(str)
    empty = pd.Series([""] * len(g), index=g.index)
    if not actors_path:
        return name_a, name_b, empty, empty, False

    a = pd.read_csv(actors_path)
    a.columns = [c.strip() for c in a.columns]
    ctx_cols = [c for c in ("description", "location", "hubs") if c in a.columns]
    if not ctx_cols:
        return name_a, name_b, empty, empty, False
    a["__ctx"] = a[ctx_cols].fillna("").astype(str).agg(" ".join, axis=1).str.strip()

    have_ids = {"actor_id_a", "actor_id_b"} <= set(g.columns) and "actor_id" in a.columns
    if have_ids:
        # prefer id-join, but check it actually hits; else fall back to name
        by_id = dict(zip(a["actor_id"].astype(str), a["__ctx"]))
        hit = g["actor_id_a"].astype(str).isin(by_id).mean()
        if hit >= 0.5:
            da = g["actor_id_a"].astype(str).map(by_id).fillna("")
            db = g["actor_id_b"].astype(str).map(by_id).fillna("")
            print(f"[join] attached context by actor_id ({hit:.0%} hit)")
            return name_a, name_b, da, db, True

    # NAME-JOIN fallback (the fix): match on normalized name
    by_name = dict(zip(a["name"].map(_norm), a["__ctx"]))
    da = name_a.map(lambda n: by_name.get(_norm(n), ""))
    db = name_b.map(lambda n: by_name.get(_norm(n), ""))
    hit = ((da != "") | (db != "")).mean()
    print(f"[join] attached context by NAME ({hit:.0%} of pairs matched an actor)")
    return name_a, name_b, da, db, True




# -------------------------------------------------------- train/test split
def get_split(g, split_file, test_size, seed):
    """Reuse a saved split if present; otherwise create + persist a stratified one."""
    if split_file and os.path.exists(split_file):
        s = pd.read_csv(split_file)
        m = dict(zip(s["pair_id"].astype(str), s["split"]))
        g["split"] = g["pair_id"].astype(str).map(m)
        if g["split"].isna().any():
            raise SystemExit("split file does not cover all gold pairs; delete it to regenerate.")
        return g
    strat = g["label"] + "|" + g["source_batch"].astype(str)
    tr, te = train_test_split(g.index, test_size=test_size, random_state=seed, stratify=strat)
    g["split"] = "train"; g.loc[te, "split"] = "test"
    if split_file:
        os.makedirs(os.path.dirname(split_file) or ".", exist_ok=True)
        g[["pair_id", "split"]].to_csv(split_file, index=False)
    return g


# ------------------------------------------------------------- scoring
def _sim(texts_a, texts_b, analyzer, ngram):
    vec = TfidfVectorizer(analyzer=analyzer, ngram_range=ngram, sublinear_tf=True,
                          min_df=1, lowercase=True)
    vec.fit(pd.concat([texts_a, texts_b], ignore_index=True))
    A, B = vec.transform(texts_a), vec.transform(texts_b)
    return np.asarray(A.multiply(B).sum(axis=1)).ravel()


def weighted_score(name_a, name_b, desc_a, desc_b, name_weight=0.7):
    """Blend name (char_wb 3-5) and description (word 1-2) similarities."""
    name_sim = _sim(name_a.map(_norm), name_b.map(_norm), "char_wb", (3, 5))
    both = (desc_a.str.strip() != "") & (desc_b.str.strip() != "")
    desc_sim = np.zeros(len(name_a))
    if both.any():
        desc_sim[both.values] = _sim(desc_a[both], desc_b[both], "word", (1, 2))
    score = name_weight * name_sim + (1.0 - name_weight) * desc_sim
    return score, name_sim, desc_sim

# ------------------------------------------------------------- metrics
def tune_threshold(scores, y):
    p, r, t = precision_recall_curve(y, scores)
    f1 = np.divide(2 * p * r, p + r, out=np.zeros_like(p), where=(p + r) > 0)
    i = int(np.nanargmax(f1[:-1])) if len(t) else 0
    return float(t[i]) if len(t) else 0.5


def evaluate(scores, y, thr):
    pred = (scores >= thr).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum()); fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum()); tn = int(((pred == 0) & (y == 0)).sum())
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    ap = float(average_precision_score(y, scores)) if len(set(y)) > 1 else float("nan")
    return dict(threshold=thr, precision=prec, recall=rec, f1=f1, average_precision=ap,
                tp=tp, fp=fp, fn=fn, tn=tn, n=len(y), positives=int(y.sum()))


def precision_target(scores, y, target):
    p, r, t = precision_recall_curve(y, scores)
    ok = np.where(p[:-1] >= target)[0]
    if not len(ok):
        return None
    i = ok[np.argmax(r[:-1][ok])]
    return dict(threshold=float(t[i]), precision=float(p[i]), recall=float(r[i]))


# --------------------------------------------------------------- report
def fmt(m):
    return (f"  precision = {m['precision']:.3f}\n"
            f"  recall    = {m['recall']:.3f}\n"
            f"  F1        = {m['f1']:.3f}\n"
            f"  avg prec  = {m['average_precision']:.3f}\n"
            f"  threshold = {m['threshold']:.3f}\n"
            f"  confusion (rows=actual same/different, cols=pred same/different):\n"
            f"        pred_same  pred_diff\n"
            f"  same   {m['tp']:>6}     {m['fn']:>6}\n"
            f"  diff   {m['fp']:>6}     {m['tn']:>6}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="data/processed/entity_resolution_gold.csv")
    ap.add_argument("--actors", default=None)
    ap.add_argument("--split-file", default="data/processed/entity_resolution_split.csv")
    ap.add_argument("--test-size", type=float, default=0.30)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--analyzer", choices=["word", "char_wb"], default="word")
    ap.add_argument("--ngram", default="1,2", help="e.g. '1,2' for word, '3,5' for char")
    ap.add_argument("--precision-target", type=float, default=0.97)
    ap.add_argument("--results-out", default=None)
    ap.add_argument("--name-weight", type=float, default=0.7, help=">=0.5 keeps the name dominant; tune on train later")
    args = ap.parse_args()
    ngram = tuple(int(x) for x in args.ngram.split(","))

    g = load_gold(args.gold)
    na, nb, da, db, used_desc = build_docs(g, args.actors)      
    g = get_split(g, args.split_file, args.test_size, args.seed)
    g["score"], _, _ = weighted_score(na, nb, da, db, name_weight=args.name_weight)

    tr, te = g[g.split == "train"], g[g.split == "test"]
    thr = tune_threshold(tr["score"].values, tr["y"].values)
    test_m = evaluate(te["score"].values, te["y"].values, thr)
    train_m = evaluate(tr["score"].values, tr["y"].values, thr)
    pt = precision_target(te["score"].values, te["y"].values, args.precision_target)

    print("=" * 64)
    print("TF-IDF BASELINE — entity resolution (Week 2)")
    print("=" * 64)
    print(f"gold pairs       : {len(g)}  (same={int(g.y.sum())}, different={int((1-g.y).sum())})")
    print(f"split            : {len(tr)} train / {len(te)} test  (seed {args.seed})")
    print(f"document fields  : {'name + description/location/hubs' if used_desc else 'name only (no actors export given)'}")
    print(f"vectorizer       : TF-IDF analyzer={args.analyzer} ngram={ngram}")
    print(f"threshold (tuned on train, max F1) = {thr:.3f}\n")
    print("TEST metrics (held-out):"); print(fmt(test_m))
    print(f"\nTRAIN metrics (for reference): F1={train_m['f1']:.3f} "
          f"P={train_m['precision']:.3f} R={train_m['recall']:.3f}")
    if pt:
        print(f"\nauto-merge band @ precision>={args.precision_target}: "
              f"threshold={pt['threshold']:.3f}  recall={pt['recall']:.3f}  "
              f"(pairs below -> Claude review)")
    else:
        print(f"\nno threshold reaches precision {args.precision_target} on test.")

    if args.results_out:
        os.makedirs(os.path.dirname(args.results_out) or ".", exist_ok=True)
        with open(args.results_out, "w") as f:
            f.write("# Entity resolution — TF-IDF baseline (Week 2)\n\n")
            f.write(f"- Gold pairs: {len(g)} (same={int(g.y.sum())}, different={int((1-g.y).sum())})\n")
            f.write(f"- Split: {len(tr)} train / {len(te)} test (held out, seed {args.seed})\n")
            f.write(f"- Documents: {'name + description/location/hubs' if used_desc else 'name only'}\n")
            f.write(f"- Vectorizer: TF-IDF analyzer={args.analyzer} ngram={ngram}\n")
            f.write(f"- Threshold (tuned on train): {thr:.3f}\n\n")
            f.write("## Held-out test metrics\n\n```\n" + fmt(test_m) + "\n```\n\n")
            f.write("Method tag for `actor_merge_log.merge_method`: `tfidf`.\n")
        print(f"\nwrote {args.results_out}")
    print("\n" + json.dumps({"test": test_m}, indent=0))


if __name__ == "__main__":
    main()