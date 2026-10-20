"""
er_description_features.py — description-based ER features.

WHY NOW
Descriptions were dropped from the ER model when gold-pair coverage was 1%
(0 of 70 positives had a description on both sides). Enrichment has since raised
actor description coverage to ~44%, so the signal is finally testable.

WHY IT MIGHT MATTER
Every current feature reads the NAME. "Michigan State University" and
"University of Michigan" look alike by every name measure. Their descriptions do
not: different city, different founding, different focus. Descriptions are
INDEPENDENT evidence that name morphology cannot provide -- which is exactly the
error class blocking auto-merge.

COVERAGE IS THE CATCH
A pair only gets real description signal when BOTH sides have one. At 44%
coverage that is ~19% of pairs. So every feature here ships with a companion
`desc_both_present` flag: the model learns "when this signal exists, trust it
this much", instead of treating a missing description as evidence of difference.

    from er_description_features import description_features, DESC_FEATURE_COLS
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

DESC_FEATURE_COLS = [
    "desc_both_present",
    "desc_tfidf_sim",
    "desc_sbert_sim",
    "desc_token_overlap",
    "desc_location_conflict",
]

# Tokens that carry organisational identity in a description
_STOP = {
    "the", "a", "an", "of", "and", "or", "for", "in", "on", "at", "to", "is",
    "are", "was", "were", "be", "been", "with", "by", "from", "as", "that",
    "this", "it", "its", "their", "which", "research", "university", "institute",
    "center", "centre", "college", "school", "program", "programs", "department",
}

# Cities are checked SEPARATELY from states. Two campuses of different
# universities sit in the same state constantly ("East Lansing, Michigan" vs
# "Ann Arbor, Michigan"), so a shared state proves nothing while a differing
# CITY is strong evidence of two distinct organisations.
_CITY_RE = re.compile(
    r"\b(boston|chicago|berkeley|stanford|cambridge|pasadena|atlanta|houston|"
    r"denver|seattle|portland|austin|madison|ann arbor|east lansing|urbana|"
    r"champaign|ithaca|princeton|evanston|boulder|davis|golden|richland|oak ridge|"
    r"los alamos|argonne|livermore|berkeley|pittsburgh|philadelphia|baltimore|"
    r"minneapolis|st\.? louis|kansas city|columbus|raleigh|durham|chapel hill|"
    r"gainesville|tallahassee|tucson|tempe|phoenix|salt lake city|reno|las vegas|"
    r"san diego|san francisco|los angeles|irvine|riverside|santa barbara|"
    r"santa cruz|new haven|providence|hanover|amherst|storrs|newark|piscataway|"
    r"college park|blacksburg|charlottesville|knoxville|nashville|athens|auburn|"
    r"tuscaloosa|baton rouge|fayetteville|norman|stillwater|lincoln|ames|"
    r"lawrence|manhattan|laramie|bozeman|moscow|pullman|corvallis|eugene)\b")

_STATE_RE = re.compile(
    r"\b(alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|"
    r"florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|"
    r"maine|maryland|massachusetts|michigan|minnesota|mississippi|missouri|montana|"
    r"nebraska|nevada|new hampshire|new jersey|new mexico|new york|north carolina|"
    r"south carolina|north dakota|south dakota|ohio|oklahoma|oregon|pennsylvania|"
    r"rhode island|tennessee|texas|utah|vermont|virginia|washington|wisconsin|"
    r"wyoming)\b")


def _toks(text) -> set[str]:
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return set()
    words = re.sub(r"[^a-z0-9 ]", " ", str(text).lower()).split()
    return {w for w in words if w not in _STOP and len(w) > 2}


def _has(text) -> bool:
    return bool(text is not None
                and not (isinstance(text, float) and pd.isna(text))
                and str(text).strip())


def _cities(text) -> set[str]:
    if not _has(text):
        return set()
    return set(_CITY_RE.findall(str(text).lower()))


def _states(text) -> set[str]:
    if not _has(text):
        return set()
    return set(_STATE_RE.findall(str(text).lower()))


def description_features(pairs: pd.DataFrame,
                         sbert_model=None) -> pd.DataFrame:
    """pairs needs columns desc_a and desc_b.

    All similarity features are ZERO when either description is missing, and
    `desc_both_present` marks which rows carry real signal.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer

    a = pairs["desc_a"].fillna("").astype(str)
    b = pairs["desc_b"].fillna("").astype(str)
    both = np.array([_has(x) and _has(y) for x, y in zip(a, b)], dtype=float)

    # --- tf-idf word-level cosine over the descriptions we actually have ---
    corpus = [t for t in pd.concat([a, b]).tolist() if t.strip()]
    tfidf = np.zeros(len(pairs))
    if len(corpus) >= 2:
        vec = TfidfVectorizer(analyzer="word", ngram_range=(1, 2),
                              sublinear_tf=True, min_df=1, stop_words="english")
        try:
            vec.fit(corpus)
            A, B = vec.transform(a), vec.transform(b)
            tfidf = np.asarray(A.multiply(B).sum(axis=1)).ravel()
        except ValueError:
            pass
    tfidf = tfidf * both

    # --- sbert cosine (optional; only if a model is supplied) ---
    sbert = np.zeros(len(pairs))
    if sbert_model is not None:
        idx = np.where(both > 0)[0]
        if len(idx):
            texts = pd.concat([a.iloc[idx], b.iloc[idx]]).unique().tolist()
            emb = sbert_model.encode(texts, normalize_embeddings=True,
                                     batch_size=32, show_progress_bar=False)
            lut = {t: e for t, e in zip(texts, emb)}
            for i in idx:
                sbert[i] = float(np.dot(lut[a.iloc[i]], lut[b.iloc[i]]))

    # --- jaccard token overlap ---
    overlap = np.zeros(len(pairs))
    for i, (x, y) in enumerate(zip(a, b)):
        if both[i]:
            tx, ty = _toks(x), _toks(y)
            if tx and ty:
                overlap[i] = len(tx & ty) / len(tx | ty)

    # --- location conflict ---
    # City mismatch is the strong signal (East Lansing vs Ann Arbor, both in
    # Michigan, are different universities). State mismatch is a weaker backup
    # used only when neither side names a city.
    conflict = np.zeros(len(pairs))
    for i, (x, y) in enumerate(zip(a, b)):
        if not both[i]:
            continue
        cx, cy = _cities(x), _cities(y)
        if cx and cy:
            conflict[i] = 0.0 if (cx & cy) else 1.0
            continue
        sx, sy = _states(x), _states(y)
        if sx and sy and not (sx & sy):
            conflict[i] = 1.0

    return pd.DataFrame({
        "desc_both_present": both,
        "desc_tfidf_sim": tfidf,
        "desc_sbert_sim": sbert,
        "desc_token_overlap": overlap,
        "desc_location_conflict": conflict,
    }, index=pairs.index)


if __name__ == "__main__":
    df = pd.DataFrame({
        "desc_a": [
            "Public land-grant research university in East Lansing, Michigan.",
            "Public research university in Ann Arbor, Michigan.",
            "National laboratory in Golden, Colorado focused on renewable energy.",
            "", "Agricultural research center in Davis, California.",
        ],
        "desc_b": [
            "Public research university in Ann Arbor, Michigan.",
            "Public research university in Ann Arbor, Michigan.",
            "US national lab for renewable energy research, Golden, Colorado.",
            "Public research university in Ann Arbor, Michigan.",
            "Agricultural research center in Davis, California.",
        ],
    })
    out = description_features(df)
    print(out.round(3).to_string())
    print("\nrow0 = Michigan State vs Michigan (different) -> expect location_conflict=1")
    print("row1 = identical (same)                        -> expect high sim")
    print("row3 = one side missing                        -> expect all zeros, both=0")