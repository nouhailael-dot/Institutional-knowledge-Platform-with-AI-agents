"""Update ONE existing actor: re-read its own pages for the boxes asked for.

    python -m agents.collection.actor_updates update --actor-id ID [--topic CODE]
        [--fields funding_signal,recent_activity] [--live] [--max-usd 0.15]

The Discovery page's "Actor updates" panel calls this through the platform's
bridge. It reads the actor's homepage, About page and one topic page
(``light_pull_reader``: three pages, checked quotes, Light Pull evidence rules)
and compares every requested box with what the map holds now:

    filled      nothing was recorded, the pages now state it
    updated     the pages state something different from what is recorded
    confirmed   the pages state what is recorded (corroboration, no new value)
    unchanged   the pages do not state it; what is recorded is kept
    not stated  the pages do not state it, and nothing was recorded
    refused     an answer failed the quote check or a Light Pull rule

With ``--live`` the results are written through
``agents.enrichment.decisions.append_actor_fact`` - the approved immutable
writer, which corroborates, supersedes and routes conflicts. One rule is added
here: a page that is silent never overwrites a recorded value, because "not on
today's pages" is not evidence that last year's grant did not happen.

Dry-run by default: the pages are read and the model is called (the only way
to show what would change), nothing is written. Live writes against a database
other than a local ``*_test`` one also need ACTOR_UPDATE_WRITES_ENABLED=true,
which only the platform bridge sets.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]

# What a person usually means by "update this actor".
PRESETS = {
    "funding_activity": ("funding_signal", "recent_activity"),
    "connections": ("international_connection", "um6p_ocp_connection"),
}


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
    row = session.execute(text(
        "SELECT a.actor_id::text AS actor_id, a.name, "
        "NULLIF(to_jsonb(a)->>'website', '') AS website, "
        "NULLIF(to_jsonb(a)->>'actor_category', '') AS actor_category, "
        "NULLIF(to_jsonb(a)->>'category_type', '') AS category_type, "
        "COALESCE(NULLIF(to_jsonb(a)->>'status', ''), NULLIF(to_jsonb(a)->>'record_status', '')) "
        "AS status FROM actor a WHERE a.actor_id = CAST(:id AS uuid)"
    ), {"id": actor_id}).mappings().first()
    if row is None:
        return None
    actor = dict(row)
    actor["topics"] = actor_topics(session, actor_id)
    return actor


def current_values(session, actor_id: str, topic_id: str, keys) -> dict[str, dict]:
    """What the map holds now for each box: the current pointer's fact."""
    rows = session.execute(text(
        "SELECT p.fact_key, f.collection_state, f.fact_value, f.confidence, "
        "f.retrieved_at FROM actor_fact_current_pointer p "
        "JOIN actor_fact f ON f.actor_fact_id = p.actor_fact_id "
        "WHERE p.actor_id = CAST(:a AS uuid) AND p.topic_id = CAST(:t AS uuid) "
        "AND p.fact_key = ANY(:keys)"
    ), {"a": actor_id, "t": topic_id, "keys": list(keys)}).mappings()
    return {r["fact_key"]: dict(r) for r in rows}


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


def _same(before, after) -> bool:
    """The same fact, possibly worded differently.

    The model rephrases between reads ("Paid customers over $1.5 billion" /
    "CPower has paid customers over $1.5 billion"), which an exact comparison
    reported as an update. Same fact = the same numbers - an amount, a year, a
    date - and most of the shorter wording found in the longer.
    """
    numbers_a, words_a = _signature(before)
    numbers_b, words_b = _signature(after)
    if numbers_a != numbers_b:
        return False
    if not words_a or not words_b:
        return bool(numbers_a)
    return len(words_a & words_b) / min(len(words_a), len(words_b)) >= 0.7


def compare(field: str, before: dict | None, evidence: dict | None,
            rejected: str | None) -> dict:
    """One box: what was recorded, what the pages say, and what that means."""
    had = bool(before) and before.get("collection_state") == "found"
    found = bool(evidence) and evidence.get("collection_state") == "found"
    if rejected and not found:
        # A refused answer never touches what is recorded; with nothing
        # recorded it is reported as refused, with the reason.
        outcome = "unchanged" if had else "refused"
    elif found and not had:
        outcome = "filled"
    elif found and _same(before.get("fact_value"), evidence.get("value")):
        outcome = "confirmed"
    elif found:
        outcome = "updated"
    else:
        outcome = "unchanged" if had else "not stated"
    return {
        "field": field,
        "outcome": outcome,
        "before": before.get("fact_value") if had else None,
        "before_read": str(before.get("retrieved_at") or "")[:10] if had else None,
        "after": evidence.get("value") if found else None,
        "source_url": evidence.get("source_url") if found else None,
        "reason": rejected,
    }


