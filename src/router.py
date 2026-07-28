"""SQL side-path (v0.2). Route counting / aggregation / membership questions to
SQL instead of RAG.

Why this exists: RAG retrieves ~10 chunks, so it structurally cannot count or
list-all — it undercounts (the assessment showed "8" for a hub that has 14, and
"4" for a TRL filter that has 34). Structured questions instead have Claude write
a read-only SELECT, which Postgres executes for an EXACT, authoritative answer.

Flow:
    question -> plan() -> ("sql", <SELECT>)  or  ("semantic", None)
         if sql:  is_safe_select() -> run_sql() -> format_sql_answer()
         else:    caller falls back to the RAG path (retrieve + generate)

Safety (this runs LLM-written SQL against a colleague's DB — belt AND braces):
    1. Executed on a READ-ONLY session with an 8s timeout (db.get_readonly_connection).
    2. Validated here to be a single SELECT with no write/DDL keywords.
Either guard alone blocks writes; both together make it safe.
"""

import re

from src.db import get_readonly_connection
from src.generate import _get_client, MODEL

# A compact schema so Claude writes correct SQL. Only the tables useful for
# counting/filtering — with the gotchas that matter for correctness.
SCHEMA = """\
Postgres schema (answer with standard PostgreSQL). Key tables and columns:

actor(actor_id uuid PK, name text, actor_type text, description text,
      location_city text, state text, country text, estimated_trl smallint,
      verification_status text, merged_into_actor_id uuid)
  - IMPORTANT: only rows WHERE merged_into_actor_id IS NULL are live; ALWAYS
    add that filter when counting/listing actors (the rest are merged duplicates).
  - estimated_trl is 1..9 or NULL. verification_status in
    ('ai_inferred','phase_1','needs_review'). country is free text and
    inconsistent ('USA' vs 'United States') — match with ILIKE/IN when needed.

hub(hub_id uuid PK, name text, primary_city text, state text, country text, region text)

hub_actor(hub_id uuid, actor_id uuid, relationship_type text, is_primary bool)
  - many-to-many: which live actors belong to which hub. Join actor to exclude merged.

event(event_id uuid PK, name text, event_type text, location text,
      next_date date, host_actor_id uuid)

partnership_profile(actor_id uuid, why_valuable_for_um6p text,
      africa_specific_mandate text, key_entry_points text)   -- ~1 row per profiled actor

actor_relevance(actor_id uuid, challenge_id uuid, relevance_score numeric, why_relevant text)
challenge(challenge_id uuid PK, name text)
"""

PLANNER_SYSTEM = f"""You route questions about a research database to the right \
engine. {SCHEMA}

Decide which kind of question this is:

- STRUCTURED — answerable by an exact SQL query: counts ("how many..."), \
aggregations, filters by a structured field (TRL, type, country, hub membership), \
"which X have/lack Y", "list all X in Y". For these, write ONE read-only SELECT.

- SEMANTIC — about meaning, topics, descriptions, or "why valuable" — better \
served by document search. Examples: "who works on phosphogypsum?", "tell me \
about Mosaic", "which labs research soil health?".

Respond in EXACTLY one of two ways:
- If STRUCTURED: output only a single SQL statement inside a ```sql code block. \
Use a SELECT only. Always filter actor.merged_into_actor_id IS NULL when \
counting/listing actors. Add a LIMIT (<=100) to list queries.

  CRITICAL name-matching rule: when filtering by a name (hub, actor, event), you \
MUST use ILIKE with surrounding wildcards on the SHORTEST distinctive fragment, \
e.g. `h.name ILIKE '%California Water%'`. Names in this database carry suffixes \
like 'California Water Hub (UC Davis - Berkeley - Stanford)', so an exact match, \
`=`, or ILIKE without `%` wildcards will WRONGLY return 0. Never match a full \
name literally; always wrap a distinctive fragment in `%...%`.
- If SEMANTIC: output only the single word SEMANTIC (nothing else)."""

# Anything that isn't a plain read: reject before it reaches the database.
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|"
    r"merge|call|do|vacuum|reindex)\b", re.IGNORECASE)
_SQL_FENCE = re.compile(r"```sql\s*(.*?)```", re.IGNORECASE | re.DOTALL)


def _extract_sql(text: str) -> str | None:
    m = _SQL_FENCE.search(text)
    if m:
        return m.group(1).strip().rstrip(";").strip()
    return None


def plan(question: str) -> tuple[str, str | None]:
    """Return ("sql", <query>) for structured questions, else ("semantic", None)."""
    resp = _get_client().messages.create(
        model=MODEL,
        max_tokens=600,
        system=PLANNER_SYSTEM,
        messages=[{"role": "user", "content": question}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    sql = _extract_sql(text)
    if sql and is_safe_select(sql):
        return "sql", sql
    return "semantic", None


def is_safe_select(sql: str) -> bool:
    """Guard #2 (guard #1 is the read-only DB session): allow only a single
    SELECT/WITH statement with no write or DDL keywords."""
    s = sql.strip().rstrip(";").strip()
    if ";" in s:                       # no stacked statements
        return False
    if not re.match(r"^(select|with)\b", s, re.IGNORECASE):
        return False
    if _FORBIDDEN.search(s):
        return False
    return True


def run_sql(sql: str) -> tuple[list[str], list[tuple]]:
    """Execute on the read-only session. Returns (column_names, rows)."""
    with get_readonly_connection() as conn, conn.cursor() as cur:
        cur.execute(sql)
        cols = [c.name for c in cur.description] if cur.description else []
        rows = cur.fetchmany(200)      # hard cap on rows returned
    return cols, rows


def format_sql_answer(question: str, sql: str, cols: list[str],
                      rows: list[tuple]) -> str:
    """Phrase the query result as a concise answer. The number/list is EXACT
    (it came straight from the database), so the answer can be authoritative."""
    table = " | ".join(cols) + "\n" + "\n".join(
        " | ".join(str(v) for v in r) for r in rows[:100])
    resp = _get_client().messages.create(
        model=MODEL,
        max_tokens=800,
        system=(
            "You state the result of a database query in plain English. The "
            "numbers are exact (computed directly from the database), so be "
            "definitive — do not hedge about completeness. Lead with the answer. "
            "If the result is a list, present it clearly. If the result is empty "
            "or zero, say so, and note it may mean nothing in the database matched "
            "the filter (for example, a name that isn't in the database) rather "
            "than asserting a true count of zero."
        ),
        messages=[{"role": "user", "content":
                   f"Question: {question}\n\nSQL run:\n{sql}\n\nResult:\n{table}"}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def sql_answer(question: str, sql: str) -> str:
    """Convenience: run a planned SQL query and return the phrased answer."""
    cols, rows = run_sql(sql)
    return format_sql_answer(question, sql, cols, rows)


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "How many actors are at TRL 6 or above?"
    mode, sql = plan(q)
    print(f"Q: {q}\nrouted to: {mode}")
    if mode == "sql":
        print(f"\nSQL:\n{sql}\n")
        print(sql_answer(q, sql))
    else:
        print("(would use the RAG semantic path)")
