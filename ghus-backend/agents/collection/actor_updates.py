"""Update an actor already on the map: plan, check its own pages, then apply.

    python -m agents.collection.actor_updates plan  --actor-id ID [options]
    python -m agents.collection.actor_updates check --actor-id ID [options]
    python -m agents.collection.actor_updates apply --check-id CHECK

    options: --topic CODE --scope topic|general|missing|outdated|specific
             --depth light|deep --fields a,b --categories funding,partnerships
             --focus "words" --max-usd 0.15

The Discovery page's "Actor updates" panel calls this through the platform's
bridge, in three steps, so a person sees what will happen before it costs or
changes anything:

``plan``  (free: no page read, no model call, nothing written)
    Which boxes the request would re-read and why the others are skipped, the
    Deep Pull gate for this exact actor and sector, the configured cost cap
    and what past updates actually cost, and a one-paragraph summary.

``check`` (one Light Refresh read, capped; nothing written to the database)
    Reads the actor's homepage, About page and one topic page
    (``light_pull_reader``: checked quotes, Light Pull evidence rules), then
    compares every box with the current fact and predicts what the Phase 11
    writer will do with it:

        new           nothing (or only "not found") recorded; the pages state it
        changed       a different value, from evidence at least as strong and
                      newer: it supersedes the current fact (history kept)
        corroborated  the pages state what is recorded (a corroboration row)
        conflict      a different value from weaker or older evidence: the
                      current value is kept and the conflict goes to Review
        protected     the current value was set by GHUS: never overwritten; a
                      pending update goes to Review
        unchanged     the pages are silent; the recorded value is kept
        not_found     the pages are silent and nothing was recorded
        not_yet_collected   in the actor's schema, never recorded, not read now

    The findings are kept for ``check_valid_hours`` under agents/runs so the
    apply step writes exactly what was checked, without paying for a second
    read.

``apply`` (writes)
    Records the run in ``collection_request``/``collection_run`` (the existing
    run ledger: cost, pages, counts) and writes each finding through
    ``agents.enrichment.decisions.append_actor_fact`` - the approved immutable
    writer, which corroborates, supersedes, flags conflicts and raises the
    Review items. Each fact carries the run as its ``request_id``. A silent
    page never overwrites a recorded value. One failed box does not stop the
    others; applying the same check again retries only the boxes that failed.

Deep Pull (``--depth deep``) is refused unless the latest GHUS decision
verified this actor for this exact sector (``deep_pull.actor_is_verified_for_topic``);
the refusal says why and offers the Light Refresh. When permitted, the same
three steps run with the Deep boxes: ``plan`` selects at most
``deep_pull_reader.MAX_DEEP_FIELDS`` of the category's Deep schema (never all
of it), ``check`` reads them with ``deep_pull_reader.DeepPullReader``, and
``apply`` checks the gate again and writes each box as a Layer 2 fact through
``deep_pull.append_deep_pull``, under a ``deep_pull`` collection request.

Live writes against a database other than a local ``*_test`` one also need
ACTOR_UPDATE_WRITES_ENABLED=true, which only the platform bridge sets.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = ROOT / "agents" / "runs" / "actor-updates"
JOB_NAME = "actor_update"
REQUESTED_BY = "actor_updates_page"
CREATED_BY = "agent:actor_updates"

SCOPES = ("topic", "general", "missing", "outdated", "specific")
DEPTHS = ("light", "deep")

# What a person usually means by "update this actor" (kept for the CLI).
PRESETS = {
    "funding_activity": ("funding_signal", "recent_activity"),
    "connections": ("international_connection", "um6p_ocp_connection"),
}

# Change categories only ORDER the boxes and steer which topic page is read;
# they never add a box outside the actor's category schema.
CHANGE_CATEGORIES: dict[str, dict[str, tuple[str, ...]]] = {
    "research": {
        "fields": ("recent_activity", "topic_unit_and_work", "relevant_centers_programs",
                   "topic_research_focus", "active_recent_projects", "topic_program_area",
                   "current_project", "clinical_research_focus", "current_initiative",
                   "relevant_program", "current_initiative_working_group"),
        "pages": ("research", "projects", "programs"),
    },
    "funding": {
        "fields": ("funding_signal", "main_funders", "funding_stage", "published_fund_size",
                   "visible_funding_programs", "programs_grant_themes"),
        "pages": ("funding", "grants", "sponsors", "investors"),
    },
    "partnerships": {
        "fields": ("international_connection", "um6p_ocp_connection", "pilot_customer_evidence",
                   "linked_members", "parent_academic_link"),
        "pages": ("partners", "partnerships", "collaborations", "members"),
    },
    "products": {
        "fields": ("topic_business_segment_product", "technology_and_problem",
                   "published_stage_or_trl", "platform_offerings", "testing_demonstration_scope"),
        "pages": ("products", "solutions", "technology", "services"),
    },
    "organization": {
        "fields": ("ownership_and_size", "institution_control", "parent_and_center_type",
                   "sponsoring_agency", "formal_national_designation", "facility_type_operator",
                   "hospital_type_scale", "platform_type_operator", "investor_type_headquarters",
                   "jurisdiction_parent_agency", "association_type", "member_types",
                   "founding_year_location", "mission_sector_focus", "land_grant_designation",
                   "rankings", "scale_indicator"),
        "pages": ("about", "leadership", "company"),
    },
    "geography": {
        "fields": ("location", "mapped_geography_operations", "geographic_focus",
                   "sector_geographic_scope", "network_scope_locations"),
        "pages": ("locations", "offices", "contact"),
    },
}
# "category" = the boxes of the actor's own category; "all" = no preference.
CATEGORY_CHOICES = ("all", *CHANGE_CATEGORIES, "category")

# Boxes whose value dates quickly: an "outdated" update re-reads them sooner.
TIME_SENSITIVE = frozenset({
    "recent_activity", "funding_signal", "active_recent_projects", "current_project",
    "current_initiative", "funding_stage", "pilot_customer_evidence", "published_fund_size",
    "current_initiative_working_group", "rankings", "scale_indicator",
})

GROUPS = {
    "new": "new", "changed": "changed", "additional": "additional", "corroborated": "confirmed",
    "conflict": "conflicts", "protected": "conflicts", "unchanged": "no_change",
    "not_found": "missing", "not_yet_collected": "missing",
}
# What the Phase 11 writer does with each finding when it is applied.
RESOLUTION = {
    "new": "Recorded as a new sourced fact.",
    "changed": "Replaces the current value; the old value stays in the history.",
    "additional": ("Adds the new details to the recorded facts; the earlier value stays in "
                   "the history."),
    "corroborated": "The current value is kept and this source is added as corroboration.",
    "conflict": "The current value is kept; the difference goes to Review.",
    "protected": "Set by GHUS, so never overwritten; a pending update goes to Review.",
    "unchanged": "Nothing is written; the recorded value is kept.",
    "not_found": "Recorded as not found on the actor's pages.",
    "not_yet_collected": "Not read in this update.",
}
WRITTEN = frozenset({"new", "changed", "additional", "corroborated", "conflict", "protected",
                     "not_found"})

DEFAULT_SETTINGS = {
    "max_usd_per_actor": 0.15,
    "max_actors_per_request": 10,
    "max_usd_per_request_run": 1.50,
    "stale_after_days": 365,
    "time_sensitive_stale_after_days": 180,
    "recheck_not_found_after_days": 90,
    "check_valid_hours": 24,
    # When its own site refuses: its parent's official site (free), then at
    # most this many paid web searches - inside max_usd_per_actor.
    "fallback_web_searches": 1,
    "web_search_usd_per_request": 0.01,
}


class ActorUpdateError(ValueError):
    """A request that cannot run, in words the page can show."""


def settings(config: dict | None) -> dict:
    section = dict((config or {}).get("actor_updates") or {})
    return {key: section.get(key, default) for key, default in DEFAULT_SETTINGS.items()}


def _local_test_database() -> bool:
    raw = os.environ.get("DATABASE_URL", "")
    parts = urlsplit(raw.replace("postgresql+psycopg2", "postgresql")
                     .replace("postgresql+psycopg", "postgresql"))
    return parts.hostname in {"127.0.0.1", "localhost", "::1"} and parts.path.endswith("_test")


def _has_table(session, table: str) -> bool:
    return bool(session.execute(text("SELECT to_regclass(:t) IS NOT NULL"), {"t": table}).scalar())


def _has_column(session, table: str, column: str) -> bool:
    return bool(session.execute(text(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_schema = ANY (current_schemas(false)) AND table_name = :t AND column_name = :c"
    ), {"t": table, "c": column}).scalar())


# --------------------------------------------------------------------- actor

def actor_topics(session, actor_id: str) -> list[dict]:
    """The sectors (topics) this actor belongs to, by every route the schema has.

    Facts are kept per topic, so an update needs one. Imported actors have no
    direct sector link - in production none does, and hub_sector arrives only
    with migration 520 - so the routes are tried in order, each only when its
    tables exist (a failed query would abort the transaction):

        actor_sector -> sector          (direct; 520 and later)
        hub_actor -> hub_sector         (the actor's hubs' sectors; 520)
        hub_actor -> hub.topic_id       (the pre-520 hub's own topic; production)
    """
    params = {"id": actor_id}
    found: list[dict] = []
    routes = []
    if _has_table(session, "actor_sector"):
        routes.append(("sector",
            "SELECT t.topic_id::text AS topic_id, t.code, t.name FROM actor_sector x "
            "JOIN sector s ON s.sector_id = x.sector_id JOIN topic t ON t.code = s.code "
            "WHERE x.actor_id = CAST(:id AS uuid)"))
    if _has_table(session, "hub_actor") and _has_table(session, "hub_sector"):
        routes.append(("hub",
            "SELECT t.topic_id::text AS topic_id, t.code, t.name FROM hub_actor ha "
            "JOIN hub_sector hs ON hs.hub_id = ha.hub_id JOIN sector s ON s.sector_id = hs.sector_id "
            "JOIN topic t ON t.code = s.code WHERE ha.actor_id = CAST(:id AS uuid)"))
    if _has_table(session, "hub_actor") and _has_column(session, "hub", "topic_id"):
        routes.append(("hub",
            "SELECT t.topic_id::text AS topic_id, t.code, t.name FROM hub_actor ha "
            "JOIN hub h ON h.hub_id = ha.hub_id JOIN topic t ON t.topic_id = h.topic_id "
            "WHERE ha.actor_id = CAST(:id AS uuid)"))
    for source, sql in routes:
        for row in session.execute(text(sql), params).mappings():
            if not any(t["code"] == row["code"] for t in found):
                found.append({**dict(row), "source": source})
    return found


def topic_by_code(session, code: str) -> dict | None:
    row = session.execute(text(
        "SELECT topic_id::text AS topic_id, code, name FROM topic WHERE upper(code) = upper(:c)"
    ), {"c": code}).mappings().first()
    return {**dict(row), "source": "chosen"} if row else None


def load_actor(session, actor_id: str) -> dict | None:
    try:
        actor_id = str(uuid.UUID(str(actor_id)))
    except ValueError:
        return None
    row = session.execute(text(
        "SELECT a.actor_id::text AS actor_id, a.name, "
        "NULLIF(to_jsonb(a)->>'website', '') AS website, "
        "NULLIF(to_jsonb(a)->>'actor_category', '') AS actor_category, "
        "NULLIF(to_jsonb(a)->>'category_type', '') AS category_type, "
        "NULLIF(to_jsonb(a)->>'actor_type', '') AS actor_type, "
        "NULLIF(to_jsonb(a)->>'location_city', '') AS city, "
        "COALESCE(NULLIF(to_jsonb(a)->>'state_code', ''), NULLIF(to_jsonb(a)->>'state', '')) "
        "AS state, NULLIF(to_jsonb(a)->>'country', '') AS country, "
        "COALESCE(NULLIF(to_jsonb(a)->>'status', ''), NULLIF(to_jsonb(a)->>'record_status', '')) "
        "AS status FROM actor a WHERE a.actor_id = CAST(:id AS uuid)"
    ), {"id": actor_id}).mappings().first()
    if row is None:
        return None
    actor = dict(row)
    actor["topics"] = actor_topics(session, actor_id)
    return actor


def schema_fields(actor_category: str | None) -> list[str]:
    """The boxes a Light Refresh may fill for this category - and only those."""
    from agents.collection.light_pull import CATEGORY_LIGHT_FIELDS
    from agents.collection.light_pull_reader import COMMON_READ_FIELDS

    return [*COMMON_READ_FIELDS, *CATEGORY_LIGHT_FIELDS.get(actor_category or "", ())]


def current_values(session, actor_id: str, topic_id: str, keys) -> dict[str, dict]:
    """What the map holds now for each box: the current pointer's fact."""
    rows = session.execute(text(
        "SELECT p.fact_key, f.actor_fact_id::text AS actor_fact_id, f.collection_state, "
        "f.fact_value, f.confidence, f.retrieved_at, f.creator_class, f.layer, "
        "s.url AS source_url FROM actor_fact_current_pointer p "
        "JOIN actor_fact f ON f.actor_fact_id = p.actor_fact_id "
        "LEFT JOIN source s ON s.source_id = f.source_id "
        "WHERE p.actor_id = CAST(:a AS uuid) AND p.topic_id = CAST(:t AS uuid) "
        "AND p.fact_key = ANY(:keys)"
    ), {"a": actor_id, "t": topic_id, "keys": list(keys)}).mappings()
    return {r["fact_key"]: dict(r) for r in rows}


def deep_eligibility(session, *, actor_id: str, topic: dict | None) -> dict:
    """Whether Deep Pull is permitted, and why - never a bypass of the gate."""
    from agents.collection.deep_pull import actor_is_verified_for_topic

    if topic is None:
        return {"permitted": False, "reason": "No sector is chosen, and Deep Pull is "
                                              "permitted per sector."}
    if actor_is_verified_for_topic(session, actor_id=actor_id, topic_id=topic["topic_id"]):
        return {"permitted": True, "reason": f"GHUS verified this actor for {topic['name']}."}
    return {"permitted": False,
            "reason": f"GHUS has not verified this actor for {topic['name']}. Deep Pull "
                      "needs that decision for this exact sector; verify it in Review "
                      "first. A Light Refresh is permitted now."}


# ------------------------------------------------------------- field choice

def _age_days(when, today: datetime) -> int | None:
    if when is None:
        return None
    if isinstance(when, str):
        when = datetime.fromisoformat(when)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return (today - when).days


def prioritise(fields: list[str], categories) -> list[str]:
    """Boxes of the chosen change categories first; the order is otherwise kept."""
    chosen = [c for c in (categories or ()) if c in CHANGE_CATEGORIES]
    if not chosen:
        return list(fields)
    wanted = {f for c in chosen for f in CHANGE_CATEGORIES[c]["fields"]}
    return [f for f in fields if f in wanted] + [f for f in fields if f not in wanted]


def plan_fields(scope: str, schema: list[str], current: dict[str, dict], *, fields=(),
                categories=(), category_fields=(), today: datetime, limits: dict
                ) -> tuple[list[str], list[dict]]:
    """Which boxes to read, and why each other box in the schema is skipped.

    Gap-aware: "missing" reads only what is empty (or was not found long
    enough ago to look again), "outdated" only values older than the
    freshness window. Nothing outside the category's schema is ever read, so an
    inapplicable box is never mistaken for a missing one.
    """
    if scope not in SCOPES:
        raise ActorUpdateError(f"Unknown update scope {scope!r}.")
    if "category" in (categories or ()):
        categories = [*categories, "_own"]
    read: list[str] = []
    skipped: list[dict] = []
    stale_days = int(limits["stale_after_days"])
    quick_days = int(limits["time_sensitive_stale_after_days"])
    recheck_days = int(limits["recheck_not_found_after_days"])
    asked = [f for f in (fields or ()) if f]
    if scope == "specific" and not asked and categories:
        # Specific changes by type of information: the boxes of the chosen
        # types that this category's schema has - never a box outside it.
        wanted = {f for c in categories if c in CHANGE_CATEGORIES
                  for f in CHANGE_CATEGORIES[c]["fields"]}
        if "_own" in categories:
            wanted |= set(category_fields or ())
        asked = [f for f in schema if f in wanted]
        if not asked:
            raise ActorUpdateError("None of the chosen types of information applies to "
                                   "this actor's category.")
    for key in asked:
        if key not in schema:
            skipped.append({"field": key, "reason": "Not in this actor's category schema, "
                                                    "so it is never filled."})
    for key in schema:
        fact = current.get(key)
        has_value = bool(fact) and fact.get("collection_state") == "found"
        if has_value and key == "location":
            # {"region": "Not Provided", "country": "US"} was stored as found;
            # a location with no city or state is missing, not filled.
            has_value = any(location_parts(fact.get("fact_value"))[:2])
        age = _age_days(fact.get("retrieved_at"), today) if fact else None
        if scope == "specific":
            if key in asked:
                read.append(key)
            continue
        if scope == "missing":
            if has_value:
                skipped.append({"field": key, "reason": "Already has a value."})
            elif fact and age is not None and age < recheck_days:
                skipped.append({"field": key, "reason": (
                    f"Checked {age} days ago and not stated; looked at again after "
                    f"{recheck_days} days.")})
            else:
                read.append(key)
            continue
        if scope == "outdated":
            window = quick_days if key in TIME_SENSITIVE else stale_days
            if not has_value:
                skipped.append({"field": key, "reason": "Nothing recorded yet "
                                                        "(choose Missing information)."})
            elif age is not None and age < window:
                skipped.append({"field": key, "reason": (
                    f"Read {age} days ago; still fresh (re-read after {window} days).")})
            else:
                read.append(key)
            continue
        read.append(key)  # topic / general: every box of the schema
    if scope == "specific" and not read:
        raise ActorUpdateError("Choose at least one box to update.")
    ordered = prioritise(read, [c for c in categories or () if c != "_own"])
    if "_own" in (categories or ()):
        own = [f for f in ordered if f in category_fields]
        ordered = own + [f for f in ordered if f not in category_fields]
    return ordered, skipped


# --------------------------------------------------------------------- cost

def cost_estimate(session, limits: dict, *, runs_dir: Path = RUNS_DIR) -> dict:
    """The cap that will be enforced, and what past updates really cost.

    Never invented: with no history the estimate is the cap alone, and says so.
    """
    spent: list[float] = []
    if _has_table(session, "collection_run"):
        spent += [float(v) for v in session.execute(text(
            "SELECT spent_usd FROM collection_run WHERE job_name = :job AND spent_usd > 0 "
            "ORDER BY started_at DESC LIMIT 50"
        ), {"job": JOB_NAME}).scalars()]
    for path in sorted(Path(runs_dir).glob("*.json"))[-50:] if Path(runs_dir).is_dir() else ():
        try:
            check = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not check.get("applied_run_id") and float(check.get("cost_usd") or 0) > 0:
            spent.append(float(check["cost_usd"]))
    cap = float(limits["max_usd_per_actor"])
    if not spent:
        return {"cap_usd": cap, "runs": 0, "low_usd": None, "typical_usd": None,
                "high_usd": None,
                "basis": f"No update has run yet, so there is no history; it can never "
                         f"cost more than the ${cap:.2f} cap."}
    return {"cap_usd": cap, "runs": len(spent), "low_usd": round(min(spent), 4),
            "typical_usd": round(statistics.median(spent), 4),
            "high_usd": round(max(spent), 4),
            "basis": f"From the last {len(spent)} actor update read(s); capped at ${cap:.2f}."}


def last_update(session, actor_id: str) -> dict | None:
    if not (_has_table(session, "collection_run") and _has_table(session, "collection_request")):
        return None
    row = session.execute(text(
        "SELECT r.finished_at, r.status, r.spent_usd FROM collection_run r "
        "JOIN collection_request q ON q.collection_request_id = r.collection_request_id "
        "WHERE r.job_name = :job AND q.actor_id = CAST(:a AS uuid) "
        "AND r.status IN ('succeeded', 'attention') ORDER BY r.finished_at DESC NULLS LAST LIMIT 1"
    ), {"job": JOB_NAME, "a": actor_id}).mappings().first()
    if row is None:
        return None
    return {"finished_at": str(row["finished_at"] or "")[:19], "status": row["status"],
            "spent_usd": float(row["spent_usd"] or 0)}


# --------------------------------------------------------------------- plan

def _label(key: str) -> str:
    return key.replace("_", " ")


def describe(plan: dict) -> str:
    """The request in one paragraph, from the plan itself."""
    actor, topic = plan["actor"], plan.get("topic")
    scope_words = {
        "topic": "every box for the chosen sector",
        "general": "its whole profile",
        "missing": "only the boxes still empty",
        "outdated": "only the values that are out of date",
        "specific": "the boxes you chose",
    }[plan["scope"]]
    parts = [f"Re-read {actor['name']}'s own website ({actor.get('website') or 'no website'}) "
             f"for {scope_words}"]
    if topic:
        parts[0] += f", in {topic['name']}"
    parts[0] += "."
    if plan["fields"]:
        listed = ", ".join(_label(f) for f in plan["fields"][:6])
        more = len(plan["fields"]) - 6
        parts.append(f"{len(plan['fields'])} box(es): {listed}" + (f" and {more} more." if more > 0
                                                                     else "."))
    else:
        parts.append("Nothing needs reading, so nothing will be spent.")
    blocked = (plan.get("access") or {}).get("blocked")
    if blocked:
        parts.append(f"{blocked['plain']} It is not tried again before {blocked['retry_after']}, "
                     "so this update reads other sources that name it instead.")
    if plan["depth"] == "deep" and not plan["deep"]["permitted"]:
        parts.append("Deep Pull is not permitted: " + plan["deep"]["reason"])
    elif plan["depth"] == "deep" and plan["fields"]:
        parts.append(f"Deep Pull, selected: {len(plan['fields'])} of the "
                     f"{plan['schema_size']} Deep items for this type; run it again for others.")
    cost = plan["cost"]
    if plan["fields"]:
        if cost["typical_usd"] is not None:
            parts.append(f"Usually about ${cost['typical_usd']:.2f}; never more than "
                         f"${cost['cap_usd']:.2f}.")
        else:
            parts.append(f"Never more than ${cost['cap_usd']:.2f}.")
    parts.append("Checking writes nothing; you see every change before it is written.")
    return " ".join(parts)


def plan_update(session, *, actor_id: str, topic_code: str | None = None, scope: str = "general",
                depth: str = "light", fields=(), categories=(), focus: str = "",
                config: dict | None = None, today: datetime | None = None,
                runs_dir: Path = RUNS_DIR) -> dict:
    """What a request would do. Free: no page is read and nothing is written."""
    if depth not in DEPTHS:
        raise ActorUpdateError(f"Unknown depth {depth!r}.")
    if scope not in SCOPES:
        raise ActorUpdateError(f"Unknown update scope {scope!r}.")
    unknown = [c for c in categories or () if c not in CATEGORY_CHOICES]
    if unknown:
        raise ActorUpdateError(f"Unknown change category: {', '.join(unknown)}.")
    limits = settings(config)
    today = today or datetime.now(UTC)
    actor = load_actor(session, actor_id)
    if actor is None:
        return {"ok": False, "error": "No actor with that id."}
    summary_actor = {k: actor.get(k) for k in ("actor_id", "name", "website", "actor_category",
                                                "category_type", "city", "state", "country",
                                                "status")}
    topics = actor["topics"]
    # A sector the person chose wins - it may be one the actor is not linked to
    # yet, which is exactly the case for imported actors. Otherwise its own.
    chosen = topic_by_code(session, topic_code) if topic_code else None
    if topic_code and chosen is None:
        return {"ok": False, "actor": summary_actor, "error": f"No sector with code {topic_code}."}
    if scope == "topic" and chosen is None:
        return {"ok": False, "actor": summary_actor, "needs_topic": True,
                "error": "A topic update needs the sector to update it for."}
    topic = chosen or (topics[0] if topics else None)
    base = {"actor": summary_actor, "topics": [{"code": t["code"], "name": t["name"]}
                                               for t in topics],
            "scope": scope, "depth": depth, "categories": list(categories or ()),
            "focus": focus.strip()[:200], "last_update": last_update(session, actor["actor_id"])}
    if "aggregate" in (actor.get("actor_category"), actor.get("actor_type")):
        return {**base, "ok": False,
                "error": "This record is an aggregate placeholder, not an organisation, so "
                         "it is never updated by an agent."}
    if not str(actor.get("website") or "").strip():
        return {**base, "ok": False,
                "error": "This actor has no website on record, so there are no pages "
                         "of its own to read. Add the website in Review first."}
    if topic is None:
        return {**base, "ok": False, "needs_topic": True,
                "error": "This actor is not linked to a sector yet, and facts are kept "
                         "per sector. Choose the sector to update it for."}
    schema = schema_fields(actor["actor_category"])
    from agents.collection.light_pull import CATEGORY_LIGHT_FIELDS

    current = current_values(session, actor["actor_id"], topic["topic_id"], schema)
    to_read, skipped = plan_fields(
        scope, schema, current, fields=fields, categories=categories,
        category_fields=CATEGORY_LIGHT_FIELDS.get(actor["actor_category"] or "", ()),
        today=today, limits=limits)
    deep = deep_eligibility(session, actor_id=actor["actor_id"], topic=topic)
    from agents.collection.site_access import BLOCKED_SITES, BlockedSites

    held = BlockedSites(BLOCKED_SITES).blocked(actor["website"])
    searches = int(limits["fallback_web_searches"])
    access = {
        "blocked": ({"plain": held["plain"], "since": held["first_seen"][:10],
                     "retry_after": held["retry_after"][:10]} if held else None),
        "fallback": (
            "If its own website refuses the agent, it reads its parent organisation's official "
            "pages that name it (free)"
            + (f", then at most {searches} web search (about "
               f"${float(limits['web_search_usd_per_request']):.2f} plus reading)" if searches
               else "")
            + ": three pages at most, each naming this organisation, within the same cost cap."),
    }
    from agents.collection import hub_reassessment

    plan = {
        **base, "ok": True,
        "topic": {"code": topic["code"], "name": topic["name"], "source": topic.get("source")},
        "deep": deep,
        "fields": to_read,
        "skipped": skipped,
        "schema": schema,
        "schema_size": len(schema),
        "cost": cost_estimate(session, limits, runs_dir=runs_dir),
        "pages": "Up to 3 page requests in total, including unavailable pages. " + access["fallback"],
        "can_check": bool(to_read) and depth == "light",
        "hubs": hub_reassessment.assess(session, actor["actor_id"]),
        "access": access,
    }
    if depth == "deep":
        _deep_plan(session, plan, actor, topic, fields=fields)
    plan["summary"] = describe(plan)
    return plan


def _deep_plan(session, plan: dict, actor: dict, topic: dict, *, fields=()) -> None:
    """Replace the Light boxes with a selected set of Deep boxes, or refuse."""
    from agents.collection.deep_pull_reader import MAX_DEEP_FIELDS, deep_schema, select_fields

    schema = deep_schema(actor["actor_category"])
    plan["can_check"] = False
    plan["schema"], plan["schema_size"] = schema, len(schema)
    plan["fields"], plan["skipped"] = [], []
    if not plan["deep"]["permitted"]:
        plan["refusal"] = plan["deep"]["reason"]
        return
    if not schema:
        plan["refusal"] = ("This organization's type has no Deep Pull items, so there is nothing "
                           "deeper to read. Run a Light Refresh instead.")
        return
    current = current_values(session, actor["actor_id"], topic["topic_id"], schema)
    chosen = select_fields(actor["actor_category"], current, wanted=fields)
    plan["fields"] = chosen
    plan["skipped"] = [{"field": f, "reason": (
        f"Not in this Deep Pull: it reads at most {MAX_DEEP_FIELDS} items at a time, those "
        "with nothing recorded first. Run it again for this one.")}
        for f in schema if f not in chosen]
    plan["can_check"] = bool(chosen)
    plan["pages"] = ("Up to 3 page requests in total, including unavailable pages, read for the "
                     "selected Deep items. " + plan["access"]["fallback"])


# ----------------------------------------------------------------- compare

def _signature(value) -> tuple[set[str], set[str]]:
    """The numbers in a value, and its words cut to five letters."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            pass
    if isinstance(value, dict):
        value = " ".join(str(v) for v in value.values())
    elif isinstance(value, list):
        value = " ".join(str(v) for v in value)
    content = str(value or "").casefold()
    numbers = {n.rstrip(".,") for n in re.findall(r"\d[\d.,]*", content)}
    words = {w[:5] for w in re.findall(r"[a-z]{4,}", content)}
    return numbers, words


def _what_changed(outcome: str, before, after) -> str:
    if outcome == "changed" or outcome in {"conflict", "protected"}:
        numbers_a, _ = _signature(before)
        numbers_b, _ = _signature(after)
        if numbers_a != numbers_b and (numbers_a or numbers_b):
            gone = ", ".join(sorted(numbers_a - numbers_b)) or "none"
            new = ", ".join(sorted(numbers_b - numbers_a)) or "none"
            return f"Different figures or dates (was: {gone}; now: {new})."
        return "Different wording and content."
    return {
        "new": "Nothing was recorded; the pages now state it.",
        "corroborated": "The pages state what is recorded.",
        "additional": "The pages state what is recorded, and more.",
        "unchanged": "The pages do not state it; the recorded value stands.",
        "not_found": "The pages do not state it, and nothing was recorded.",
        "not_yet_collected": "Not read in this update.",
    }.get(outcome, "")


def classify(field: str, before: dict | None, evidence: dict | None, rejected: str | None,
             *, read_at: datetime, topic_name: str) -> dict:
    """One box: what is recorded, what the pages say, and what the writer will do.

    Mirrors ``decisions.append_actor_fact`` so the preview is the outcome:
    same value -> corroborate; nothing current -> new; current set by GHUS ->
    protected; at least as confident and newer -> changed; else conflict.
    """
    from agents.enrichment.decisions import _confidence_rank

    from agents.common.fact_parts import compare_values, parts_line

    had = bool(before) and before.get("collection_state") == "found"
    found = bool(evidence) and evidence.get("collection_state") == "found"
    comparison = None
    if evidence is None:
        outcome = "unchanged" if had else "not_yet_collected"
    elif not found:
        outcome = "unchanged" if had else "not_found"
    elif not had:
        outcome = "new"
    elif (comparison := compare_values(field, before.get("fact_value"),
                                       evidence.get("value")))["outcome"] == "corroborated":
        # Fact by fact: the same facts (or fewer of them) confirm the record.
        outcome = "corroborated"
    elif before.get("creator_class") == "ghus_human":
        outcome = "protected"
    else:
        previous_read = before.get("retrieved_at")
        if isinstance(previous_read, str):
            previous_read = datetime.fromisoformat(previous_read)
        if previous_read is not None and previous_read.tzinfo is None:
            previous_read = previous_read.replace(tzinfo=UTC)
        stronger = (_confidence_rank(evidence.get("confidence") or "medium")
                    >= _confidence_rank(before.get("confidence") or "low"))
        newer = previous_read is None or read_at > previous_read
        if not (stronger and newer):
            outcome = "conflict"
        else:
            outcome = "additional" if comparison["outcome"] == "additional" else "changed"
    previous = None
    if before:
        previous = {"value": before.get("fact_value") if had else None,
                    "state": before.get("collection_state"),
                    "source_url": before.get("source_url"),
                    "date_read": str(before.get("retrieved_at") or "")[:10] or None,
                    "confidence": before.get("confidence"),
                    "set_by": "GHUS" if before.get("creator_class") == "ghus_human" else "agent"}
    proposed = None
    if found:
        proposed = {"value": evidence.get("value"), "source_url": evidence.get("source_url"),
                    "date_read": str(evidence.get("date_read") or "")[:10],
                    "confidence": evidence.get("confidence")}
    parts = (comparison or {}).get("parts") or []
    write_value = (comparison or {}).get("merged") if outcome in {
        "additional", "changed", "conflict", "protected"} else None
    if proposed and write_value is not None:
        # What the box would hold: the new facts, and the recorded facts this
        # reading did not restate - never a poorer value than the record's.
        proposed["value"] = write_value
    return {
        "field": field,
        "topic": topic_name,
        "outcome": outcome,
        "group": GROUPS[outcome],
        "previous": previous,
        "proposed": proposed,
        "parts": parts,
        "what_changed": (parts_line(parts) if parts and outcome != "corroborated" else
                         _what_changed(outcome, previous and previous["value"],
                                       proposed and proposed["value"])),
        # An answer that failed a check is not evidence of absence either.
        "resolution": ("Nothing is written: the answer failed a check."
                       if rejected and outcome == "not_found" else RESOLUTION[outcome]),
        "reason": rejected,
        # Kept for apply; not shown.
        "_evidence": evidence,
        "_current_value": before.get("fact_value") if had else None,
        "_write_value": write_value,
    }


def counts_of(findings) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding["group"]] = counts.get(finding["group"], 0) + 1
    return counts


def public(finding: dict) -> dict:
    return {k: v for k, v in finding.items() if not k.startswith("_")}


# -------------------------------------------------------------------- check

def _check_path(runs_dir: Path, check_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", str(check_id or "")):
        raise ActorUpdateError("That check id is not valid.")
    return Path(runs_dir) / f"{check_id}.json"


def check_update(session, *, actor_id: str, topic_code: str | None = None,
                 scope: str = "general", depth: str = "light", fields=(), categories=(),
                 focus: str = "", max_usd: float | None = None, config: dict | None = None,
                 reader_factory=None, runs_dir: Path = RUNS_DIR,
                 today: datetime | None = None) -> dict:
    """Read the actor's pages once and compare every box. Writes no database row."""
    if config is None:
        from agents.discovery.search.run import load_open_web_config

        config = load_open_web_config(ROOT)
    limits = settings(config)
    plan = plan_update(session, actor_id=actor_id, topic_code=topic_code, scope=scope,
                       depth=depth, fields=fields, categories=categories, focus=focus,
                       config=config, today=today, runs_dir=runs_dir)
    if not plan.get("ok"):
        return plan
    if depth == "deep" and not plan["can_check"]:
        return {**plan, "ok": False, "error": plan.get("refusal")
                or "Nothing is selected for this Deep Pull."}
    if not plan["fields"]:
        return {**plan, "ok": True, "findings": [], "counts": {}, "cost_usd": 0.0,
                "pages_read": [], "check_id": None,
                "note": "Every box in scope is filled and fresh, so nothing was read."}
    cap = float(limits["max_usd_per_actor"])
    cap = min(cap, float(max_usd)) if max_usd else cap
    if reader_factory is None:
        from agents.collection.deep_pull_reader import DeepPullReader
        from agents.collection.light_pull_candidates import _reader

        reader, meter, model = _reader(
            config, cap, reader_class=DeepPullReader if depth == "deep" else None)
    else:
        reader, meter, model = reader_factory(cap)

    actor = load_actor(session, actor_id)
    topic = topic_by_code(session, plan["topic"]["code"])
    terms = [topic["name"]]
    if plan["focus"]:
        terms.append(plan["focus"])
    for category in plan["categories"]:
        terms += list(CHANGE_CATEGORIES.get(category, {}).get("pages", ()))
    before = current_values(session, actor["actor_id"], topic["topic_id"], plan["fields"])
    read_at = datetime.now(UTC)
    try:
        read = reader.read(name=actor["name"], website=actor["website"],
                           actor_category=actor["actor_category"],
                           category_type=str(actor.get("category_type") or ""),
                           topic_terms=terms, read_at=read_at, fields=plan["fields"])
    except Exception as exc:  # noqa: BLE001 - a stalled call or the cost cap; say what was spent
        from agents.collection.site_access import failure_of

        spent = round(float(meter.spent_usd), 4)
        reason = ("it reached its spending limit" if "cost" in str(exc).casefold()
                  or "budget" in str(exc).casefold()
                  else "the AI service did not answer in time" if "timeout" in str(exc).casefold()
                  else failure_of(exc)["plain"].rstrip(".").lower())
        return {**plan, "ok": False, "cost_usd": spent,
                "error": f"{actor['name']} could not be checked: {reason}. Nothing was written.",
                "technical": type(exc).__name__}
    spent = round(float(meter.spent_usd), 4)
    attempts = list(getattr(read, "attempts", []) or [])
    if not read.pages:
        # Nothing was read - its site refused (403), did not resolve, or had no
        # text, and no other source open to the agent names it. Reporting each
        # box as "not found" would claim pages were read and were silent.
        return {**plan, "ok": False, "cost_usd": spent, "attempts": attempts,
                "error": f"Nothing could be read about {actor['name']}. "
                         f"{read.error or ''} Nothing was compared or written.".replace("  ", " ")}
    findings = [classify(f, before.get(f), read.evidence.get(f), read.rejected.get(f),
                         read_at=read_at, topic_name=topic["name"]) for f in plan["fields"]]
    from agents.collection import related_actors

    related, related_error = [], None
    client = getattr(reader, "client", None)
    if client is not None and related_actors.relation_values(findings):
        try:
            named = related_actors.extract(client, actor_name=actor["name"], findings=findings)
            related = related_actors.route(session, actor, named)
        except Exception as exc:  # noqa: BLE001 - the facts stand without it; say so
            related_error = f"Related organisations were not listed: {type(exc).__name__}"
    spent = round(float(meter.spent_usd), 4)
    # Boxes in the schema with nothing recorded and not read now.
    schema = plan["schema"]
    others = current_values(session, actor["actor_id"], topic["topic_id"],
                            [f for f in schema if f not in plan["fields"]])
    unread = [classify(f, None, None, None, read_at=read_at, topic_name=topic["name"])
              for f in schema if f not in plan["fields"] and f not in others]
    check_id = uuid.uuid4().hex
    record = {
        "check_id": check_id, "created_at": read_at.isoformat(), "read_at": read_at.isoformat(),
        "actor_id": actor["actor_id"], "actor_name": actor["name"],
        "actor_category": actor["actor_category"], "topic_id": topic["topic_id"], "topic_code": topic["code"], "topic_name": topic["name"],
        "scope": scope, "depth": depth, "categories": plan["categories"], "focus": plan["focus"],
        "fields": plan["fields"], "pages_read": read.pages, "cost_usd": spent, "cap_usd": cap,
        "sources": dict(getattr(read, "sources", {}) or {}), "attempts": attempts,
        "model": model, "summary": plan["summary"], "findings": findings,
        "applied_run_id": None, "written_fields": [],
        "related": related, "hubs": plan["hubs"], "proposals_written": False,
    }
    Path(runs_dir).mkdir(parents=True, exist_ok=True)
    _check_path(runs_dir, check_id).write_text(json.dumps(record, default=str, indent=1),
                                               encoding="utf-8")
    return {**plan, "ok": True, "check_id": check_id, "pages_read": read.pages,
            # Which source each page was, and what was tried when its own site
            # was closed - shown on the page, in plain words.
            "sources": record["sources"], "attempts": attempts,
            "findings": [public(f) for f in findings], "unread": [public(f) for f in unread],
            "counts": counts_of(findings), "cost_usd": spent, "model": model,
            "related": related, "related_error": related_error,
            "proposals": _proposal_count(related, plan["hubs"]),
            "writes": sum(1 for f in findings if f["outcome"] in WRITTEN
                          and not (f["outcome"] == "not_found" and f.get("reason"))),
            "error": read.error}


# -------------------------------------------------------------------- apply

def _record_run(session, record: dict) -> tuple[str, str]:
    """The run in the existing ledger, written by its one writer (subscription_store)."""
    from agents.collection import subscription_store as store

    return store.start_actor_update_run(
        session, actor_id=record["actor_id"], topic_id=record["topic_id"],
        need=f"Actor update ({record['scope']}): {record['summary']}",
        requested_by=REQUESTED_BY, job_name=JOB_NAME, cap_usd=float(record["cap_usd"]),
        deep=record.get("depth") == "deep",
        spent_usd=float(record["cost_usd"]), pages_fetched=len(record["pages_read"]),
        snapshot={
            "check_id": record["check_id"], "scope": record["scope"], "depth": record["depth"],
            "categories": record["categories"], "focus": record["focus"],
            "fields": record["fields"], "pages_read": record["pages_read"],
            "sources": record.get("sources") or {}, "attempts": record.get("attempts") or [],
            "model": record["model"], "read_at": record["read_at"],
        })


def _finish_run(session, run_id: str, *, status: str, reason: str | None, results) -> None:
    from agents.collection import subscription_store as store

    store.finish_actor_update_run(
        session, run_id, status=status, reason=reason,
        found=sum(1 for r in results if r.get("written") and r["outcome"] != "not_found"),
        review_items=sum(1 for r in results
                         if r.get("written") and r["outcome"] in {"conflict", "protected"}),
        outcomes={r["field"]: r.get("actual") or r["outcome"] for r in results})


def location_parts(value) -> tuple[str | None, str | None, str | None]:
    """(city, state, country) from a location fact: an object, or "City, State"."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            pass
    if isinstance(value, dict):
        city = value.get("city") or value.get("location_city")
        state = value.get("state") or value.get("state_code")
        return (str(city).strip() if city else None, str(state).strip() if state else None,
                value.get("country"))
    parts = [part.strip() for part in str(value or "").split(",") if part.strip()]
    if len(parts) >= 2:
        country = parts[2] if len(parts) > 2 else None
        # "Montpelier, VT 05602" -> state "VT"
        return parts[0], re.sub(r"\s+\d{5}(-\d{4})?$", "", parts[1]), country
    return None, None, None


def _fill_location(session, record: dict, results: list[dict]) -> dict | None:
    """A location the pages stated fills the actor's record if it is empty."""
    from agents.enrichment.decisions import fill_actor_location

    written = next((r for r in results if r["field"] == "location" and r.get("written")
                    and r.get("actual") in {"new", "changed", "corroborated"}), None)
    if written is None or not written.get("proposed"):
        return None
    city, state, country = location_parts(written["proposed"]["value"])
    if not city or not state:
        return {"action": "not_enough", "detail": "the pages gave no city and state"}
    savepoint = session.begin_nested()
    try:
        result = fill_actor_location(session, actor_id=record["actor_id"], city=city,
                                     state=state, country=country or "US", live=True)
        savepoint.commit()
    except Exception as exc:  # noqa: BLE001 - the fact stands; say why the record did not move
        savepoint.rollback()
        result = {"action": "failed", "error": f"{type(exc).__name__}: {exc}"[:200]}
    return result


def _proposal_count(related, hubs) -> int:
    return (sum(1 for r in related or () if r.get("status") == "on_map")
            + len((hubs or {}).get("proposals") or ()))


def _write_proposals(session, record: dict, request_id: str) -> list[dict]:
    """Relationships and hub memberships the check found, raised to Review.

    Never written as edges or memberships here: decisions.py raises a Review
    item for each, and only a person's acceptance makes it real.
    """
    from agents.enrichment.decisions import propose_actor_relationship, propose_hub_membership

    out = []
    for item in record.get("related") or ():
        if item.get("status") != "on_map" or not item.get("source_url"):
            continue
        savepoint = session.begin_nested()
        try:
            result = propose_actor_relationship(
                session, topic_id=record["topic_id"], request_id=request_id,
                source_url=item["source_url"], live=True, **item["proposal"])
            savepoint.commit()
        except Exception as exc:  # noqa: BLE001 - one proposal must not stop the others
            savepoint.rollback()
            result = {"action": "failed", "error": f"{type(exc).__name__}: {exc}"[:200]}
        out.append({"kind": "relationship", "name": item["name"],
                    "relationship_type": item["relationship_type"], **result})
    for hub in (record.get("hubs") or {}).get("proposals") or ():
        savepoint = session.begin_nested()
        try:
            result = propose_hub_membership(
                session, actor_id=record["actor_id"], hub_id=hub["hub_id"],
                distance_miles=hub["distance_miles"], radius_miles=hub["radius_miles"],
                sector_code=hub["sector"], topic_id=record["topic_id"], request_id=request_id,
                live=True)
            savepoint.commit()
        except Exception as exc:  # noqa: BLE001
            savepoint.rollback()
            result = {"action": "failed", "error": f"{type(exc).__name__}: {exc}"[:200]}
        out.append({"kind": "hub", "name": hub["name"], **result})
    return out


def _actual(session, fact_id: str, current_id: str | None) -> str:
    """What the writer really did, read back from the fact it returned."""
    if current_id and fact_id == current_id:
        return "corroborated"
    state = session.execute(text(
        "SELECT lifecycle_state, supersedes_fact_id IS NOT NULL AS supersedes FROM actor_fact "
        "WHERE actor_fact_id = CAST(:id AS uuid)"), {"id": fact_id}).mappings().first()
    if state is None:
        return "unknown"
    if state["lifecycle_state"] == "pending_update":
        return "protected"
    if state["lifecycle_state"] == "conflict_flagged":
        return "conflict"
    return "changed" if state["supersedes"] else "new"


def apply_check(session, check_id: str, *, runs_dir: Path = RUNS_DIR, config: dict | None = None,
                now: datetime | None = None, ledger: tuple[str, str] | None = None) -> dict:
    """Write what a check found, through the Phase 11 writer. No second read.

    ``ledger`` is (collection request id, run id) when the check belongs to an
    update request's run: the facts carry that request and the request runner
    records and closes the run. Without it this check is its own run.
    """
    from agents.common.facts import ActorFactWrite
    from agents.enrichment.decisions import append_actor_fact

    path = _check_path(runs_dir, check_id)
    if not path.is_file():
        return {"ok": False, "error": "That check was not found; run the check again."}
    record = json.loads(path.read_text(encoding="utf-8"))
    limits = settings(config)
    now = now or datetime.now(UTC)
    created = datetime.fromisoformat(record["created_at"])
    if now - created > timedelta(hours=float(limits["check_valid_hours"])):
        return {"ok": False, "error": (
            f"This check is older than {limits['check_valid_hours']} hours; its pages may "
            "have changed. Run the check again.")}
    deep = record.get("depth") == "deep"
    if deep:
        from agents.collection.deep_pull import actor_is_verified_for_topic

        # Checked again at the moment of writing: a verification reversed
        # after the check stops the Deep Pull here (the writer refuses too).
        if not actor_is_verified_for_topic(session, actor_id=record["actor_id"],
                                           topic_id=record["topic_id"]):
            return {"ok": False, "check_id": check_id, "error": (
                "GHUS no longer has this actor verified for this sector, so the Deep Pull "
                "is not written. Nothing was changed.")}
    done = set(record.get("written_fields") or ())
    pending = [f for f in record["findings"] if f["outcome"] in WRITTEN
               and not (f["outcome"] == "not_found" and f.get("reason"))
               and f["field"] not in done]
    if not pending and record.get("proposals_written", True):
        return {"ok": True, "check_id": check_id, "run_id": record.get("applied_run_id"),
                "results": [], "note": "Everything in this check was already written."}
    read_at = datetime.fromisoformat(record["read_at"])
    if ledger is not None:
        request_id, run_id = ledger
        record["applied_run_id"], record["applied_request_id"] = run_id, request_id
    elif record.get("applied_run_id"):
        run_id = record["applied_run_id"]
        request_id = record["applied_request_id"]
    else:
        request_id, run_id = _record_run(session, record)
        session.commit()
        record["applied_run_id"], record["applied_request_id"] = run_id, request_id
    current = current_values(session, record["actor_id"], record["topic_id"],
                             [f["field"] for f in pending])
    results = []
    for finding in pending:
        evidence = finding["_evidence"] or {}
        now_current = current.get(finding["field"])
        value = evidence.get("value")
        if finding["outcome"] == "corroborated" and now_current \
                and now_current.get("collection_state") == "found":
            # Same fact in other words: corroborate the recorded value itself,
            # so the writer adds this source instead of a near-duplicate fact.
            value = now_current["fact_value"]
        elif finding.get("_write_value") is not None:
            # Compared fact by fact: the new facts, with the recorded ones this
            # reading did not restate - a reading never makes a box poorer.
            value = finding["_write_value"]
        result = public(finding)
        savepoint = session.begin_nested()
        try:
            if deep:
                fact_id = _write_deep(session, record, finding["field"], evidence, value,
                                      read_at=read_at, request_id=request_id)
            else:
                fact_id = append_actor_fact(session, ActorFactWrite(
                    actor_id=record["actor_id"], topic_id=record["topic_id"],
                    fact_type="light_pull", field_key=finding["field"],
                    value=value if evidence.get("collection_state") == "found" else None,
                    layer=1, collection_state=evidence.get("collection_state") or "not_found",
                    confidence=evidence.get("confidence") or "medium",
                    source_url=evidence.get("source_url") or record["pages_read"][0],
                    date_read=read_at, source_origin="newly_found", created_by=CREATED_BY,
                    request_id=request_id,
                ), live=True)
            savepoint.commit()
        except Exception as exc:  # noqa: BLE001 - one box must not stop the others
            savepoint.rollback()
            result.update(written=False, error=f"{type(exc).__name__}: {exc}"[:300])
            results.append(result)
            continue
        actual = _actual(session, fact_id,
                         now_current.get("actor_fact_id") if now_current else None)
        if finding["outcome"] == "not_found":
            actual = "not_found"
        elif finding["outcome"] == "additional" and actual == "changed":
            actual = "additional"
        result.update(written=True, fact_id=fact_id, actual=actual)
        results.append(result)
    location = _fill_location(session, record, results)
    proposals = []
    if not record.get("proposals_written"):
        proposals = _write_proposals(session, record, request_id)
        record["proposals_written"] = True
    failed = [r for r in results if not r.get("written")]
    status = "attention" if failed else "succeeded"
    reason = (f"{len(failed)} box(es) failed; apply the same check again to retry them."
              if failed else None)
    if ledger is None:
        _finish_run(session, run_id, status=status, reason=reason, results=results)
    session.commit()
    record["written_fields"] = sorted(done | {r["field"] for r in results if r.get("written")})
    path.write_text(json.dumps(record, default=str, indent=1), encoding="utf-8")
    counts: dict[str, int] = {}
    for r in results:
        if r.get("written"):
            counts[r["actual"]] = counts.get(r["actual"], 0) + 1
    proposed = sum(1 for p in proposals if p.get("action") == "proposed")
    return {"ok": not failed, "check_id": check_id, "run_id": run_id, "results": results,
            "counts": counts, "failed": len(failed), "error": reason,
            "proposals": proposals, "location": location,
            "review_items": proposed + sum(1 for r in results
                                           if r.get("written")
                                           and r["actual"] in {"conflict", "protected"})}


def _write_deep(session, record: dict, field: str, evidence: dict, value, *,
                read_at: datetime, request_id: str) -> str:
    """One Deep box as a Layer 2 fact, through the Phase 10 writer and its gate."""
    from agents.collection.deep_pull import CollectedValue, DeepPullRequest, append_deep_pull

    found = evidence.get("collection_state") == "found"
    request = DeepPullRequest(
        actor_id=record["actor_id"], topic_id=record["topic_id"],
        actor_category=str(record.get("actor_category") or ""), selected_fields=(field,),
        requested_by=CREATED_BY, request_id=request_id)
    collected = CollectedValue(
        field_key=field, value=value if found else None,
        collection_state=evidence.get("collection_state") or "not_found",
        source_url=evidence.get("source_url") or record["pages_read"][0],
        source_origin="newly_found", date_read=read_at,
        confidence=evidence.get("confidence") or "medium")
    return append_deep_pull(session, request, {field: collected}, live=True)[0]


# ----------------------------------------------------------------- requests
# An update request keeps chosen actors current: one actor or a bounded group,
# once or on a frequency, for a stated period. It is an actor_update_subscription
# (migration 570) run by the existing request runner - there is no second
# scheduler. A run re-reads the actors with the most missing or out-of-date
# boxes first, stops at the request's actor cap or spend ceiling, and writes
# through the same check -> Phase 11 writer path as a single update.

# The Discovery page offers two choices: General Update, and Specific Changes
# (by type of information, or by a question - the "topic" scope).
SCOPE_NAMES = {"general": "General update", "topic": "Specific changes",
               "missing": "Missing information", "outdated": "Outdated information",
               "specific": "Specific changes"}
REQUEST_KEYS = frozenset({
    "title", "actor_ids", "group", "topic", "scope", "depth", "categories", "fields", "focus",
    "cadence", "start_date", "end_date", "max_actors_per_run", "max_usd_per_run",
})
GROUP_KEYS = frozenset({"sector", "category", "state"})


def _max_duration_days() -> int:
    from agents.collection.discovery_requests import _max_duration_days as configured

    return configured()


def request_options(payload: dict, *, config: dict | None = None,
                    today=None) -> dict:
    """The page's request, checked and normalised. Unknown keys are refused."""
    from datetime import date as _date

    from agents.collection.subscriptions import CADENCE_DAYS

    limits = settings(config)
    unknown = set(payload) - REQUEST_KEYS
    if unknown:
        raise ActorUpdateError(f"Unknown request field(s): {', '.join(sorted(unknown))}.")
    group = dict(payload.get("group") or {})
    if set(group) - GROUP_KEYS:
        raise ActorUpdateError("A group is chosen by sector, type and state only.")
    actor_ids = []
    for value in payload.get("actor_ids") or []:
        try:
            actor_ids.append(str(uuid.UUID(str(value))))
        except ValueError as exc:
            raise ActorUpdateError("An actor id is not valid.") from exc
    actor_ids = list(dict.fromkeys(actor_ids))
    most = int(limits["max_actors_per_request"])
    if len(actor_ids) > most:
        raise ActorUpdateError(f"Choose at most {most} actors for one request.")
    sector = str(group.get("sector") or "").strip().upper() or None
    topic = str(payload.get("topic") or "").strip().upper() or sector
    if not actor_ids and not sector:
        raise ActorUpdateError("Choose the actors, or a group with a sector: an update "
                               "request never sweeps the whole map.")
    scope = str(payload.get("scope") or "general")
    if scope not in SCOPES:
        raise ActorUpdateError(f"Unknown update scope {scope!r}.")
    if scope == "topic" and not topic:
        raise ActorUpdateError("A topic update needs the sector to update it for.")
    depth = str(payload.get("depth") or "light")
    if depth != "light":
        raise ActorUpdateError("Saved and group requests use the Light refresh. Deep "
                               "enrichment is asked for one actor at a time, and only when "
                               "GHUS verified it for that sector.")
    categories = [str(c) for c in payload.get("categories") or []]
    if any(c not in CATEGORY_CHOICES for c in categories):
        raise ActorUpdateError("Unknown change category.")
    fields = [str(f) for f in payload.get("fields") or []]
    if scope == "specific" and not fields and not categories:
        raise ActorUpdateError("Choose at least one box, or a type of information, to update.")
    cadence = str(payload.get("cadence") or "once")
    if cadence not in CADENCE_DAYS:
        raise ActorUpdateError(f"Unknown frequency {cadence!r}.")
    today = today or datetime.now(UTC).date()
    start = _date.fromisoformat(payload["start_date"]) if payload.get("start_date") else today
    if start < today:
        raise ActorUpdateError("A request cannot start in the past.")
    if cadence == "once":
        end = start
    else:
        if not payload.get("end_date"):
            raise ActorUpdateError("A recurring request needs an end date: every request ends.")
        end = _date.fromisoformat(payload["end_date"])
        if end < start:
            raise ActorUpdateError("The end date is before the start.")
        if (end - start).days > _max_duration_days():
            raise ActorUpdateError(f"A request may run for at most {_max_duration_days()} days.")
    per_run = int(payload.get("max_actors_per_run") or min(len(actor_ids) or most, most))
    if not 1 <= per_run <= most:
        raise ActorUpdateError(f"Actors per run must be 1 to {most}.")
    ceiling = float(payload.get("max_usd_per_run") or limits["max_usd_per_request_run"])
    if not 0 < ceiling <= float(limits["max_usd_per_request_run"]):
        raise ActorUpdateError(
            f"The spend ceiling per run must be above $0 and at most "
            f"${float(limits['max_usd_per_request_run']):.2f}.")
    state = str(group.get("state") or "").strip().upper() or None
    category = str(group.get("category") or "").strip() or None
    title = " ".join(str(payload.get("title") or "").split())[:160]
    return {
        "title": title, "actor_ids": actor_ids, "sector": sector, "state": state,
        "start_date": start, "end_date": end, "cadence": cadence,
        "max_usd_per_run": round(ceiling, 4),
        "options": {"scope": scope, "depth": depth, "categories": categories,
                    "fields": fields, "focus": " ".join(str(payload.get("focus") or "")
                                                       .split())[:200],
                    "topic": topic, "category": category, "max_actors_per_run": per_run},
    }


def group_actors(session, *, sector: str, category: str | None, state: str | None) -> list[dict]:
    """Actors on the map in a sector (by every route), with a website."""
    topic = topic_by_code(session, sector)
    if topic is None:
        raise ActorUpdateError(f"No sector with code {sector}.")
    routes = []
    if _has_table(session, "actor_sector"):
        routes.append("SELECT x.actor_id FROM actor_sector x JOIN sector s "
                      "ON s.sector_id = x.sector_id WHERE upper(s.code) = :code")
    if _has_table(session, "hub_actor") and _has_table(session, "hub_sector"):
        routes.append("SELECT ha.actor_id FROM hub_actor ha JOIN hub_sector hs "
                      "ON hs.hub_id = ha.hub_id JOIN sector s ON s.sector_id = hs.sector_id "
                      "WHERE upper(s.code) = :code")
    if _has_table(session, "hub_actor") and _has_column(session, "hub", "topic_id"):
        routes.append("SELECT ha.actor_id FROM hub_actor ha JOIN hub h ON h.hub_id = ha.hub_id "
                      "WHERE h.topic_id = CAST(:topic AS uuid)")
    if not routes:
        return []
    rows = session.execute(text(
        "SELECT a.actor_id::text AS actor_id, a.name, "
        "NULLIF(to_jsonb(a)->>'actor_category', '') AS actor_category "
        f"FROM actor a WHERE a.actor_id IN ({' UNION '.join(routes)}) "
        "AND NULLIF(to_jsonb(a)->>'website', '') IS NOT NULL "
        "AND NULLIF(to_jsonb(a)->>'merged_into_actor_id', '') IS NULL "
        # Aggregate placeholders are not organisations (AGENTS rule 5).
        "AND COALESCE(NULLIF(to_jsonb(a)->>'actor_category', ''), "
        "  NULLIF(to_jsonb(a)->>'actor_type', ''), '') <> 'aggregate' "
        "AND (CAST(:category AS text) IS NULL OR to_jsonb(a)->>'actor_category' = :category) "
        "AND (CAST(:state AS text) IS NULL OR upper(COALESCE(NULLIF(to_jsonb(a)->>'state_code', ''), "
        "  to_jsonb(a)->>'state')) = :state) ORDER BY a.name"
    ), {"code": sector.upper(), "topic": topic["topic_id"], "category": category,
        "state": state}).mappings()
    return [dict(r) for r in rows]


def choose_actors(session, prepared: dict, *, config: dict | None = None,
                  today: datetime | None = None) -> dict:
    """Which actors a run updates, most gaps first, and why the others wait.

    Gap-aware: an actor with nothing missing or out of date for the request's
    scope is not read at all, so it costs nothing. The actor cap is applied
    after ordering, so the cap spends the run on the actors that need it most.
    """
    from agents.collection.light_pull import CATEGORY_LIGHT_FIELDS

    limits = settings(config)
    today = today or datetime.now(UTC)
    options = prepared["options"]
    if prepared["actor_ids"]:
        pool = []
        for actor_id in prepared["actor_ids"]:
            actor = load_actor(session, actor_id)
            if actor is not None:
                pool.append(actor)
        matched = len(pool)
    else:
        pool = group_actors(session, sector=prepared["sector"], category=options["category"],
                            state=prepared["state"])
        matched = len(pool)
    chosen_topic = topic_by_code(session, options["topic"]) if options["topic"] else None
    ready, waiting = [], []
    for actor in pool:
        if "aggregate" in (actor.get("actor_category"), actor.get("actor_type")):
            waiting.append({"actor_id": actor["actor_id"], "name": actor["name"],
                            "reason": "An aggregate placeholder, not an organisation; never updated."})
            continue
        if actor.get("website") is None and "website" in actor:
            waiting.append({"actor_id": actor["actor_id"], "name": actor["name"],
                            "reason": "No website on record."})
            continue
        topics = actor.get("topics")
        if topics is None and chosen_topic is None:
            topics = actor_topics(session, actor["actor_id"])
        topic = chosen_topic or (topics[0] if topics else None)
        if topic is None:
            waiting.append({"actor_id": actor["actor_id"], "name": actor["name"],
                            "reason": "Not linked to a sector; choose one for the request."})
            continue
        schema = schema_fields(actor.get("actor_category"))
        current = current_values(session, actor["actor_id"], topic["topic_id"], schema)
        own_fields = CATEGORY_LIGHT_FIELDS.get(actor.get("actor_category") or "", ())
        try:
            fields, _ = plan_fields(
                options["scope"], schema, current, fields=options["fields"],
                categories=options["categories"], category_fields=own_fields,
                today=today, limits=limits)
        except ActorUpdateError as exc:
            waiting.append({"actor_id": actor["actor_id"], "name": actor["name"],
                            "reason": str(exc)})
            continue
        if not fields:
            waiting.append({"actor_id": actor["actor_id"], "name": actor["name"],
                            "reason": "Nothing to read: every box in scope is filled and fresh."})
            continue
        # Gaps = boxes in scope that are empty or out of date: the order in
        # which a capped run reaches actors, whatever the scope.
        gaps = {f for gap_scope in ("missing", "outdated")
                for f in plan_fields(gap_scope, schema, current, today=today, limits=limits)[0]}
        ready.append({"actor_id": actor["actor_id"], "name": actor["name"],
                      "actor_category": actor.get("actor_category"),
                      "topic": topic["code"], "boxes": len(fields), "fields": fields,
                      "gaps": len(gaps & set(fields))})
    ready.sort(key=lambda a: (-a["gaps"], -a["boxes"], a["name"]))
    cap = int(options["max_actors_per_run"])
    for actor in ready[cap:]:
        waiting.append({"actor_id": actor["actor_id"], "name": actor["name"],
                        "reason": f"Over this run's cap of {cap} actors; it comes first next run "
                                  "if it still has the most gaps."})
    return {"matched": matched, "chosen": ready[:cap], "waiting": waiting}


def _runs_in_period(prepared: dict) -> int:
    from agents.collection.subscriptions import CADENCE_DAYS

    interval = CADENCE_DAYS[prepared["cadence"]]
    if interval is None:
        return 1
    return (prepared["end_date"] - prepared["start_date"]).days // interval + 1


def _request_title(prepared: dict, chosen: list[dict], sector_name: str | None = None) -> str:
    if prepared["title"]:
        return prepared["title"]
    scope = SCOPE_NAMES[prepared["options"]["scope"]]
    if prepared["actor_ids"]:
        names = [a["name"] for a in chosen] or ["chosen actors"]
        who = names[0] if len(prepared["actor_ids"]) == 1 else f"{len(prepared['actor_ids'])} actors"
    else:
        category = (prepared["options"]["category"] or "").replace("_", " ") or None
        who = " · ".join(filter(None, [sector_name or prepared["sector"], category,
                                       prepared["state"]]))
    return f"{scope}: {who}"[:160]


def plan_request(session, payload: dict, *, config: dict | None = None,
                 runs_dir: Path = RUNS_DIR, today: datetime | None = None) -> dict:
    """What a request would do on its first run. Free: nothing read or written."""
    from agents.collection import subscription_store as store

    prepared = request_options(payload, config=config,
                               today=(today.date() if today else None))
    choice = choose_actors(session, prepared, config=config, today=today)
    limits = settings(config)
    cost = cost_estimate(session, limits, runs_dir=runs_dir)
    n = len(choice["chosen"])
    ceiling = prepared["max_usd_per_run"]
    per_actor = min(float(limits["max_usd_per_actor"]), ceiling)
    if cost["typical_usd"] is not None:
        expected = min(round(cost["typical_usd"] * n, 4), ceiling)
    else:
        expected = None
    # Even if every read cost the full per-actor cap, this many are reached.
    reachable = min(n, int(ceiling // per_actor)) if per_actor else n
    runs = _runs_in_period(prepared)
    sector = topic_by_code(session, prepared["sector"]) if prepared["sector"] else None
    title = _request_title(prepared, choice["chosen"], sector["name"] if sector else None)
    frequency = {"once": "once", "weekly": "every week", "biweekly": "every two weeks",
                 "monthly": "every month", "quarterly": "every three months"}[prepared["cadence"]]
    summary = (
        f"“{title}”: re-read up to {prepared['options']['max_actors_per_run']} actor(s) "
        f"{frequency}"
        + (f" from {prepared['start_date']} to {prepared['end_date']} ({runs} runs)"
           if prepared["cadence"] != "once" else f" on {prepared['start_date']}")
        + f", each with a Light refresh (up to 3 page requests including fallback sources). "
        f"{choice['matched']} actor(s) match; {n} would be read on the first run, those "
        f"with the most missing or out-of-date boxes first. Each run stops at "
        f"${ceiling:.2f}. New and changed values are written with their source; "
        f"conflicts and changes to GHUS values go to Review."
    )
    return {
        "ok": True, "title": title, "summary": summary, "cadence": prepared["cadence"],
        "start_date": prepared["start_date"].isoformat(),
        "end_date": prepared["end_date"].isoformat(), "runs": runs,
        "matched": choice["matched"], "chosen": choice["chosen"], "waiting": choice["waiting"],
        "options": prepared["options"], "max_usd_per_run": ceiling,
        "cost": {**cost, "per_actor_cap_usd": per_actor, "expected_usd": expected,
                 "reachable_actors": min(reachable, n)},
        "next_run": prepared["start_date"].isoformat(),
        "can_save": store.has_update_requests(session),
        "needs_migration": None if store.has_update_requests(session) else (
            "Saving update requests needs migration 570 on this database. A one-time "
            "update of one actor works without it."),
    }


def create_request(session, payload: dict, *, config: dict | None = None,
                   live: bool = False) -> dict:
    """Save a request (live) or say what would be saved. The runner does the rest."""
    from agents.collection import subscription_store as store
    from agents.collection.subscriptions import SubscriptionError

    plan = plan_request(session, payload, config=config)
    prepared = request_options(payload, config=config)
    try:
        written = store.create_update_request(
            session, title=plan["title"], end_date=prepared["end_date"],
            start_date=prepared["start_date"], cadence=prepared["cadence"],
            update_options=prepared["options"], max_usd_per_run=prepared["max_usd_per_run"],
            actor_ids=prepared["actor_ids"],
            sector_codes=[prepared["sector"]] if prepared["sector"] else [],
            state_code=prepared["state"], live=live)
    except SubscriptionError as exc:
        raise ActorUpdateError(str(exc)) from exc
    return {**plan, "live": written.live, "subscription_id": written.subscription_id}


def _prepared_from(subscription) -> dict:
    options = dict(subscription.update_options)
    return {
        "title": subscription.title or "", "actor_ids": list(subscription.actor_ids),
        "sector": (subscription.sector_codes or (None,))[0], "state": subscription.state_code,
        "start_date": subscription.start_date, "end_date": subscription.end_date,
        "cadence": subscription.cadence, "max_usd_per_run": subscription.max_usd_per_run,
        "options": {"scope": options.get("scope", "general"), "depth": "light",
                    "categories": list(options.get("categories") or []),
                    "fields": list(options.get("fields") or []),
                    "focus": options.get("focus") or "", "topic": options.get("topic"),
                    "category": options.get("category"),
                    "max_actors_per_run": int(options.get("max_actors_per_run") or 1)},
    }


def plan_subscription(session, subscription, *, config: dict | None = None) -> dict:
    """The actors a due request would read now (the runner's plan-only report)."""
    return choose_actors(session, _prepared_from(subscription), config=config)


def run_request(session, subscription, *, ledger: tuple[str, str], config: dict | None = None,
                reader_factory=None, runs_dir: Path = RUNS_DIR) -> dict:
    """One live run of a request: check and write each chosen actor, within the ceiling.

    Each actor's check is capped at min(per-actor cap, what is left of the
    run's ceiling); when less than a cent is left the run stops and says which
    actors it did not reach. One actor's failure never stops the others.
    """
    limits = settings(config)
    prepared = _prepared_from(subscription)
    choice = choose_actors(session, prepared, config=config)
    ceiling = float(subscription.max_usd_per_run)
    spent, pages, results, stopped = 0.0, 0, [], None
    options = prepared["options"]
    for index, actor in enumerate(choice["chosen"]):
        left = round(ceiling - spent, 4)
        if left < 0.01:
            stopped = (f"Stopped at the ${ceiling:.2f} spend ceiling; "
                       f"{len(choice['chosen']) - index} actor(s) not reached this run.")
            break
        cap = min(float(limits["max_usd_per_actor"]), left)
        entry = {"actor_id": actor["actor_id"], "name": actor["name"], "topic": actor["topic"],
                 "boxes": actor["boxes"]}
        try:
            check = check_update(
                session, actor_id=actor["actor_id"], topic_code=actor["topic"],
                scope=options["scope"], fields=options["fields"],
                categories=options["categories"], focus=options["focus"], max_usd=cap,
                config=config, reader_factory=reader_factory, runs_dir=runs_dir)
        except Exception as exc:  # noqa: BLE001 - one actor must not stop the others
            session.rollback()
            check = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
        spent += float(check.get("cost_usd") or 0)
        pages += len(check.get("pages_read") or [])
        if not check.get("ok") or not check.get("check_id"):
            entry.update(ok=False, error=check.get("error") or check.get("note"),
                         spent_usd=round(float(check.get("cost_usd") or 0), 4))
            results.append(entry)
            continue
        try:
            applied = apply_check(session, check["check_id"], runs_dir=runs_dir, config=config,
                                  ledger=ledger)
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            applied = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300], "counts": {}}
        entry.update(ok=bool(applied.get("ok")), error=applied.get("error"),
                     counts=applied.get("counts") or {},
                     review_items=int(applied.get("review_items") or 0),
                     spent_usd=round(float(check.get("cost_usd") or 0), 4))
        results.append(entry)
    written = [r for r in results if r.get("counts")]
    return {
        "actor_results": results, "spent_usd": round(spent, 4), "pages": pages,
        "stopped": stopped, "waiting": len(choice["waiting"]),
        "found": sum(r["counts"].get("new", 0) + r["counts"].get("changed", 0) for r in written),
        "review_items": sum(r.get("review_items", 0) for r in results),
        "failed": sum(1 for r in results if not r.get("ok")),
    }


def list_requests(session) -> dict:
    """Every actor update request, with its next run and its run history."""
    from agents.collection import subscription_store as store

    today = datetime.now(UTC).date()
    requests = []
    # A request on an inactive sector is a test fixture (the integration tests
    # create inactive topics); the page says how many and does not list them.
    inactive = set(session.execute(text(
        "SELECT upper(code) FROM topic WHERE NOT COALESCE((to_jsonb(topic)->>'active')::boolean, true)"
    )).scalars()) if _has_table(session, "topic") else set()
    for row in store.load_actor_update_requests(session):
        item = dict(row)
        try:
            subscription = store.subscription_from_row(row)
            item["next_run"] = subscription.next_due(today)
            item["skip_reason"] = subscription.skip_reason(today)
        except ValueError as exc:
            item["next_run"], item["skip_reason"] = None, f"invalid: {exc}"
        ids = list(row.get("actor_ids") or [])
        item["actor_names"] = [r[0] for r in session.execute(text(
            "SELECT name FROM actor WHERE actor_id = ANY(CAST(:ids AS uuid[])) ORDER BY name"
        ), {"ids": ids})] if ids else []
        item["runs"] = store.load_request_runs(session, str(row["subscription_id"]))
        options = row.get("update_options") or {}
        codes = {str(c).upper() for c in [options.get("topic"), *(row.get("sector_codes") or [])]
                 if c}
        item["test_sector"] = bool(codes) and codes <= inactive
        requests.append(item)
    return {"requests": requests, "ready": store.has_update_requests(session),
            "one_time": one_time_updates(session, inactive=inactive)}


def one_time_updates(session, *, inactive=frozenset(), limit: int = 30) -> list[dict]:
    """The one-actor updates written from the page (Check, then Write), newest first."""
    if not (_has_table(session, "collection_run") and _has_table(session, "collection_request")):
        return []
    rows = session.execute(text(
        "SELECT r.collection_run_id::text AS run_id, r.started_at, r.status, r.spent_usd, "
        "r.config_snapshot, a.actor_id::text AS actor_id, a.name, upper(t.code) AS topic, "
        "t.name AS topic_name FROM collection_run r "
        "JOIN collection_request q ON q.collection_request_id = r.collection_request_id "
        "JOIN actor a ON a.actor_id = q.actor_id LEFT JOIN topic t ON t.topic_id = q.topic_id "
        "WHERE r.job_name = :job ORDER BY r.started_at DESC LIMIT :limit"
    ), {"job": JOB_NAME, "limit": limit}).mappings()
    out = []
    for row in rows:
        if row["topic"] in inactive:
            continue
        snapshot = row["config_snapshot"] or {}
        counts: dict[str, int] = {}
        for outcome in (snapshot.get("outcomes") or {}).values():
            group = GROUPS.get(str(outcome), str(outcome))
            counts[group] = counts.get(group, 0) + 1
        out.append({"run_id": row["run_id"], "started_at": str(row["started_at"] or "")[:19],
                    "status": row["status"], "spent_usd": float(row["spent_usd"] or 0),
                    "actor_id": row["actor_id"], "name": row["name"],
                    "topic_name": row["topic_name"], "scope": snapshot.get("scope"),
                    "counts": counts})
    return out


# --------------------------------------------------------------------- CLI

def _common(parser) -> None:
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--topic", default=None, help="sector code; default: the actor's first")
    parser.add_argument("--scope", default="general", choices=SCOPES)
    parser.add_argument("--depth", default="light", choices=DEPTHS)
    parser.add_argument("--fields", default="",
                        help="comma-separated box keys, or a preset: " + ", ".join(PRESETS))
    parser.add_argument("--categories", default="", help="comma-separated change categories")
    parser.add_argument("--focus", default="", help="words to steer which topic page is read")


def _split(value: str) -> list[str]:
    return [v.strip() for v in str(value or "").split(",") if v.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    _common(sub.add_parser("plan"))
    check = sub.add_parser("check")
    _common(check)
    check.add_argument("--max-usd", type=float, default=None)
    apply = sub.add_parser("apply")
    apply.add_argument("--check-id", required=True)
    # Update requests (migration 570), run by the request runner.
    for name in ("request-plan", "request-create"):
        command = sub.add_parser(name)
        command.add_argument("--json", dest="payload", required=True)
        command.add_argument("--live", action="store_true")
    sub.add_parser("requests")
    status = sub.add_parser("request-status")
    status.add_argument("--id", required=True)
    status.add_argument("--action", required=True, choices=["pause", "resume", "cancel"])
    status.add_argument("--live", action="store_true")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(ROOT))
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)  # API key only; the caller's DATABASE_URL wins
    writes = args.command == "apply" or (
        args.command in ("request-create", "request-status") and args.live)
    if writes and not _local_test_database() \
            and os.environ.get("ACTOR_UPDATE_WRITES_ENABLED", "").lower() != "true":
        print(json.dumps({"ok": False, "error": (
            "Writing actor updates outside a local *_test database needs "
            "ACTOR_UPDATE_WRITES_ENABLED=true (the platform bridge sets it).")}))
        return 0

    from agents.collection.discovery_requests import open_session
    from agents.common.config import load_sources_config

    # The same section load_open_web_config returns, read without importing the
    # search pipeline: that import alone took 10-14 s, and the Discovery page
    # waited 21 s for its list of update requests (2026-10-24).
    config = dict(load_sources_config(ROOT).get("open_web_discovery") or {})
    if not config:
        raise RuntimeError("agents/config/sources.yaml must define open_web_discovery")
    session = open_session()
    try:
        if args.command == "apply":
            result = apply_check(session, args.check_id, config=config)
        elif args.command in ("request-plan", "request-create"):
            payload = json.loads(args.payload)
            if not isinstance(payload, dict):
                raise ActorUpdateError("A request is a JSON object.")
            result = (plan_request(session, payload, config=config)
                      if args.command == "request-plan"
                      else create_request(session, payload, config=config, live=args.live))
        elif args.command == "requests":
            result = {"ok": True, **list_requests(session)}
        elif args.command == "request-status":
            from agents.collection import subscription_store as store
            from agents.collection.subscriptions import SubscriptionError

            try:
                written = store.change_status(session, args.id, args.action, live=args.live)
            except SubscriptionError as exc:
                raise ActorUpdateError(str(exc)) from exc
            result = {"ok": True, "live": written.live, "subscription_id": args.id,
                      "status": written.values["status"]}
        else:
            fields = list(PRESETS.get(args.fields) or _split(args.fields))
            options = dict(actor_id=args.actor_id, topic_code=args.topic, scope=args.scope,
                           depth=args.depth, fields=fields, categories=_split(args.categories),
                           focus=args.focus, config=config)
            result = (plan_update(session, **options) if args.command == "plan"
                      else check_update(session, max_usd=args.max_usd, **options))
    except (ActorUpdateError, ValueError) as exc:
        session.rollback()
        result = {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - the page shows the reason, never a traceback
        session.rollback()
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:400]}
    finally:
        session.close()
    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
