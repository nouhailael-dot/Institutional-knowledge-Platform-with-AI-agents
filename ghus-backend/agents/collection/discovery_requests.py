"""Discovery-page requests from the command line, as JSON.

    python -m agents.collection.discovery_requests list
    python -m agents.collection.discovery_requests options
    python -m agents.collection.discovery_requests preview --json '{...}'
    python -m agents.collection.discovery_requests create  --json '{...}' [--live]
    python -m agents.collection.discovery_requests pause|resume|cancel ID [--live]

The platform's Discovery page calls this, the way Review calls the admission
bridge: the page never writes these tables itself. ``create`` and the status
changes are dry runs unless ``--live`` is given; a dry run validates and prints
what would be written.

Every command prints one JSON object on stdout. Errors are
``{"ok": false, "error": "..."}`` with exit code 2.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import text

from agents.collection import subscription_store as store
from agents.collection.subscriptions import (
    CADENCE_DAYS,
    DEFAULT_NEW_ACTORS_PER_RUN,
    DEFAULT_PULL_DEPTH,
    DISCOVERY_ENTITIES,
    DISCOVERY_PAGE,
    EVENT_TYPES,
    MAX_EVENT_TYPES,
    MAX_FOCUS_TERMS,
    MAX_NEW_ACTORS_PER_RUN,
    PULL_DEPTHS,
    Subscription,
    SubscriptionError,
)
from agents.common.geography import REGION_STATES, STATE_NAMES, normalize_state
from agents.discovery.search.discovery_request import DiscoveryRequest, DiscoveryRequestError

ROOT = Path(__file__).resolve().parents[2]
REGION_NAMES = {
    "northeast": "Northeast",
    "mid_atlantic": "Mid-Atlantic",
    "southeast": "Southeast",
    "midwest_great_lakes": "Midwest / Great Lakes",
    "south_central_texas_gulf": "South Central / Texas Gulf",
    "mountain_west": "Mountain West / Rocky Mountain",
    "west_coast_pacific": "West Coast / Pacific",
}


def _jsonable(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def _max_duration_days() -> int:
    import yaml

    config = yaml.safe_load((ROOT / "config/architecture_v2.yaml").read_text(encoding="utf-8"))
    return int((config.get("actor_update_subscriptions") or {}).get("max_duration_days", 365))


def _draft_fields(payload: dict) -> dict:
    """The page's JSON, checked and normalised. Unknown keys are refused."""

    allowed = {"title", "sector_codes", "topic_ids", "focus_terms", "region_code",
               "state_code", "city", "start_date", "end_date", "cadence",
               "max_new_actors_per_run", "discovery_entity", "discovery_options"}
    unknown = set(payload) - allowed
    if unknown:
        raise SubscriptionError(f"unknown field(s): {sorted(unknown)}")
    today = datetime.now(UTC).date()
    start = date.fromisoformat(payload["start_date"]) if payload.get("start_date") else today
    if not payload.get("end_date"):
        raise SubscriptionError("an end date is required: every request ends")
    end = date.fromisoformat(payload["end_date"])
    if start < today:
        raise SubscriptionError("a request cannot start in the past")
    if (end - start).days > _max_duration_days():
        raise SubscriptionError(f"a request may run for at most {_max_duration_days()} days")
    if bool(payload.get("region_code")) and bool(payload.get("state_code")):
        raise SubscriptionError("choose a region or a state, not both")
    state = None
    if payload.get("state_code"):
        state = normalize_state(payload["state_code"])
        if state is None:
            raise SubscriptionError(f"unknown state {payload['state_code']!r}")
    if payload.get("region_code") and payload["region_code"] not in REGION_STATES:
        raise SubscriptionError(f"unknown region {payload['region_code']!r}")
    entity = str(payload.get("discovery_entity") or "actor")
    options = {k: v for k, v in dict(payload.get("discovery_options") or {}).items()
               if v not in (None, "", [])}
    # A new request chooses only from the event types offered now.
    retired = [t for t in options.get("event_types") or [] if t not in EVENT_TYPES]
    if retired:
        raise SubscriptionError(f"event types are chosen from {list(EVENT_TYPES)}, "
                                f"not {retired}")
    if entity == "actor":
        # Every new organization request reads what it keeps (Light Pull),
        # unless the person opts out.
        options.setdefault("pull_depth", DEFAULT_PULL_DEPTH)
    return {
        "title": str(payload.get("title") or "").strip(),
        "sector_codes": [str(c) for c in payload.get("sector_codes") or []],
        "topic_ids": [str(t) for t in payload.get("topic_ids") or []],
        "focus_terms": [str(t) for t in payload.get("focus_terms") or []],
        "region_code": payload.get("region_code") or None,
        "state_code": state,
        "city": payload.get("city") or None,
        "start_date": start,
        "end_date": end,
        "cadence": str(payload.get("cadence") or "weekly"),
        "max_new_actors_per_run": int(
            payload.get("max_new_actors_per_run") or DEFAULT_NEW_ACTORS_PER_RUN),
        # Organizations unless the page asked for events or people (580).
        "discovery_entity": entity,
        "discovery_options": options,
    }


ANY_SECTOR = "ANY"


