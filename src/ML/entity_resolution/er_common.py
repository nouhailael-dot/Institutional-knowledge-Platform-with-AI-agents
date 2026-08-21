"""
er_common.py — shared utilities for GHUS Entity Resolution.

Scope, after the data review (2025):
  * Descriptions and location are ~1% covered on the gold pairs (0/70 on the
    duplicate pairs), so they are NOT used. There is no document builder here.
  * The real signals are: the actor NAME (100%) and HUB membership (~92%).
  * SBERT encodes the NAME ONLY. Hub info never enters SBERT — appending a hub
    string would pull two different orgs in the same hub together, which is the
    exact false signal we must avoid. Hubs enter ONLY as a combiner feature
    (hub_overlap), where the model learns its sign from data.

Provides:
  * load_actors / load_gold_with_split — matched to the real CSV schemas.
  * lexical_features — acronym, containment, Jaccard, length ratio, hub overlap.
  * evaluation suite — precision/recall/F1 at a train-selected threshold, plus
    AUTO-MERGE COVERAGE at precision >= MIN_PRECISION, three decision zones
    (AUTO / REVIEW / DIFFERENT), and bootstrap CIs (test has ~21 positives, so
    point estimates are noisy — always read the CI).

Rule: thresholds are selected on TRAIN and reported on TEST. Never tune on test.

LEAKAGE NOTE: the gold file carries tfidf_cosine / band / match_reason columns
from how the labeling set was sampled. These do NOT exist for a new incoming
actor, so they are never used as features. TF-IDF is always recomputed fresh.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd
from sklearn.metrics import precision_recall_curve

MIN_PRECISION = 0.97       # auto-merge precision floor
LOW_ZONE_MIN_RECALL = 0.98  # LOW threshold keeps >=98% of true dupes above it

_ACRONYM_STOP = {"of", "the", "and", "for", "de", "la", "du", "des", "at", "in", "on", "a", "&"}
_POSITIVE = {"same", "1", "true", "match", "duplicate", "yes"}
_NEGATIVE = {"different", "0", "false", "distinct", "no", "diff"}


# ---------------------------------------------------------------- normalization
def normalize_name(s) -> str:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\([^)]*\)", " ", s.lower())          # drop parentheticals
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokens(s) -> set:
    return set(normalize_name(s).split())


# ---------------------------------------------------------------- loaders
def load_actors(path) -> pd.DataFrame:
    """actors.csv -> actor_id, name, hubs, description, location """
    a = pd.read_csv(path, dtype=str).fillna("")
    a.columns = [c.strip() for c in a.columns]
    for c in ("actor_id", "name"):
        if c not in a.columns:
            raise SystemExit(f"{path}: missing column '{c}'")
    for c in ("hubs", "description", "location"):
        if c not in a.columns:
            a[c] = ""
    return a[["actor_id", "name", "hubs", "description", "location"]].copy()


def load_gold_with_split(gold_path, split_path) -> pd.DataFrame:
    """Return pairs: pair_id, actor_id_a, actor_id_b, name_a, name_b, y, split."""
    g = pd.read_csv(gold_path, dtype=str).fillna("")
    g.columns = [c.strip() for c in g.columns]
    for c in ("name_a", "name_b", "label"):
        if c not in g.columns:
            raise SystemExit(f"{gold_path}: missing column '{c}'")
    lab = g["label"].str.strip().str.lower()
    keep = lab.isin(_POSITIVE | _NEGATIVE)
    if (~keep).any():
        print(f"[warn] dropping {int((~keep).sum())} rows with unlabeled/unknown label")
    g = g[keep].copy()
    g["y"] = g["label"].str.strip().str.lower().isin(_POSITIVE).astype(int)

    for c in ("actor_id_a", "actor_id_b", "pair_id"):
        if c not in g.columns:
            g[c] = ""

    s = pd.read_csv(split_path, dtype=str)
    s.columns = [c.strip() for c in s.columns]
    if "pair_id" in g.columns and g["pair_id"].str.strip().ne("").all() \
            and "pair_id" in s.columns and "split" in s.columns:
        g = g.merge(s[["pair_id", "split"]], on="pair_id", how="left")
    elif "split" in s.columns and len(s) == len(g):
        g["split"] = s["split"].values
    else:
        raise SystemExit("could not align split to gold (need matching pair_id, or equal row counts)")

    g["split"] = g["split"].astype(str).str.lower().str.strip()
    g["split"] = g["split"].map(lambda x: "train" if "train" in x else ("test" if "test" in x else x))
    if (~g["split"].isin(["train", "test"])).any():
        n = int((~g["split"].isin(["train", "test"])).sum())
        raise SystemExit(f"{n} gold pairs have no train/test split assigned")
    return g.reset_index(drop=True)


def attach_hubs(pairs: pd.DataFrame, actors: pd.DataFrame) -> pd.DataFrame:
    """Attach hubs_a / hubs_b by actor_id (fallback: normalized name)."""
    p = pairs.copy()
    by_id = dict(zip(actors["actor_id"], actors["hubs"]))
    id_hit = p["actor_id_a"].isin(by_id).mean()
    if id_hit >= 0.5:
        p["hubs_a"] = p["actor_id_a"].map(by_id).fillna("")
        p["hubs_b"] = p["actor_id_b"].map(by_id).fillna("")
        print(f"[join] hubs attached by actor_id ({id_hit:.0%} hit)")
    else:
        by_name = dict(zip(actors["name"].map(normalize_name), actors["hubs"]))
        p["hubs_a"] = p["name_a"].map(lambda n: by_name.get(normalize_name(n), ""))
        p["hubs_b"] = p["name_b"].map(lambda n: by_name.get(normalize_name(n), ""))
        cov = ((p["hubs_a"] != "") | (p["hubs_b"] != "")).mean()
        print(f"[join] id-join weak ({id_hit:.0%}); hubs attached by NAME ({cov:.0%} matched)")
    return p

def attach_descriptions(gold, actors):
    """Attach desc_a/desc_b by actor_id, same pattern as attach_hubs."""
    lut = dict(zip(actors["actor_id"].astype(str), actors["description"].fillna("")))
    gold["desc_a"] = gold["actor_id_a"].astype(str).map(lut).fillna("")
    gold["desc_b"] = gold["actor_id_b"].astype(str).map(lut).fillna("")
    hit = ((gold.desc_a != "") & (gold.desc_b != "")).mean()
    print(f"[join] descriptions on both sides for {hit:.0%} of pairs")
    return gold

# ---------------------------------------------------------------- features
def _acronym(name: str) -> str:
    toks = [t for t in normalize_name(name).split() if t not in _ACRONYM_STOP]
    return "".join(t[0] for t in toks) if len(toks) >= 2 else ""


def acronym_match(a: str, b: str) -> int:
    ca = normalize_name(a).replace(" ", "")
    cb = normalize_name(b).replace(" ", "")
    aa, ab = _acronym(a), _acronym(b)
    return int((len(aa) >= 3 and aa == cb) or (len(ab) >= 3 and ab == ca))


def containment(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def jaccard(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not (ta | tb):
        return 0.0
    return len(ta & tb) / len(ta | tb)


def length_ratio(a: str, b: str) -> float:
    la, lb = len(normalize_name(a)), len(normalize_name(b))
    return min(la, lb) / max(la, lb) if max(la, lb) else 0.0


def hub_overlap(ha: str, hb: str) -> float:
    sa = {normalize_name(x) for x in re.split(r";", str(ha)) if normalize_name(x)}
    sb = {normalize_name(x) for x in re.split(r";", str(hb)) if normalize_name(x)}
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def name_features(p: pd.DataFrame) -> pd.DataFrame:
    """Name-only lexical features (available for 100% of pairs)."""
    return pd.DataFrame({
        "acronym_match": [acronym_match(a, b) for a, b in zip(p.name_a, p.name_b)],
        "containment":   [containment(a, b) for a, b in zip(p.name_a, p.name_b)],
        "jaccard":       [jaccard(a, b) for a, b in zip(p.name_a, p.name_b)],
        "length_ratio":  [length_ratio(a, b) for a, b in zip(p.name_a, p.name_b)],
    }, index=p.index)


def hub_feature(p: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "hub_overlap": [hub_overlap(a, b) for a, b in zip(p.hubs_a, p.hubs_b)],
    }, index=p.index)


# ---------------------------------------------------------------- evaluation
@dataclass
class ModelReport:
    model: str
    test_precision: float = np.nan
    test_recall: float = np.nan
    test_f1: float = np.nan
    f1_threshold: float = np.nan
    automerge_threshold: float | None = None
    automerge_coverage: float = np.nan      # recall of true dupes inside auto zone (TEST)
    automerge_precision: float = np.nan
    am_prec_ci: str = ""
    automerge_n: int = 0
    automerge_false_merges: int = 0
    low_threshold: float | None = None
    n_auto: int = 0
    n_review: int = 0
    n_different: int = 0
    review_share: float = np.nan
    missed_dupes: int = 0
    notes: str = ""


def _prf(y, s, t):
    pred = s >= t
    tp = int((pred & (y == 1)).sum()); fp = int((pred & (y == 0)).sum())
    fn = int((~pred & (y == 1)).sum())
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f, tp, fp, fn


def _best_f1_threshold(y, s):
    p, r, t = precision_recall_curve(y, s)
    f1 = np.where(p + r > 0, 2 * p * r / (p + r + 1e-12), 0.0)[:-1]
    return float(t[int(np.argmax(f1))]) if len(t) else 0.5


def _automerge_threshold(y, s, min_p):
    p, r, t = precision_recall_curve(y, s)
    ok = [(ti, pi, ri) for ti, pi, ri in zip(t, p[:-1], r[:-1]) if pi >= min_p]
    return float(max(ok, key=lambda x: (x[2], x[1]))[0]) if ok else None


def _low_threshold(y, s, min_r):
    p, r, t = precision_recall_curve(y, s)
    ok = [ti for ti, ri in zip(t, r[:-1]) if ri >= min_r]
    return float(max(ok)) if ok else None


def _bootstrap_precision_ci(y, s, t, n_boot=2000, seed=13):
    rng = np.random.default_rng(seed)
    n = len(y); vals = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        pred = s[idx] >= t
        d = int(pred.sum())
        if d:
            vals.append(float((pred & (y[idx] == 1)).sum() / d))
    if not vals:
        return (np.nan, np.nan)
    return (float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5)))


def evaluate(name, y_tr, s_tr, y_te, s_te, min_p=MIN_PRECISION, min_r=LOW_ZONE_MIN_RECALL):
    rep = ModelReport(model=name)
    rep.f1_threshold = _best_f1_threshold(y_tr, s_tr)
    rep.test_precision, rep.test_recall, rep.test_f1, *_ = _prf(y_te, s_te, rep.f1_threshold)

    high = _automerge_threshold(y_tr, s_tr, min_p)
    rep.automerge_threshold = high
    if high is not None:
        p, r, _, tp, fp, _ = _prf(y_te, s_te, high)
        rep.automerge_coverage, rep.automerge_precision = r, p
        rep.automerge_n, rep.automerge_false_merges = tp + fp, fp
        lo, hi = _bootstrap_precision_ci(y_te, s_te, high)
        rep.am_prec_ci = "" if np.isnan(lo) else f"[{lo:.2f},{hi:.2f}]"
    else:
        rep.notes = f"no train threshold reaches precision >= {min_p}"

    low = _low_threshold(y_tr, s_tr, min_r)
    if high is not None and low is not None:
        low = min(low, high)
        rep.low_threshold = low
        auto = s_te >= high; diff = s_te < low; review = ~auto & ~diff
        rep.n_auto, rep.n_review, rep.n_different = int(auto.sum()), int(review.sum()), int(diff.sum())
        rep.review_share = float(review.mean())
        rep.missed_dupes = int(((y_te == 1) & diff).sum())
    return rep


def to_frame(reports) -> pd.DataFrame:
    df = pd.DataFrame([asdict(r) for r in reports])
    order = ["model", "test_precision", "test_recall", "test_f1",
             "automerge_coverage", "automerge_precision", "am_prec_ci",
             "automerge_n", "automerge_false_merges", "automerge_threshold",
             "low_threshold", "n_auto", "n_review", "n_different", "review_share",
             "missed_dupes", "f1_threshold", "notes"]
    return df[[c for c in order if c in df.columns]]


def save_pr_curve(y, s, path):
    p, r, t = precision_recall_curve(y, s)
    pd.DataFrame({"threshold": np.append(t, np.nan), "precision": p, "recall": r}).to_csv(path, index=False)