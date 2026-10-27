"""Browse — structured, filterable lists of the map's entities.

The Ask tab answers a question; Browse lets you *walk* the data: "show me the
startups in the Bay Area AI Hub".

Reads actors through `actor_read`, the Architecture V2 read view (migrated
6 Oct 2026): the 12-category code is shown by its display name and the state
code by its full name. The API keeps its pre-V2 keys (`actor_type`, `state`,
`verification_status`) so the page did not have to change.

  - We browse the dimensions that are POPULATED: hub membership, category and
    status. Sector is not offered (the sector table is empty); TRL and country
    are optional refinements (TRL is set on few actors; country is messy).
  - All filtering happens in memory. The live actor set is <1000 rows, so one
    read-only query + Python filtering is simpler and more robust than building
    WHERE clauses over the inconsistent `country` values.

Pure data, runnable on its own:  python -m src.browse
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
    # Architecture V2 status (actor.status); every migrated actor is verified.
    "verified": "✅ Verified",
    "imported": "📥 Imported",
    "parked": "🅿️ Parked",
    "rejected": "⛔ Rejected",
    # Legacy verification_status values, read until the V2 cutover.
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
    # actor_read is the Architecture V2 read view: it excludes rejected records
    # (the 153 "collection of organizations" placeholders GHUS rejected) and
    # brings the descriptive fields back from actor_fact. TRL arrives from the
    # fact store, so it is cast defensively rather than trusted to be a number.
    sql = f"""
        SELECT a.actor_id, a.name,
               coalesce(cd.display_name, a.actor_category) AS category,
               NULLIF(to_jsonb(a)->>'category_type', '') AS category_type,
               -- Migration 500 drops verification_status, estimated_trl and
               -- renames location_city -> city, state -> state_code, so each is
               -- read through to_jsonb. V2 status is authoritative.
               COALESCE(NULLIF(to_jsonb(a)->>'status', ''),
                        NULLIF(to_jsonb(a)->>'verification_status', '')) AS verification_status,
               COALESCE(NULLIF(to_jsonb(a)->>'location_city', ''),
                        NULLIF(to_jsonb(a)->>'city', '')) AS location_city,
               coalesce(rs.state_name,
                        NULLIF(to_jsonb(a)->>'state', ''),
                        NULLIF(to_jsonb(a)->>'state_code', '')) AS state,
               a.country,
               CASE WHEN to_jsonb(a)->>'estimated_trl' ~ '^[0-9]+$'
                    THEN (to_jsonb(a)->>'estimated_trl')::smallint END AS trl,
               a.website, a.description,
               (pp.why_valuable_for_um6p IS NOT NULL
                AND btrim(pp.why_valuable_for_um6p) <> '') AS has_profile,
               (SELECT string_agg(h.name, '{_HUB_SEP}')
                  FROM hub_actor ha JOIN hub h ON h.hub_id = ha.hub_id
                 WHERE ha.actor_id = a.actor_id) AS hub_names
        FROM actor_read a
        LEFT JOIN actor_category_definition cd ON cd.category_code = a.actor_category
        LEFT JOIN region_state rs ON rs.state_code = a.state_code
        LEFT JOIN partnership_profile pp ON pp.actor_id = a.actor_id
        WHERE a.merged_into_actor_id IS NULL
          -- GHUS-rejected records (e.g. collections of organizations) are not on the map.
          AND COALESCE(to_jsonb(a)->>'status', '') <> 'rejected'
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
                # Category display name under the pre-V2 key, so Browse shows
                # guide names rather than codes.
                "actor_type": r["category"],
                "category_type": r["category_type"],
                "verification_status": r["verification_status"],
                "city": r["location_city"],
                "state": r["state"],
                "country_raw": r["country"],
                "country": normalize_country(r["country"]),
                "trl": r["trl"],
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


