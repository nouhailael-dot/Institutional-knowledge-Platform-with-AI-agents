"""Stage 1 — the gap worklist. READ-ONLY, zero cost.

Which live actors are missing which enrichable factual field, with enough
context (type, location, hubs) for the agent to identify the right entity.
This sizes the work and is the exact input the agent consumes.

Enrichable factual fields for Task 1A. Deliberately factual-only — judgment
fields (why_valuable_for_um6p, relevance scores, TRL) stay human-written.
"""

from src.db import get_readonly_connection

# field -> the SQL "missing" predicate for that column on the actor table
FIELDS = {
    "website": "website IS NULL OR btrim(website) = ''",
    "country": "country IS NULL OR btrim(country) = ''",
}

LIVE = "a.merged_into_actor_id IS NULL"


def _missing_clause(field: str) -> str:
    if field not in FIELDS:
        raise ValueError(f"unknown field {field!r}; known: {sorted(FIELDS)}")
    return FIELDS[field].replace("website", "a.website").replace("country", "a.country")


def find_gaps(field: str, limit: int | None = None,
              tiers: tuple[str, ...] = ("ai_inferred", "phase_1", "needs_review")):
    """Live actors missing `field`, newest-curated first, with hub context.

    Returns a list of dicts: actor_id, name, actor_type, city, state, country,
    website, verification_status, hubs (comma-joined names). The current value
    of the target field is included so the agent can see "what's there now".
    """
    sql = f"""
        SELECT a.actor_id, a.name, a.actor_type,
               a.location_city, a.state, a.country, a.website,
               a.verification_status,
               COALESCE(string_agg(DISTINCT h.name, ' | '), '') AS hubs
        FROM actor a
        LEFT JOIN hub_actor ha ON ha.actor_id = a.actor_id
        LEFT JOIN hub h        ON h.hub_id = ha.hub_id
        WHERE {LIVE}
          AND a.verification_status = ANY(%(tiers)s)
          AND ({_missing_clause(field)})
        GROUP BY a.actor_id
        ORDER BY a.verification_status, a.name
    """
    if limit is not None:
        sql += "\n        LIMIT %(limit)s"
    args = {"tiers": list(tiers), "limit": limit}
    with get_readonly_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, args)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def summarize():
    """Print the gap counts by field and tier — the read-only scan."""
    with get_readonly_connection() as conn, conn.cursor() as cur:
        for field, pred in FIELDS.items():
            clause = pred.replace("website", "a.website").replace("country", "a.country")
            cur.execute(f"""
                SELECT COALESCE(a.verification_status,'(null)'),
                       count(*) FILTER (WHERE {clause}) AS missing,
                       count(*) AS total
                FROM actor a WHERE {LIVE}
                GROUP BY 1 ORDER BY 3 DESC
            """)
            print(f"\n=== missing {field} (live actors, by tier) ===")
            grand_miss = grand_tot = 0
            for tier, miss, tot in cur.fetchall():
                grand_miss += miss; grand_tot += tot
                print(f"  {tier:14} {miss:4} / {tot}")
            print(f"  {'TOTAL':14} {grand_miss:4} / {grand_tot}")


if __name__ == "__main__":
    summarize()
