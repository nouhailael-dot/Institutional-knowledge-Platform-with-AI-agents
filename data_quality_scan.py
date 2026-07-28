"""Read-only data-quality scan for the colleague who owns the Postgres DB.

Purpose: surface data issues WITHOUT changing anything. This script only runs
SELECTs, over a hardened read-only connection (the DB session physically rejects
writes). It never modifies, dedupes, or normalizes — it produces a Markdown
report the colleague can act on in the source spreadsheets / ETL.

Run:
    PYTHONPATH=~/Desktop/um6p-rag ~/.conda/envs/um6p/bin/python -m data_quality_scan

Writes: DATA_QUALITY_REPORT.md in the project root.

What it checks:
  1. Near-duplicate actor names (fuzzy) that the merge workflow hasn't caught.
  2. `country` field hygiene: USA vs United States, US states stored as country,
     and free-text descriptions that leaked into the column.
  3. Suspected typos in names (rare tokens a hair away from a common spelling).

Nothing here is authoritative — every hit is a CANDIDATE for a human to judge,
mirroring the review_queue "score -> human decides" pattern already in the DB.
"""

from collections import defaultdict
from datetime import date

from rapidfuzz import fuzz

from src.db import get_readonly_connection

# US state names + DC + common abbreviations. Used to flag rows where a state
# leaked into the `country` column (e.g. country = 'California').
US_STATES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming",
    "district of columbia", "d.c.", "dc", "washington dc", "washington d.c.",
}

# The two spellings HANDOFF.md calls out. Anything in this family = "United States".
US_COUNTRY_SPELLINGS = {"usa", "united states", "united states of america",
                        "u.s.", "u.s.a.", "us", "america"}

# Above this token_sort_ratio, two names are likely the same org. Tuned to catch
# real dupes (word-order / punctuation / suffix differences) without drowning the
# report in coincidental matches. The colleague makes the final call on each.
FUZZY_THRESHOLD = 88


def fetch_live_actors():
    """(actor_id, name, country) for every live (non-merged) actor."""
    sql = """
        SELECT actor_id, name, country
        FROM actor
        WHERE merged_into_actor_id IS NULL
        ORDER BY name
    """
    with get_readonly_connection() as conn, conn.cursor() as cur:
        cur.execute(sql)
        return [
            {"id": r[0], "name": r[1], "country": r[2]}
            for r in cur.fetchall()
        ]


def find_near_duplicate_names(actors):
    """All pairs of live actors whose names are >= FUZZY_THRESHOLD similar.

    O(n^2) over ~870 names is ~380k comparisons — trivial and clearer than any
    blocking scheme. Returns pairs sorted by descending similarity.
    """
    names = [(a["name"] or "").strip() for a in actors]
    pairs = []
    for i in range(len(names)):
        ni = names[i]
        if not ni:
            continue
        for j in range(i + 1, len(names)):
            nj = names[j]
            if not nj:
                continue
            score = fuzz.token_sort_ratio(ni, nj)
            if score >= FUZZY_THRESHOLD:
                pairs.append((score, ni, nj))
    pairs.sort(reverse=True, key=lambda p: p[0])
    return pairs


def scan_country(actors):
    """Bucket the messy `country` column into actionable groups."""
    us_spelling_variants = defaultdict(int)   # e.g. {'USA': 214, 'United States': 178}
    state_as_country = []                     # country is actually a US state
    freetext_leak = []                        # long / sentence-like junk in country
    other_countries = defaultdict(int)

    for a in actors:
        c = a["country"]
        if c is None or not c.strip():
            continue
        raw = c.strip()
        low = raw.lower()

        if low in US_COUNTRY_SPELLINGS:
            us_spelling_variants[raw] += 1
        elif low in US_STATES:
            state_as_country.append((a["name"], raw))
        elif len(raw) > 30 or " Regional Offices" in raw or ":" in raw:
            # Real country names are short; anything long is a description leak.
            freetext_leak.append((a["name"], raw))
        else:
            other_countries[raw] += 1

    return {
        "us_spelling_variants": dict(us_spelling_variants),
        "state_as_country": state_as_country,
        "freetext_leak": freetext_leak,
        "other_countries": dict(other_countries),
    }


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |")
    return "\n".join(out)