def update_actor(session, *, actor_id: str, topic_code: str | None, fields, live: bool,
                 max_usd: float, reader_factory=None) -> dict:
    actor = load_actor(session, actor_id)
    if actor is None:
        return {"ok": False, "error": "No actor with that id."}
    if not str(actor.get("website") or "").strip():
        return {"ok": False, "actor": actor,
                "error": "This actor has no website on record, so there are no pages "
                         "of its own to read. Add the website in Review first."}
    topics = actor["topics"]
    # A sector the person chose wins - it may be one the actor is not linked to
    # yet, which is exactly the case for imported actors. Otherwise its own.
    chosen = topic_by_code(session, topic_code) if topic_code else None
    topic = chosen or (topics[0] if topics else None)
    if topic is None:
        return {"ok": False, "actor": actor, "needs_topic": True,
                "error": "This actor is not linked to a sector yet, and facts are kept "
                         "per sector. Choose the sector to update it for."}

    from agents.collection.light_pull import CATEGORY_LIGHT_FIELDS
    from agents.collection.light_pull_reader import COMMON_READ_FIELDS

    allowed = [*COMMON_READ_FIELDS, *CATEGORY_LIGHT_FIELDS.get(actor["actor_category"] or "", ())]
    wanted = [f for f in (fields or allowed) if f in allowed] or list(allowed)

    if reader_factory is None:
        from agents.collection.light_pull_candidates import _reader
        from agents.discovery.search.run import load_open_web_config

        reader, meter, model = _reader(load_open_web_config(ROOT), max_usd)
    else:
        reader, meter, model = reader_factory(max_usd)

    before = current_values(session, actor_id, topic["topic_id"], wanted)
    read_at = datetime.now(UTC)
    read = reader.read(name=actor["name"], website=actor["website"],
                       actor_category=actor["actor_category"],
                       category_type=str(actor.get("category_type") or ""),
                       topic_terms=[topic["name"]], read_at=read_at, fields=wanted)
    if not read.pages:
        # Nothing was read - the site refused (403), did not resolve, or had no
        # text. Reporting each box as "not stated" would claim the pages were
        # read and were silent; say what actually happened instead.
        return {"ok": False, "actor": {k: actor[k] for k in ("actor_id", "name", "website")},
                "error": f"{actor['name']}'s website could not be read, so nothing was "
                         f"compared or written. {read.error or ''}".strip(),
                "cost_usd": round(float(meter.spent_usd), 4)}
    boxes = [compare(f, before.get(f), read.evidence.get(f), read.rejected.get(f))
             for f in wanted]

    written = 0
    if live and read.pages:
        from agents.enrichment.decisions import ActorFactWrite, append_actor_fact

        for box in boxes:
            evidence = read.evidence.get(box["field"]) or {}
            # A silent page never overwrites a recorded value.
            if box["outcome"] in {"unchanged", "refused"} or not evidence:
                continue
            append_actor_fact(session, ActorFactWrite(
                actor_id=actor_id, topic_id=topic["topic_id"], fact_type="light_pull",
                field_key=box["field"], value=evidence.get("value"), layer=1,
                collection_state=evidence["collection_state"],
                confidence=evidence.get("confidence") or "medium",
                source_url=evidence.get("source_url") or read.pages[0],
                date_read=read_at, source_origin="newly_found",
                created_by="agent:actor_updates",
            ), live=True)
            written += 1
        session.commit()

    counts: dict[str, int] = {}
    for box in boxes:
        counts[box["outcome"]] = counts.get(box["outcome"], 0) + 1
    return {
        "ok": read.error is None,
        "error": read.error,
        "mode": "live" if live else "preview",
        "actor": {k: actor[k] for k in ("actor_id", "name", "website", "actor_category",
                                        "status")},
        "topic": {"code": topic["code"], "name": topic["name"], "source": topic.get("source")},
        "topics": [{"code": t["code"], "name": t["name"]} for t in topics],
        "pages_read": read.pages,
        "boxes": boxes,
        "counts": counts,
        "written": written,
        "cost_usd": round(float(meter.spent_usd), 4),
        "model": model,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    up = sub.add_parser("update")
    up.add_argument("--actor-id", required=True)
    up.add_argument("--topic", default=None, help="sector code; default: the actor's first")
    up.add_argument("--fields", default="",
                    help="comma-separated box keys, or a preset: "
                         + ", ".join(PRESETS) + "; empty means every box")
    up.add_argument("--live", action="store_true", help="write; absent means preview")
    up.add_argument("--max-usd", type=float, default=0.15)
    args = parser.parse_args(argv)

    sys.path.insert(0, str(ROOT))
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)  # API key only; the caller's DATABASE_URL wins
    if args.live and not _local_test_database() \
            and os.environ.get("ACTOR_UPDATE_WRITES_ENABLED", "").lower() != "true":
        print(json.dumps({"ok": False, "error": (
            "Live actor updates outside a local *_test database need "
            "ACTOR_UPDATE_WRITES_ENABLED=true (the platform bridge sets it).")}))
        return 0
    fields = PRESETS.get(args.fields) or [f.strip() for f in args.fields.split(",") if f.strip()]

    from agents.collection.discovery_requests import open_session

    session = open_session()
    try:
        result = update_actor(session, actor_id=args.actor_id, topic_code=args.topic,
                              fields=fields, live=args.live, max_usd=args.max_usd)
    except Exception as exc:  # noqa: BLE001 - the page shows the reason, never a traceback
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:400]}
    finally:
        session.close()
    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
