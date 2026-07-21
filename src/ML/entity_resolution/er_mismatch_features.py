"""
er_mismatch_features.py — discriminative features for entity resolution.

WHY THIS EXISTS
Every existing feature (TF-IDF, SBERT, containment, Jaccard, hub overlap)
measures SIMILARITY. None measures DIFFERENCE. That is why the model cannot
separate:

    Michigan State University   vs  University of Michigan      (different, 0.884)
    Battery Material Startups   vs  Battery Materials Startups  (same,      0.912)

Both look highly similar. The distinguishing evidence is what ONE side contains
that the other does not -- the token "State" changes the institution, while
"Material"/"Materials" is the same word. These features encode that.

Add to er_common.py (or import from here) and include the new column names in
the feature lists of run_er_kfold.py / run_er_eval.py / train_production_combiner.py.
"""
from __future__ import annotations

import re
import unicodedata

import pandas as pd

# Words that carry no identity: dropping them isolates the tokens that actually
# name the organization.
STRUCTURAL = {
    "university", "univ", "of", "the", "at", "in", "and", "for", "a", "an",
    "department", "dept", "school", "college", "center", "centre", "institute",
    "laboratory", "laboratories", "lab", "labs", "program", "programs",
    "division", "office", "group", "inc", "llc", "ltd", "corporation", "corp",
    "company", "co", "the",
}

# Tokens that distinguish one institution from another with a similar name.
# "Michigan State University" is not "University of Michigan".
DISTINGUISHING_QUALIFIERS = {
    "state", "tech", "technical", "technological", "technology", "polytechnic",
    "poly", "community", "southern", "northern", "eastern", "western",
    "central", "north", "south", "east", "west", "upper", "lower", "greater",
    "national", "international", "american", "royal", "federal",
}

ORDINAL_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5,
}

MISMATCH_FEATURE_COLS = [
    "qualifier_mismatch",
    "unique_tokens_both_sides",
    "unique_token_count",
    "numeric_mismatch",
]


def _norm(s) -> str:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9& ]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _stem(tok: str) -> str:
    """Crude singular/plural fold so 'Material' == 'Materials'."""
    if len(tok) > 3 and tok.endswith("ies"):
        return tok[:-3] + "y"
    if len(tok) > 3 and tok.endswith("es") and not tok.endswith("ses"):
        return tok[:-2]
    if len(tok) > 3 and tok.endswith("s"):
        return tok[:-1]
    return tok


def _content_tokens(name: str) -> set[str]:
    """Identity-bearing tokens: abbreviations expanded, structural words
    removed, plurals folded."""
    out = set()
    for t in _norm(name).split():
        t = ABBREV.get(t, t)
        if t not in STRUCTURAL:
            out.add(_stem(t))
    return out


def qualifier_mismatch(a: str, b: str) -> int:
    """1 when one name carries a distinguishing qualifier the other lacks.

    Michigan STATE University vs University of Michigan -> 1
    Battery Material Startups vs Battery Materials Startups -> 0
    """
    qa = {t for t in _norm(a).split() if t in DISTINGUISHING_QUALIFIERS}
    qb = {t for t in _norm(b).split() if t in DISTINGUISHING_QUALIFIERS}
    return int(qa != qb)


def unique_tokens_both_sides(a: str, b: str) -> int:
    """1 when EACH side has an identity token the other lacks.

    Strong evidence of two different organizations rather than two spellings
    of one. 'Berkeley Water Center' vs 'UC Berkeley Water Center' -> 0
    (only one side adds anything).
    """
    ta, tb = _content_tokens(a), _content_tokens(b)
    return int(bool(ta - tb) and bool(tb - ta))


def unique_token_count(a: str, b: str) -> int:
    """How many identity tokens appear on exactly one side (capped at 5)."""
    ta, tb = _content_tokens(a), _content_tokens(b)
    return min(len((ta - tb) | (tb - ta)), 5)


def _numbers(name: str) -> set:
    out = set()
    for t in _norm(name).split():
        if t.isdigit():
            out.add(int(t))
        elif t in ORDINAL_WORDS:
            out.add(ORDINAL_WORDS[t])
    return out


def numeric_mismatch(a: str, b: str) -> int:
    """1 when the names carry different numbers ('Site 1' vs 'Site 2')."""
    na, nb = _numbers(a), _numbers(b)
    if not na and not nb:
        return 0
    return int(na != nb)


# Common abbreviations that mean the same thing, folded before comparison so
# 'R&D Labs' and 'Research Labs' do not look like different organizations.
ABBREV = {
    "r&d": "research", "rd": "research", "dept": "department",
    "sci": "science", "tech": "technology", "eng": "engineering",
    "natl": "national", "intl": "international", "univ": "university",
    "inst": "institute", "med": "medical", "ctr": "center", "lab": "laboratory",
}


def _initials(name: str) -> str:
    toks = [t for t in _norm(name).split() if t not in {"of", "the", "and", "for", "at", "in", "&"}]
    return "".join(t[0] for t in toks)


def is_acronym_pair(a: str, b: str) -> bool:
    """'NREL' vs 'National Renewable Energy Laboratory' is ONE organization.

    Acronym pairs look maximally different token-wise, so the mismatch features
    must be suppressed for them or every acronym reads as a distinct entity.
    """
    ta, tb = _norm(a).split(), _norm(b).split()
    short, long_ = (a, b) if len(ta) < len(tb) else (b, a)
    ts = _norm(short).split()
    if len(ts) != 1:
        return False
    tok = ts[0]
    return tok == _initials(long_) or tok in _norm(long_).split()


def mismatch_features(pairs: pd.DataFrame) -> pd.DataFrame:
    """pairs needs columns name_a and name_b."""
    rows = []
    for a, b in zip(pairs.name_a, pairs.name_b):
        if is_acronym_pair(a, b):        # suppress: acronym == expansion
            rows.append((0, 0, 0, 0))
        else:
            rows.append((qualifier_mismatch(a, b), unique_tokens_both_sides(a, b),
                         unique_token_count(a, b), numeric_mismatch(a, b)))
    return pd.DataFrame(rows, columns=MISMATCH_FEATURE_COLS, index=pairs.index)


if __name__ == "__main__":
    checks = [
        ("Michigan State University", "University of Michigan", "different"),
        ("Washington State University", "University of Washington (UW)", "different"),
        ("Arizona State University (ASU)", "University of Arizona", "different"),
        ("George Washington University", "University of Washington (UW)", "different"),
        ("Missouri University of Science & Technology", "University of Missouri", "different"),
        ("Battery Material Startups", "Battery Materials Startups", "SAME"),
        ("Agrochemical R&D Labs", "Agrochemical Research Labs", "SAME"),
        ("Berkeley Water Center", "UC Berkeley Water Center", "SAME"),
        ("National Renewable Energy Laboratory", "NREL", "SAME"),
    ]
    df = pd.DataFrame({"name_a": [c[0] for c in checks],
                       "name_b": [c[1] for c in checks]})
    f = mismatch_features(df)
    print(f"{'truth':<10} {'qual':>4} {'both':>5} {'uniq':>5} {'num':>4}   pair")
    for i, (a, b, truth) in enumerate(checks):
        r = f.iloc[i]
        print(f"{truth:<10} {r.qualifier_mismatch:>4} {r.unique_tokens_both_sides:>5} "
              f"{r.unique_token_count:>5} {r.numeric_mismatch:>4}   {a[:34]} || {b[:28]}")