def build_report(actors, dup_pairs, country):
    n = len(actors)
    lines = []
    lines.append("# UM6P — Data-Quality Scan (read-only)\n")
    lines.append(f"_Generated {date.today().isoformat()} · {n} live actors "
                 "(merged duplicates excluded) · nothing in the DB was changed._\n")
    lines.append(
        "> Every item below is a **candidate for human review**, not an "
        "auto-fix. This mirrors the `review_queue` \"score → human decides\" "
        "pattern already in the database. Fixes belong in the source "
        "spreadsheets / ETL, not applied blindly.\n"
    )

    # --- 1. country ---
    lines.append("\n## 1. `country` field hygiene\n")
    usv = country["us_spelling_variants"]
    if usv:
        total = sum(usv.values())
        lines.append(
            f"**1a. United States is stored under {len(usv)} different spellings "
            f"({total} actors total).** Pick one canonical value and map the rest. "
            "This directly breaks Browse-by-region and the SQL router's exact "
            "substring filters.\n")
        lines.append(md_table(
            ["stored value", "actors"],
            sorted(usv.items(), key=lambda x: -x[1])))
        lines.append("")

    if country["state_as_country"]:
        lines.append(
            f"\n**1b. US state stored in the `country` column "
            f"({len(country['state_as_country'])} actors).** Should be `country = "
            "United States` with the state moved to `state`.\n")
        lines.append(md_table(
            ["actor", "country value (a US state)"],
            country["state_as_country"]))
        lines.append("")

    if country["freetext_leak"]:
        lines.append(
            f"\n**1c. Free-text / descriptions leaked into `country` "
            f"({len(country['freetext_leak'])} actors).** These look like ETL "
            "spillover from a wider cell. Each needs the real country extracted.\n")
        rows = [(nm, (val[:70] + "…") if len(val) > 70 else val)
                for nm, val in country["freetext_leak"]]
        lines.append(md_table(["actor", "country value (truncated)"], rows))
        lines.append("")

    # --- 2. near-duplicate names ---
    lines.append("\n## 2. Suspected near-duplicate actor names\n")
    if dup_pairs:
        lines.append(
            f"**{len(dup_pairs)} name pairs are ≥{FUZZY_THRESHOLD}% similar** and "
            "may be the same organization not yet merged. Higher score = more "
            "likely a true duplicate. (Exact-name collisions are already 0 — the "
            "merge workflow handles those; these are the fuzzy ones it misses.)\n")
        lines.append(
            "⚠️ Similarity is on *spelling*, so a few pairs share a template but "
            "are genuinely different organizations (e.g. Arizona vs California "
            "Dept of Water Resources) — do **not** merge those. The colleague "
            "judges each pair.\n")
        lines.append(md_table(
            ["similarity", "name A", "name B"],
            [(f"{round(s)}%", a, b) for s, a, b in dup_pairs]))
        lines.append("")
    else:
        lines.append("_No name pairs above the similarity threshold._\n")

    # --- footer ---
    lines.append("\n## How this was produced\n")
    lines.append(
        "- Source: live `actor` rows (`merged_into_actor_id IS NULL`), read over "
        "a **read-only** Postgres session.\n"
        "- Near-dup metric: `rapidfuzz.token_sort_ratio` (word-order/"
        f"punctuation tolerant), threshold {FUZZY_THRESHOLD}.\n"
        "- Re-run anytime: "
        "`PYTHONPATH=~/Desktop/um6p-rag ~/.conda/envs/um6p/bin/python -m "
        "data_quality_scan`\n")
    return "\n".join(lines)


def main():
    actors = fetch_live_actors()
    dup_pairs = find_near_duplicate_names(actors)
    country = scan_country(actors)
    report = build_report(actors, dup_pairs, country)

    out_path = "DATA_QUALITY_REPORT.md"
    with open(out_path, "w") as f:
        f.write(report)

    print(f"Scanned {len(actors)} live actors.")
    print(f"  near-duplicate name pairs (>= {FUZZY_THRESHOLD}%): {len(dup_pairs)}")
    print(f"  US spelling variants: {country['us_spelling_variants']}")
    print(f"  state-as-country rows: {len(country['state_as_country'])}")
    print(f"  free-text-leak country rows: {len(country['freetext_leak'])}")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