def expand_any_sector(fields: dict, codes: dict[str, str]) -> dict:
    """"Any sector": every active sector, and only for a named topic.

    Stored as all active sectors (the schema requires at least one), so a
    result that fits any GHUS sector counts; what is searched for is the topic
    or sub-topics the person named - never an unscoped sweep of an area.
    """
    every = sorted({str(c).upper() for c in codes.values()})
    chosen = [str(c).upper() for c in fields.get("sector_codes") or []]
    if ANY_SECTOR in chosen:
        chosen = every
    if every and set(chosen) >= set(every) and not fields.get("focus_terms"):
        raise SubscriptionError("“Any sector” needs a topic or sub-topic to search for: "
                                "an area alone is the unscoped sweep this design replaces")
    return {**fields, "sector_codes": chosen}


def _preview(fields: dict, codes: dict[str, str], session=None) -> dict:
    """The queries a draft would search, without saving it."""

    from agents.common.config import load_sources_config
    from agents.discovery.search.query_generation import QueryGenerator

    draft = Subscription(subscription_id="preview", requested_via=DISCOVERY_PAGE, **{
        **fields,
        "sector_codes": tuple(c.upper() for c in fields["sector_codes"]),
        "topic_ids": tuple(fields["topic_ids"]),
        "focus_terms": tuple(fields["focus_terms"]),
    })
    request = DiscoveryRequest.from_subscription(draft, topic_codes=codes)
    config = dict(load_sources_config(ROOT).get("open_web_discovery") or {})
    bundle = QueryGenerator(None, config).generate(
        request.entity, session=session, project_root=ROOT, request=request)
    where = dict((bundle.metadata or {}).get("query_domains") or {})
    return {"request": request.describe(),
            # A people search shows the sites it is limited to.
            "queries": [f"{q}  [on {', '.join(where[q])}]" if where.get(q) else q
                        for q in bundle.queries],
            "first_run": draft.next_due(draft.start_date)}


def _options(session) -> dict:
    topics = [
        dict(row) for row in session.execute(text(
            "SELECT topic_id::text AS topic_id, code, name FROM topic WHERE active ORDER BY name"
        )).mappings()
    ]
    return {
        "topics": topics,
        "regions": [{"code": code, "name": REGION_NAMES.get(code, code),
                     "states": list(states)} for code, states in REGION_STATES.items()],
        "states": [{"code": code, "name": name} for code, name in sorted(
            STATE_NAMES.items(), key=lambda item: item[1])],
        "cadences": [c for c in CADENCE_DAYS],
        "max_focus_terms": MAX_FOCUS_TERMS,
        "max_new_actors_per_run": MAX_NEW_ACTORS_PER_RUN,
        "default_new_actors_per_run": DEFAULT_NEW_ACTORS_PER_RUN,
        "max_duration_days": _max_duration_days(),
        # What a request can find, and an event request's types (migration 580).
        "entities": list(DISCOVERY_ENTITIES),
        "entity_requests_ready": store.has_entity_requests(session),
        "event_types": list(EVENT_TYPES),
        "max_event_types": MAX_EVENT_TYPES,
        "pull_depths": list(PULL_DEPTHS),
        "default_pull_depth": DEFAULT_PULL_DEPTH,
    }


def _list(session) -> dict:
    today = datetime.now(UTC).date()
    requests = []
    for row in store.load_discovery_requests(session):
        item = dict(row)
        try:
            sub = store.subscription_from_row(row)
            item["next_run"] = sub.next_due(today)
            item["skip_reason"] = sub.skip_reason(today)
        except ValueError as exc:
            item["next_run"], item["skip_reason"] = None, f"invalid: {exc}"
        item["runs"] = store.load_request_runs(session, str(row["subscription_id"]))
        run_ids = [run.get("search_run_id") for run in item["runs"]]
        entity = str(row.get("discovery_entity") or "actor")
        item["results"] = store.load_request_results(session, run_ids, entity=entity)
        item["excluded"] = store.load_request_exclusions(session, run_ids, entity=entity)
        requests.append(item)
    return {"requests": requests}


def open_session():
    """A database session for one command.

    The page waits on this command, so it must start quickly. The shared
    session factory resolves public IPv4 addresses for hosted databases (via
    PowerShell on Windows), which costs seconds and is pointless for a local
    one; a loopback database gets a plain engine instead.
    """
    import os

    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session

    raw = os.environ.get("DATABASE_URL", "")
    if raw and make_url(raw).host in ("127.0.0.1", "localhost", "::1"):
        return Session(create_engine(raw, pool_pre_ping=True))
    from src.db.session import SessionLocal

    return SessionLocal()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["list", "options", "preview", "create",
                                            "pause", "resume", "cancel"])
    parser.add_argument("subscription_id", nargs="?")
    parser.add_argument("--json", dest="payload", default="{}")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args(argv)

    try:
        with open_session() as session:
            if args.command == "list":
                result = _list(session)
            elif args.command == "options":
                result = _options(session)
            elif args.command in ("preview", "create"):
                fields = _draft_fields(json.loads(args.payload))
                codes = store.topic_codes(session)
                fields = expand_any_sector(fields, codes)
                preview = _preview(fields, codes, session)
                if args.command == "preview":
                    result = preview
                else:
                    written = store.create_request(session, live=args.live, **fields)
                    result = {**preview, "live": written.live,
                              "subscription_id": written.subscription_id}
            else:
                if not args.subscription_id:
                    raise SubscriptionError("a request id is required")
                written = store.change_status(session, args.subscription_id, args.command,
                                              live=args.live)
                result = {"live": written.live, "subscription_id": args.subscription_id,
                          "status": written.values["status"]}
    except (SubscriptionError, DiscoveryRequestError, ValueError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    print(json.dumps({"ok": True, **_jsonable(result)}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
