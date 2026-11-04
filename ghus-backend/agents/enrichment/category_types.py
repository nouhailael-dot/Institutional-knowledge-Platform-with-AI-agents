"""Give organizations without a Category Type one from their own category's list.

    python -m agents.enrichment.category_types --plan PLAN.json [--max-usd 2.00] [--limit N]
    python -m agents.enrichment.category_types --apply PLAN.json --live

730 of 743 Directory organizations (the Phase 1 records) were migrated with a
category and no type, and the type was only ever proposed one record at a time.
The category is kept as it is; the type is chosen from that category's list by
``classify_type_for_existing_category`` (a small model, no page read), from
what COMPASS holds about the organization: its name, description and focus.

``--plan`` writes nothing: it classifies and saves the plan. Only a confident
answer is planned; a doubtful one, or a catch-all ("Not Applicable"), stays
empty for a person. ``--apply`` writes the plan through
``agents.enrichment.decisions.fill_category_type``, which fills an empty type
only and never changes one already set. It needs ``--live`` and refuses any
database but a local ``*_test`` one unless ``--allow-shared-database`` is given.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
MODEL = "claude-haiku-4-5"
PRICING = {"input_usd_per_million": 1.0, "output_usd_per_million": 5.0}
# A stronger model when the records hold little text and the type turns on who
# operates or owns the organization (4 Nov 2026 sample).
MODELS = {"claude-haiku-4-5": PRICING,
          "claude-sonnet-5": {"input_usd_per_million": 3.0, "output_usd_per_million": 15.0}}
PLACEHOLDER = "should be verified from primary sources"

UNTYPED_SQL = """
SELECT a.actor_id::text AS actor_id, a.name, a.actor_category,
       concat_ws(' ', NULLIF(a.description, ''), to_jsonb(a)->>'primary_technical_focus',
                 to_jsonb(a)->>'current_activities') AS about
FROM actor_read a
WHERE a.merged_into_actor_id IS NULL AND COALESCE(a.status, '') <> 'rejected'
  AND a.actor_category IS NOT NULL
  AND (a.category_type IS NULL OR a.category_type IN ('', 'not_classified'))
ORDER BY a.name
"""


def _guard(allow_shared: bool) -> None:
    raw = os.environ.get("DATABASE_URL", "")
    parts = urlsplit(raw.replace("postgresql+psycopg", "postgresql"))
    local = parts.hostname in {"127.0.0.1", "localhost", "::1"} and parts.path.endswith("_test")
    if not local and not allow_shared:
        raise SystemExit("category_types: DATABASE_URL is not a local *_test database; "
                         "pass --allow-shared-database only as the authorised operator")


def what_it_does(about: str) -> str:
    """What COMPASS holds about it, without the Phase 1 placeholder sentence."""
    text_ = " ".join(str(about or "").split())
    return "" if PLACEHOLDER in text_.lower() else text_[:1500]


def classify(client, actor: dict, catalog) -> dict:
    """{"category_type"} when confident, else {"unclear": reason}."""
    from agents.common.actor_classification import (
        CATCH_ALL_TYPE_CODES,
        classify_type_for_existing_category,
    )

    try:
        result = classify_type_for_existing_category(
            client, name=actor["name"], self_description=what_it_does(actor["about"]),
            actor_category=actor["actor_category"], catalog=catalog)
    except Exception as exc:  # noqa: BLE001 - one record stays empty, the rest go on
        return {"unclear": f"not classified: {type(exc).__name__}"}
    if result.category_type in CATCH_ALL_TYPE_CODES or result.category_needs_review:
        return {"unclear": "no type in its category's list fits clearly"}
    return {"category_type": result.category_type}


def build_plan(session, client, *, max_usd: float, limit: int | None = None) -> dict:
    from agents.common.actor_classification import load_category_catalog

    catalog = load_category_catalog()
    actors = [dict(r) for r in session.execute(text(UNTYPED_SQL)).mappings()]
    if limit:
        actors = actors[:limit]
    planned, unclear = [], []
    for actor in actors:
        entry = {"actor_id": actor["actor_id"], "name": actor["name"],
                 "actor_category": actor["actor_category"]}
        if not catalog.type_codes(actor["actor_category"]):
            unclear.append({**entry, "reason": "its category has no type list"})
            continue
        if client.usage.cost_usd >= max_usd:
            unclear.append({**entry, "reason": "spending cap reached before this organization"})
            continue
        result = classify(client, actor, catalog)
        if "category_type" in result:
            planned.append({**entry, "category_type": result["category_type"]})
        else:
            unclear.append({**entry, "reason": result["unclear"]})
    return {"created_at": datetime.now(UTC).isoformat(), "model": MODEL,
            "summary": {"organizations": len(actors), "typed": len(planned),
                        "left_empty": len(unclear),
                        "by_type": dict(Counter(p["category_type"] for p in planned).most_common()),
                        "cost_usd": round(client.usage.cost_usd, 4)},
            "planned": planned, "unclear": unclear}


def apply_plan(session, plan: dict, *, live: bool) -> dict:
    from agents.enrichment.decisions import fill_category_type

    counts: dict[str, int] = {}
    for item in plan["planned"]:
        outcome = fill_category_type(session, actor_id=item["actor_id"],
                                     actor_category=item["actor_category"],
                                     category_type=item["category_type"], live=live)
        counts[outcome["action"]] = counts.get(outcome["action"], 0) + 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", metavar="PLAN.json", help="classify; write nothing")
    mode.add_argument("--apply", metavar="PLAN.json", help="write a saved plan's types")
    parser.add_argument("--live", action="store_true", help="with --apply: save")
    parser.add_argument("--max-usd", type=float, default=2.00)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--allow-shared-database", action="store_true")
    parser.add_argument("--model", choices=sorted(MODELS), default=MODEL)
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    _guard(args.allow_shared_database)
    from agents.collection.discovery_requests import open_session

    if args.plan:
        from agents.common.cost import CostMeter
        from agents.common.llm import ClaudeToolClient

        client = ClaudeToolClient(args.model, cost_meter=CostMeter(max_usd=args.max_usd),
                                  **MODELS[args.model])
        with open_session() as session:
            plan = build_plan(session, client, max_usd=args.max_usd, limit=args.limit)
            plan["model"] = args.model
            session.rollback()
        Path(args.plan).write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(plan["summary"]))
        return 0
    plan = json.loads(Path(args.apply).read_text(encoding="utf-8"))
    with open_session() as session:
        # One transaction: the whole plan is written, or none of it.
        counts = apply_plan(session, plan, live=args.live)
        if args.live:
            session.commit()
        else:
            session.rollback()
    print(json.dumps({"live": args.live, "outcomes": counts}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