def load_people() -> list[dict]:
    """Every person in the database who is not rejected, with their current
    organizations (live actors only), those organizations' locations, and topics.

    Read-only. Email and phone are never selected: Browse is a directory, and the
    people-privacy rules keep contact details out of general views."""
    sql = f"""
        SELECT p.person_id, p.full_name, p.title, p.orcid, p.linkedin_url,
               COALESCE(NULLIF(p.record_status, ''), p.verification_status) AS status,
               (SELECT string_agg(DISTINCT a.name, '{_HUB_SEP}')
                  FROM actor_person ap JOIN actor_read a ON a.actor_id = ap.actor_id
                 WHERE ap.person_id = p.person_id AND ap.is_current IS NOT FALSE
                   AND a.merged_into_actor_id IS NULL) AS organizations,
               (SELECT string_agg(DISTINCT coalesce(rs.state_name, a.state_code), '{_HUB_SEP}')
                  FROM actor_person ap JOIN actor_read a ON a.actor_id = ap.actor_id
                  LEFT JOIN region_state rs ON rs.state_code = a.state_code
                 WHERE ap.person_id = p.person_id AND ap.is_current IS NOT FALSE
                   AND a.merged_into_actor_id IS NULL) AS states,
               (SELECT string_agg(DISTINCT t.name, '{_HUB_SEP}')
                  FROM person_topic pt JOIN topic t ON t.topic_id = pt.topic_id
                 WHERE pt.person_id = p.person_id) AS topics,
               (SELECT string_agg(DISTINCT d.research_area, '{_HUB_SEP}')
                  FROM person_discovery_profile d
                 WHERE d.person_id = p.person_id AND d.research_area IS NOT NULL) AS research_areas,
               (SELECT d.public_profile_url FROM person_discovery_profile d
                 WHERE d.person_id = p.person_id AND d.public_profile_url IS NOT NULL
                 ORDER BY d.fetched_at DESC NULLS LAST LIMIT 1) AS profile_url
        FROM person p
        WHERE COALESCE(p.record_status, '') <> 'rejected'
          AND COALESCE(p.verification_status, '') <> 'rejected'
        ORDER BY p.full_name
    """
    split = lambda value: value.split(_HUB_SEP) if value else []
    out = []
    with get_readonly_connection() as conn, conn.cursor() as cur:
        cur.execute(sql)
        cols = [c.name for c in cur.description]
        for row in cur.fetchall():
            r = dict(zip(cols, row))
            out.append({
                "id": str(r["person_id"]),
                "name": r["full_name"],
                "title": r["title"],
                "status": r["status"],
                "organizations": split(r["organizations"]),
                "states": split(r["states"]),
                "topics": split(r["topics"]),
                "research_areas": split(r["research_areas"]),
                "profile_url": r["profile_url"] or r["linkedin_url"],
                "orcid": r["orcid"],
            })
    return out


def people_filter_options(people: list[dict]) -> dict:
    """Dropdown values for the People filters, each sorted."""
    pick = lambda key: sorted({v for p in people for v in p[key] if v})
    return {"organizations": pick("organizations"), "states": pick("states"),
            "topics": pick("topics")}


def filter_people(people: list[dict], *, organization: str | None = None,
                  state: str | None = None, topic: str | None = None,
                  text: str | None = None) -> list[dict]:
    """Organization/state/topic are exact values from the dropdowns; `text` is a
    case-insensitive match on name, title, topics and research areas."""
    result = people
    if organization:
        result = [p for p in result if organization in p["organizations"]]
    if state:
        result = [p for p in result if state in p["states"]]
    if topic:
        result = [p for p in result if topic in p["topics"]]
    if text:
        needle = text.strip().lower()
        result = [p for p in result if needle in " ".join(
            [p["name"] or "", p["title"] or "", *p["topics"], *p["research_areas"]]).lower()]
    return result


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
        result = [
            a for a in result
            if (a.get("actor_category") or a.get("actor_type")) in types
        ]
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
        category = a.get("actor_category") or a.get("actor_type")
        if category:
            type_counts[category] = type_counts.get(category, 0) + 1
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
    startups = filter_actors(actors, types=["Startup / Emerging Technology Company"])
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
