"""Browse — structured, filterable lists of the map's entities.

The Ask tab answers a question; Browse lets you *walk* the data: "show me the
startups in the Bay Area AI Hub", "show me everything that's still AI-inferred".

Design choices driven by what the data actually supports (see HANDOFF.md §8):
  - We browse the dimensions that are POPULATED: hub membership, actor category, and
    verification_status. We deliberately DO NOT offer browse-by-sector (the sector
    table is empty) and we treat TRL/country as optional refinements, not primary
    axes (TRL is set on only ~8% of actors; country is messy).
  - verification_status is surfaced as a first-class column, so an AI-inferred
    actor never looks as authoritative as a hand-verified one. This is the
    "surface trust" principle from the spec, applied to Browse.
  - All filtering happens in memory. The whole live actor set is <1000 rows, so
    one cached read-only query + Python filtering is simpler and more robust than
    building WHERE clauses over the inconsistent `country` values.

This module is pure data (no Streamlit) so it can be run/tested on its own:
    PYTHONPATH=~/Desktop/um6p-rag python -m src.browse
Caching lives in app.py (st.cache_data), same split as retrieve.py / generate.py.
"""

from uuid import UUID

from src.db import get_readonly_connection

# hub names contain commas, so we join them with a delimiter that can't appear in
# the data and split it back in Python.
_HUB_SEP = "||"

# Friendly, trust-ordered labels for verification_status. Used by the UI and as
# the canonical vocabulary for the Browse trust filter. Order = most to least
# trustworthy, which is also the order we show them in.
VERIFICATION_LABELS = {
    "phase_1": "✅ Verified",
    "needs_review": "🔶 Needs review",
    "ai_inferred": "⚠️ AI-inferred",
    None: "— unset",
}


def verification_label(status: str | None) -> str:
    """Human label for a raw verification_status (falls back to the raw value)."""
    return VERIFICATION_LABELS.get(status, status or "— unset")


# --- country normalization -------------------------------------------------
# The `country` column is inconsistent (see the data-quality scan): 'USA' vs
# 'United States', US states mislabeled as countries, and free-text leaks. We
# canonicalize on READ for browsing only — the database is never modified.

