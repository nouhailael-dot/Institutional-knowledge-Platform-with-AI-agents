"""
backfill_confirmed_merges.py — merge the duplicates a human already confirmed.

Reads entity_resolution_gold.csv, takes every pair labeled `same`, and groups
them into CLUSTERS (connected components). Duplicates are not just pairs: e.g.
"NREL", "National Renewable Energy Laboratory", "... (NREL)" and
"... (energy-mineral link)" are one entity across four rows. Merging pair-by-pair
would create chains; merging per cluster gives one canonical winner that absorbs
every other member directly.

These merges use human labels, not model scores, so they carry no threshold risk.
They are logged with method='human_labeled' and are individually reversible.

WINNER RULE (per cluster), in order:
  1. most complete record  — most non-empty fields on the actor row
  2. most connected        — most hub/sector/person/relevance references
  3. cleanest name         — no parentheses, then longest form
  4. oldest created_at     — stable tie-break

DRY RUN BY DEFAULT. Nothing is written without --apply.

    python scripts/backfill_confirmed_merges.py --gold data/processed/entity_resolution_gold.csv
    python scripts/backfill_confirmed_merges.py --gold ... --apply
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.db.session import SessionLocal
try:
    from actor_merge import merge_actors
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parent))
    from actor_merge import merge_actors

SUBUNIT_WORDS = {
    "department", "dept", "school", "college", "center", "centre", "institute",
    "lab", "labs", "laboratory", "laboratories", "program", "programs",
    "division", "faculty", "erg", "chemistry", "engineering", "physics",
    "biology", "medicine", "campus", "branch", "office",
    # added after review: a sub-unit was absorbing its own parent
    # ("Mass General Brigham AI initiatives" was swallowing "Mass General Brigham")
    "initiative", "initiatives", "group", "unit", "facility", "facilities",
    "complex", "project", "projects",
}
# Purely structural additions. If the longer name adds ONLY these, the two names
# are the same entity written differently -- "Rice University Chemistry" and
# "Rice University Department of Chemistry" are one department, not two.
STRUCTURAL_WORDS = {"department", "dept", "of", "the", "at", "and", "for", "in",
                    "university", "univ"}

# A name that denotes a WHOLE organization. If the shorter side is one of these
# and the longer side adds anything substantive, the longer side is a part of it
# ("University of Michigan" + "Health", "Cleveland Clinic" + "Innovation").
# Vocabulary lists of unit words kept missing these; this is structural instead.
_WHOLE_ORG_HEAD = _re_compile = None


def is_whole_org(name):
    import re as _re
    n = _re.sub(r"\([^)]*\)", " ", (name or "")).lower()
    n = _re.sub(r"[^a-z0-9 ]", " ", n)
    n = _re.sub(r"\s+", " ", n).strip()
    if _re.match(r"^(university|univ)\b", n):
        return True
    return bool(_re.search(r"\b(university|clinic|hospital|corporation|corp|company|inc)$", n))


def paren_only_difference(a_name, b_name):
    """True when the names are identical once parentheticals are removed --
    'MIT Energy Initiative (materials interface)' vs 'MIT Energy Initiative'."""
    import re as _re
    def base(x):
        x = _re.sub(r"\([^)]*\)", " ", x or "")
        return " ".join(_re.sub(r"[^a-z0-9 ]", " ", x.lower()).split())
    ba, bb = base(a_name), base(b_name)
    if not ba or ba != bb:
        return False
    parens = _re.findall(r"\(([^)]*)\)", (a_name or "") + " " + (b_name or ""))
    init = _initials(ba)
    for p_ in parens:                       # acronym tag => definitely same entity
        if _re.sub(r"[^a-z0-9]", "", p_.lower()) == init:
            return True
    return len(ba.split()) >= 3
SAFE_JACCARD = 0.6      # token overlap required for an automatic merge

# All-caps strings that are not institution identifiers
NON_INSTITUTION_CAPS = {"ai", "us", "usa", "it", "hq", "rd", "phd", "cs"}
_GENERIC_INST = {
    "department", "dept", "of", "and", "the", "for", "school", "college",
    "center", "centre", "institute", "institutes", "lab", "labs", "laboratory",
    "laboratories", "program", "programs", "division", "faculty", "research",
    "science", "sciences", "engineering", "chemistry", "physics", "biology",
    "medicine", "university", "univ", "national", "energy", "renewable",
}


def institution_markers(name):
    """Identify WHICH organization a name belongs to, so two different
    institutions never end up in one cluster (Texas A&M vs UIUC).

    Two signals: an all-caps acronym (UIUC, NREL, MACHH2), and the proper-noun
    run that precedes a structural word ("Texas A&M" in "Texas A&M Department
    of ..."). Lower-case parentheticals like "(energy-mineral link)" are ignored.
    """
    import re as _re
    marks = set()
    for m in _re.findall(r"\b([A-Z][A-Z&]{1,7}\d?)\b", name or ""):
        ml = m.lower()
        if ml not in NON_INSTITUTION_CAPS and ml not in _GENERIC_INST:
            marks.add(ml)
    head = _re.split(r"\b(?:Department|Dept|School|College|Institute|Center|Centre|Division)\b",
                     name or "", flags=_re.I)
    if len(head) > 1 and head[0].strip():
        for t in _re.sub(r"[^A-Za-z0-9& ]", " ", head[0]).split():
            tl = t.lower()
            if len(tl) > 1 and tl not in _GENERIC_INST:
                marks.add(tl)
    return marks


def cluster_has_institution_conflict(names):
    """True if two members clearly belong to DIFFERENT institutions."""
    sets = [m for m in (institution_markers(n) for n in names) if m]
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            if not (sets[i] & sets[j]):
                return True
    return False


def _toks(name):
    import re as _re
    return set(_re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).split())


def _acronym_of(name):
    stop = {"of", "the", "and", "for", "at", "in", "de", "la", "&"}
    t = [w for w in _toks(name) if w not in stop]
    return "".join(w[0] for w in sorted(t)) if len(t) >= 2 else ""


def _toks_ordered(name):
    import re as _re
    return _re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).split()


def _initials(name):
    """Initials in WORD ORDER. _toks returns a set, so it cannot be used here --
    that bug turned 'National Renewable Energy Laboratory' into 'lern'."""
    stop = {"of", "the", "and", "for", "at", "in", "de", "la", "&"}
    t = [w for w in _toks_ordered(name) if w not in stop]
    return "".join(w[0] for w in t)


def is_acronym_pair(a_name, b_name):
    """True for 'NREL' <-> 'National Renewable Energy Laboratory (NREL)'.

    Requires the short side to be a SINGLE token that is either written in caps
    or matches the initials of the long side -- so 'Microsoft' vs 'Microsoft AI'
    is NOT treated as an acronym pair.
    """
    ta, tb = _toks(a_name), _toks(b_name)
    short, long_ = (a_name, b_name) if len(ta) < len(tb) else (b_name, a_name)
    ts, tl = _toks(short), _toks(long_)
    if len(ts) != 1:
        return False
    tok = next(iter(ts))
    looks_acronym = (short.strip().isupper() and 2 <= len(tok) <= 8) or tok == _initials(long_)
    return looks_acronym and (tok in tl or tok == _initials(long_))


def classify_edge(a_name, b_name):
    """Decide what a confirmed-'same' pair really is.

    Returns 'hierarchy' (sub-unit of the other -> should be an edge, NOT a merge),
    'merge' (safe duplicate), or 'review' (ambiguous, a human decides).
    """
    ta, tb = _toks(a_name), _toks(b_name)
    if not ta or not tb:
        return "review"
    # acronym relationship is a genuine duplicate -- checked FIRST, because the
    # expanded form usually contains a sub-unit word ("Laboratory", "Center")
    # that would otherwise be misread as a parent/child relationship.
    if is_acronym_pair(a_name, b_name):
        return "merge"
    # identical apart from a parenthetical context tag => same entity
    if paren_only_difference(a_name, b_name):
        return "merge"
    # strict subset => check WHAT the longer name adds
    for small, big, sname, bname in ((ta, tb, a_name, b_name), (tb, ta, b_name, a_name)):
        if small < big:
            added = big - small
            if added <= STRUCTURAL_WORDS:      # only "Department of" etc => same entity
                return "merge"
            # the shorter side names a whole organization and the longer side
            # adds something substantive => the longer side is a PART of it
            if is_whole_org(sname):
                return "hierarchy"
            if added & SUBUNIT_WORDS and not (small & SUBUNIT_WORDS):
                return "hierarchy"
    jac = len(ta & tb) / len(ta | tb)
    return "merge" if jac >= SAFE_JACCARD else "review"


COMPLETENESS_FIELDS = [
    "actor_type", "actor_type_raw", "description", "website", "location_city",
    "state", "country", "primary_technical_focus", "technical_approach",
    "current_activities", "technology_ip_notes", "key_constraints",
    "estimated_trl", "primary_lifecycle_role", "source_id",
]


def clusters_from_gold(gold_path):
    g = pd.read_csv(gold_path, dtype=str).fillna("")
    g.columns = [c.strip() for c in g.columns]
    same = g[g["label"].str.strip().str.lower() == "same"]
    if same.empty:
        raise SystemExit("no pairs labeled 'same' in the gold file")

    parent = {}
    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    names, hierarchy_edges, review_edges = {}, [], []
    for _, r in same.iterrows():
        a, b = str(r["actor_id_a"]).strip(), str(r["actor_id_b"]).strip()
        if not a or not b:
            continue
        names[a] = r.get("name_a", ""); names[b] = r.get("name_b", "")
        kind = classify_edge(r.get("name_a", ""), r.get("name_b", ""))
        if kind == "hierarchy":
            hierarchy_edges.append((a, b, r.get("name_a", ""), r.get("name_b", ""),
                                    r.get("pair_id", "")))
            continue                      # do NOT let this edge join a cluster
        if kind == "review":
            review_edges.append((a, b, r.get("name_a", ""), r.get("name_b", ""),
                                 r.get("pair_id", "")))
            continue
        union(a, b)

    groups = defaultdict(list)
    for node in list(parent):
        groups[find(node)].append(node)
    return ([sorted(v) for v in groups.values()], names, len(same),
            hierarchy_edges, review_edges)


def load_actors(conn, ids):
    rows = conn.execute(
        text("SELECT * FROM actor WHERE actor_id = ANY(CAST(:ids AS uuid[]))"),
        {"ids": list(ids)}).mappings().all()
    return {str(r["actor_id"]): dict(r) for r in rows}


def ref_count(conn, actor_id):
    q = ("SELECT (SELECT COUNT(*) FROM hub_actor WHERE actor_id=:a)"
         " + (SELECT COUNT(*) FROM actor_sector WHERE actor_id=:a)"
         " + (SELECT COUNT(*) FROM actor_person WHERE actor_id=:a)"
         " + (SELECT COUNT(*) FROM actor_relevance WHERE actor_id=:a)"
         " + (SELECT COUNT(*) FROM partnership_profile WHERE actor_id=:a)"
         " + (SELECT COUNT(*) FROM event WHERE host_actor_id=:a)")
    return int(conn.execute(text(q), {"a": actor_id}).scalar() or 0)


def completeness(row):
    n = 0
    for f in COMPLETENESS_FIELDS:
        v = row.get(f)
        if v is not None and str(v).strip() != "":
            n += 1
    return n


def name_cleanliness(name):
    """Higher is better. Prefers the FULLER, more specific name.

    The earlier version rewarded short names with no parentheses, which made a
    parent university beat its own departments. Sub-unit edges are now removed
    before clustering, and the tie-break prefers the more informative name.
    """
    nm = (name or "").strip()
    score = min(len(nm) / 60.0, 1.0)
    if len(nm.split()) > 1:            # a full form beats a bare acronym
        score += 1
    return score


def pick_winner(conn, members, actor_rows):
    best, best_key = None, None
    for aid in members:
        row = actor_rows.get(aid)
        if row is None:
            continue
        key = (completeness(row), ref_count(conn, aid),
               name_cleanliness(row.get("name")),
               -(row.get("created_at").timestamp() if row.get("created_at") else 0))
        if best_key is None or key > best_key:
            best, best_key = aid, key
    return best


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gold", default="data/processed/entity_resolution_gold.csv")
    ap.add_argument("--apply", action="store_true", help="execute merges (default: dry run)")
    ap.add_argument("--report", default="docs/ml/results/backfill_merge_plan.csv")
    ap.add_argument("--limit", type=int, default=None, help="only process the first N clusters")
    args = ap.parse_args()

    groups, gold_names, n_pairs, hier_edges, review_edges = clusters_from_gold(args.gold)
    groups = [g for g in groups if len(g) > 1]
    if args.limit:
        groups = groups[:args.limit]
    all_ids = [i for g in groups for i in g]
    print(f"[gold] {n_pairs} confirmed duplicate pairs")
    print(f"[guard] {len(hier_edges)} pair(s) look like SUB-UNIT of a parent "
          f"-> hierarchy edges, not merges")
    print(f"[guard] {len(review_edges)} pair(s) ambiguous -> human review")
    print(f"[plan] {len(groups)} safe clusters over {len(all_ids)} actor rows")

    out_dir = Path(args.report).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(hier_edges, columns=["actor_id_a", "actor_id_b", "name_a", "name_b",
                                      "pair_id"]).to_csv(out_dir / "hierarchy_candidates.csv",
                                                          index=False)
    pd.DataFrame(review_edges, columns=["actor_id_a", "actor_id_b", "name_a", "name_b",
                                        "pair_id"]).to_csv(out_dir / "needs_human_review.csv",
                                                            index=False)
    print(f"[saved] {out_dir}/hierarchy_candidates.csv, {out_dir}/needs_human_review.csv")

    s = SessionLocal(); conn = s.connection()
    actor_rows = load_actors(conn, all_ids)
    missing = [i for i in all_ids if i not in actor_rows]
    already = [i for i, r in actor_rows.items() if r.get("merged_into_actor_id")]
    if missing:
        print(f"[warn] {len(missing)} actor id(s) in the gold file are not in the DB — skipped")
    if already:
        print(f"[warn] {len(already)} actor(s) are already merged away — skipped")

    plan, conflicted = [], []
    for members in groups:
        live = [m for m in members
                if m in actor_rows and not actor_rows[m].get("merged_into_actor_id")]
        if len(live) < 2:
            continue
        member_names = [actor_rows[m].get("name") or "" for m in live]
        if cluster_has_institution_conflict(member_names):
            conflicted.append(member_names)
            continue
        winner = pick_winner(conn, live, actor_rows)
        for loser in live:
            if loser == winner:
                continue
            plan.append({
                "winner_actor_id": winner,
                "winner_name": actor_rows[winner].get("name"),
                "winner_fields": completeness(actor_rows[winner]),
                "loser_actor_id": loser,
                "loser_name": actor_rows[loser].get("name"),
                "loser_fields": completeness(actor_rows[loser]),
                "cluster_size": len(live),
            })
    s.close()

    if conflicted:
        print(f"\n[guard] {len(conflicted)} cluster(s) span DIFFERENT institutions "
              f"-> sent to review, not merged:")
        for names in conflicted[:6]:
            for n in names:
                print(f"      {n[:72]}")
            print("      ---")
        pd.DataFrame({"cluster": [" || ".join(n) for n in conflicted]}).to_csv(
            Path(args.report).parent / "institution_conflicts.csv", index=False)

    df = pd.DataFrame(plan)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.report, index=False)
    print(f"[plan] {len(df)} merges across {df['winner_actor_id'].nunique() if len(df) else 0} "
          f"canonical actors -> {args.report}")

    if len(df):
        print("\n--- sample of the plan (largest clusters first) ---")
        for wid, grp in sorted(df.groupby("winner_actor_id"),
                               key=lambda kv: -len(kv[1]))[:8]:
            w = grp.iloc[0]
            print(f"\n  KEEP  {w['winner_name'][:66]}  ({w['winner_fields']} fields)")
            for _, r in grp.iterrows():
                print(f"   merge {r['loser_name'][:64]}  ({r['loser_fields']} fields)")

    if not args.apply:
        print(f"\nDRY RUN — nothing written. Review {args.report}, then re-run with --apply")
        return

    print(f"\n[apply] executing {len(df)} merges ...")
    done = failed = 0
    for _, r in df.iterrows():
        try:
            merge_actors(SessionLocal, r["winner_actor_id"], r["loser_actor_id"],
                         score=1.0, method="human_labeled", decided_by="backfill_gold")
            done += 1
        except Exception as e:
            failed += 1
            print(f"  FAILED {r['loser_name'][:50]} -> {r['winner_name'][:50]}: "
                  f"{type(e).__name__}: {e}")
    print(f"\n[done] {done} merged, {failed} failed. "
          f"Every merge is in actor_merge_log and reversible (newest-first).")


if __name__ == "__main__":
    main()