_US_STATES = {
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
_CLEAN_COUNTRIES = {
    "india", "brazil", "switzerland", "canada", "italy", "united kingdom",
    "france", "austria", "ethiopia", "kenya", "new zealand",
}


def normalize_country(raw: str | None) -> str | None:
    """Best-effort canonical country for browsing. Returns None if we can't tell.

    Not authoritative — a display convenience. Anything US-flavored collapses to
    'United States'; recognizable foreign countries pass through; messy free-text
    that we can't confidently classify returns None (shown as 'Unknown')."""
    if not raw or not raw.strip():
        return None
    low = raw.strip().lower()
    if (low in {"usa", "united states", "united states of america", "u.s.",
                "u.s.a.", "us", "america"}
            or low in _US_STATES
            or low.startswith("usa ")
            or "united states" in low):
        return "United States"
    if low in _CLEAN_COUNTRIES:
        return raw.strip().title() if low != "united kingdom" else "United Kingdom"
    # startswith match for the "India; major operations..." style leaks
    for c in _CLEAN_COUNTRIES:
        if low.startswith(c):
            return c.title() if c != "united kingdom" else "United Kingdom"
    return None


# --- loaders ---------------------------------------------------------------

def load_actors() -> list[dict]:
    """Every live actor with the fields Browse needs. One read-only query.

    `has_profile` marks the ~28 deeply-profiled actors — those with a
    'why valuable for UM6P' write-up. These are the hand-curated, richest
    records, so Browse lets you filter down to just them."""
    sql = f"""
        SELECT a.actor_id, a.name,
               COALESCE(to_jsonb(a)->>'actor_category',
                        to_jsonb(a)->>'actor_type') AS actor_category,
               to_jsonb(a)->>'category_type' AS category_type,
               a.verification_status,
               a.location_city, a.state, a.country, a.estimated_trl,
               a.website, a.description,
               (pp.why_valuable_for_um6p IS NOT NULL
                AND btrim(pp.why_valuable_for_um6p) <> '') AS has_profile,
               (SELECT string_agg(h.name, '{_HUB_SEP}')
                  FROM hub_actor ha JOIN hub h ON h.hub_id = ha.hub_id
                 WHERE ha.actor_id = a.actor_id) AS hub_names
        FROM actor a
        LEFT JOIN partnership_profile pp ON pp.actor_id = a.actor_id
        WHERE a.merged_into_actor_id IS NULL
        ORDER BY a.name
    """
    out = []
    with get_readonly_connection() as conn, conn.cursor() as cur:
        cur.execute(sql)
        cols = [c.name for c in cur.description]
        for row in cur.fetchall():
            r = dict(zip(cols, row))
            hubs = r["hub_names"].split(_HUB_SEP) if r["hub_names"] else []
            out.append({
                "id": str(r["actor_id"]),
                "name": r["name"],
                "actor_category": r["actor_category"],
                "category_type": r["category_type"],
                # Temporary response alias for Agent 3/older clients. Remove at cutover.
                "actor_type": r["actor_category"],
                "verification_status": r["verification_status"],
                "city": r["location_city"],
                "state": r["state"],
                "country_raw": r["country"],
                "country": normalize_country(r["country"]),
                "trl": r["estimated_trl"],
                "website": r["website"],
                "description": r["description"],
                "has_profile": bool(r["has_profile"]),
                "hubs": hubs,
            })
    return out


def load_hubs() -> list[dict]:
    """Every hub with EVERY column from the hub table (plus a live-actor count).

    Browse shows the full record, so we SELECT * and pass all columns through.
    Array columns (primary_sectors, secondary_sectors) are joined to a string for
    display; everything else is returned as-is."""
    sql = """
        SELECT h.*,
               (SELECT count(*) FROM hub_actor ha JOIN actor a
                  ON a.actor_id = ha.actor_id AND a.merged_into_actor_id IS NULL
                 WHERE ha.hub_id = h.hub_id) AS actor_count
        FROM hub h ORDER BY h.name
    """
    out = []
    with get_readonly_connection() as conn, conn.cursor() as cur:
        cur.execute(sql)
        cols = [c.name for c in cur.description]
        for row in cur.fetchall():
            r = dict(zip(cols, row))
            for k, v in r.items():
                if isinstance(v, list):          # Postgres ARRAY columns
                    r[k] = ", ".join(str(x) for x in v)
                elif isinstance(v, UUID):        # else Arrow renders it as junk
                    r[k] = str(v)
            out.append(r)
    return out


def hub_columns() -> list[str]:
    """Ordered column names for the hub table, for laying out the Browse view."""
    with get_readonly_connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT column_name FROM information_schema.columns
                       WHERE table_name = 'hub' ORDER BY ordinal_position""")
        return [r[0] for r in cur.fetchall()]


def load_events() -> list[dict]:
    sql = """
        SELECT event_id, name, event_type, location, next_date
        FROM event ORDER BY name
    """
    out = []
    with get_readonly_connection() as conn, conn.cursor() as cur:
        cur.execute(sql)
        cols = [c.name for c in cur.description]
        for row in cur.fetchall():
            r = dict(zip(cols, row))
            out.append({
                "id": str(r["event_id"]),
                "name": r["name"],
                "event_type": r["event_type"],
                "location": r["location"],
                "next_date": r["next_date"],
            })
    return out


# --- filtering (pure, in memory) -------------------------------------------

def filter_actors(actors: list[dict], *, hub: str | None = None,
                  types: list[str] | None = None,
                  country: str | None = None,
                  state: str | None = None,
                  min_trl: int | None = None,
                  profiled_only: bool = False,
                  text: str | None = None) -> list[dict]:
    """Apply the Browse filters. Any arg left None/empty/False is ignored.

    `hub`/`country`/`state` are exact matches on values the UI got from this same
    data, so no fuzzy logic is needed. `min_trl` keeps actors with a TRL >= the
    given value (actors with no TRL are dropped, as they can't meet the bar).
    `profiled_only` keeps only the deeply-profiled actors. `text` is a
    case-insensitive name/description substring."""
    result = actors
    if hub:
        result = [a for a in result if hub in a["hubs"]]
    if types:
        result = [a for a in result if a.get("actor_category", a.get("actor_type")) in types]
    if country:
        result = [a for a in result if a["country"] == country]
    if state:
        result = [a for a in result if a["state"] == state]
    if min_trl:
        result = [a for a in result if a["trl"] is not None and a["trl"] >= min_trl]
    if profiled_only:
        result = [a for a in result if a["has_profile"]]
    if text:
        t = text.strip().lower()
        result = [a for a in result
                  if t in (a["name"] or "").lower()
                  or t in (a["description"] or "").lower()]
    return result


def filter_events(events: list[dict], *, location: str | None = None,
                  date_from=None, date_to=None) -> list[dict]:
    """Filter events by a location substring and/or a next_date range.

    `location` is a case-insensitive substring (the location column is free text,
    e.g. 'New York, USA' vs 'New York City, New York, USA', so a substring match
    is what catches all variants). When a date bound is given, events with no
    next_date are dropped — they can't fall inside a range."""
    result = events
    if location:
        loc = location.strip().lower()
        result = [e for e in result if loc in (e["location"] or "").lower()]
    if date_from:
        result = [e for e in result
                  if e["next_date"] is not None and e["next_date"] >= date_from]
    if date_to:
        result = [e for e in result
                  if e["next_date"] is not None and e["next_date"] <= date_to]
    return result


def event_date_bounds(events: list[dict]):
    """(earliest, latest) next_date across events, or (None, None) if none set."""
    dates = [e["next_date"] for e in events if e["next_date"] is not None]
    return (min(dates), max(dates)) if dates else (None, None)


def actor_filter_options(actors: list[dict]) -> dict:
    """The distinct values to populate the Browse dropdowns, each sorted.

    Types are ordered by frequency (most common first); hubs, countries and
    states alphabetically."""
    type_counts: dict[str, int] = {}
    hubs: set[str] = set()
    countries: set[str] = set()
    states: set[str] = set()
    for a in actors:
        actor_category = a.get("actor_category", a.get("actor_type"))
        if actor_category:
            type_counts[actor_category] = type_counts.get(actor_category, 0) + 1
        hubs.update(a["hubs"])
        if a["country"]:
            countries.add(a["country"])
        if a["state"] and a["state"].strip():
            states.add(a["state"].strip())
    types = sorted(type_counts, key=lambda t: (-type_counts[t], t))
    return {
        "types": types,
        "hubs": sorted(hubs),
        "countries": sorted(countries),
        "states": sorted(states),
    }


if __name__ == "__main__":
    actors = load_actors()
    opts = actor_filter_options(actors)
    print(f"Loaded {len(actors)} live actors, {len(load_hubs())} hubs, "
          f"{len(load_events())} events.")
    print(f"Actor types: {len(opts['types'])}  ·  hubs: {len(opts['hubs'])}  ·  "
          f"countries: {opts['countries']}")
    # Spot-check a few filter combos.
    startups = filter_actors(actors, types=["startup"])
    print(f"\nStartups: {len(startups)} (first 3: "
          f"{[a['name'] for a in startups[:3]]})")
    trl6 = filter_actors(actors, min_trl=6)
    print(f"TRL 6+: {len(trl6)}")
    profiled = filter_actors(actors, profiled_only=True)
    print(f"Deeply-profiled actors: {len(profiled)}")
    print(f"States available: {len(opts['states'])}")

    events = load_events()
    lo, hi = event_date_bounds(events)
    ny = filter_events(events, location="new york")
    dated = filter_events(events, date_from=lo, date_to=hi)
    print(f"\nEvents in 'new york': {len(ny)}  ·  date range {lo}..{hi}  ·  "
          f"with a date in range: {len(dated)}")
