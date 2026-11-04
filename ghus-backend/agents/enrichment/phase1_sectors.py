"""Give the verified Phase 1 organizations their sectors.

    python -m agents.enrichment.phase1_sectors --plan PLAN.json [--max-usd 0.50]
    python -m agents.enrichment.phase1_sectors --apply PLAN.json --live

Phase 1 records were migrated with no sector, so Organization Updates refuses
them and sector filters skip them. Two sources of evidence, no page reads:

* Hub membership (free): an organization in a GHUS hub gets the sectors of
  that hub - Fatima Zahra's own Phase 1 mapping. One sector is the primary;
  with several, the primary is the one sector that is primary in its hubs, or
  none for a reviewer to choose.
* Stored description (a few cents): an organization in no hub is classified
  from its own stored name and description by a small model, which must quote
  the words it relied on. Only its main sector is linked. A missing or
  placeholder description, a weak answer, a quote not found in the description,
  or a quote that is only the organization's name leaves it unlinked and listed.

``--plan`` writes nothing: it decides every link and saves the plan, so a
person can read it first. ``--apply`` writes exactly that plan through
``agents.enrichment.decisions.link_actor_sector``, which never changes an
existing link; it needs ``--live`` (otherwise it reports what it would do), and
refuses any database but a local ``*_test`` one unless
``--allow-shared-database`` is given by the authorised operator.
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

MODEL = "claude-haiku-4-5"
PRICING = {"input_usd_per_million": 1.0, "output_usd_per_million": 5.0}
PLACEHOLDER_MARKERS = ("should be verified from primary sources",)
MIN_DESCRIPTION_CHARS = 40
HUB_SOURCE_URL = "urn:ghus:phase1-hub-membership"
DESCRIPTION_SOURCE_URL = "urn:ghus:phase1-stored-description"

UNLINKED_SQL = """
SELECT a.actor_id::text AS actor_id, a.name, a.actor_category, COALESCE(a.description, '') AS description
FROM actor a
WHERE a.status = 'verified'
  AND NOT EXISTS (SELECT 1 FROM actor_sector s WHERE s.actor_id = a.actor_id)
ORDER BY a.name
"""

HUB_SECTORS_SQL = """
SELECT ha.actor_id::text AS actor_id, h.name AS hub, sec.code, hs.is_primary
FROM hub_actor ha
JOIN hub h ON h.hub_id = ha.hub_id
JOIN hub_sector hs ON hs.hub_id = ha.hub_id
JOIN sector sec ON sec.sector_id = hs.sector_id AND sec.active
WHERE ha.actor_id = ANY(CAST(:ids AS uuid[]))
ORDER BY h.name, sec.code
"""


def _guard(allow_shared: bool) -> None:
    raw = os.environ.get("DATABASE_URL", "")
    parts = urlsplit(raw.replace("postgresql+psycopg", "postgresql"))
    local = parts.hostname in {"127.0.0.1", "localhost", "::1"} and parts.path.endswith("_test")
    if not local and not allow_shared:
        raise SystemExit("phase1_sectors: DATABASE_URL is not a local *_test database; "
                         "pass --allow-shared-database only as the authorised operator")


def hub_links(rows: list[dict]) -> list[dict]:
    """One actor's hub sectors as planned links, with the primary rule applied."""
    codes = sorted({row["code"] for row in rows})
    hubs_by_code = {code: sorted({row["hub"] for row in rows if row["code"] == code})
                    for code in codes}
    primaries = {row["code"] for row in rows if row["is_primary"]}
    primary = codes[0] if len(codes) == 1 else (next(iter(primaries)) if len(primaries) == 1 else None)
    return [{"sector": code, "primary": code == primary, "match_strength": "moderate",
             "reason": (f"Phase 1 hub membership: a member of {', '.join(hubs_by_code[code])}, "
                        f"whose sector is {code} (GHUS Phase 1 ecosystem mapping). "
                        "Derived, not read from the organization's own pages.")}
            for code in codes]


def usable_description(description: str) -> bool:
    text_ = " ".join(str(description or "").split())
    return (len(text_) >= MIN_DESCRIPTION_CHARS
            and not any(marker in text_.lower() for marker in PLACEHOLDER_MARKERS))


def _words(value: str) -> str:
    """Lower-case words only, so curly quotes, dashes and spacing never decide a match."""
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def quote_in(quote: str, description: str) -> bool:
    """Every piece of the quote (split at commas, dashes, semicolons, full stops and
    ellipses) is in the description, word for word; at least eight characters in all."""
    pieces = [_words(piece) for piece in re.split(r"[,;:.—–()…]|\s-\s", quote)]
    pieces = [piece for piece in pieces if piece]
    haystack = _words(description)
    return (len("".join(pieces)) >= 8
            and all(piece in haystack for piece in pieces))


def _schema(codes: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "sectors": {"type": "array", "maxItems": 2, "items": {"type": "string", "enum": codes},
                        "description": "The sector(s) the description plainly supports, main one first."},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "evidence_quote": {"type": "string",
                               "description": ("ONE continuous phrase (5-25 words) copied exactly "
                                               "from the description; never join phrases.")},
        },
        "required": ["sectors", "confidence", "evidence_quote"],
    }


def classify_from_description(client, actor: dict, sectors: list[dict]) -> dict:
    """Ask for the sector(s) a stored description supports; keep only a checked answer."""
    raw = client.extract_with_tool(
        system=("Classify a GHUS ecosystem organization into GHUS sectors using ONLY its stored "
                "name and description. Choose a sector only when the description plainly says the "
                "organization works in it; never guess from fame or general knowledge. Copy the "
                "words you relied on exactly, as one continuous phrase. If nothing fits, return no "
                "sectors and low confidence."),
        user=json.dumps({"organization_name": actor["name"],
                         "actor_category": actor["actor_category"],
                         "description": actor["description"],
                         "sectors": [{"code": s["code"], "name": s["name"]} for s in sectors]}),
        tool_name="classify_sector", tool_description="Choose GHUS sectors from the description.",
        input_schema=_schema([s["code"] for s in sectors]), max_tokens=300,
    ) or {}
    valid = {s["code"] for s in sectors}
    codes = [c for c in dict.fromkeys(str(c).upper() for c in raw.get("sectors") or []) if c in valid]
    quote = " ".join(str(raw.get("evidence_quote") or "").split())
    if not codes or raw.get("confidence") not in ("high", "medium"):
        return {"links": [], "unclear": "the description does not plainly support a sector"}
    words = _words(quote)
    if not quote_in(quote, actor["description"]):
        return {"links": [], "unclear": "the model's quote is not in the description"}
    name_words = set(_words(actor["name"]).split())
    if set(words.split()) <= name_words:
        return {"links": [], "unclear": "the only evidence is the organization's name"}
    # The main sector only: a second one read from a description is too often a stretch.
    return {"links": [{"sector": codes[0], "primary": True, "match_strength": "moderate",
                       "reason": (f"Classified from the stored Phase 1 description (\"{quote[:300]}\"). "
                                  "Agent-assigned and awaiting GHUS review.")}]}


def build_plan(session, client, *, max_usd: float, limit: int | None = None) -> dict:
    actors = [dict(row) for row in session.execute(text(UNLINKED_SQL)).mappings()]
    if limit:
        actors = actors[:limit]
    hub_rows: dict[str, list[dict]] = {}
    if actors:
        for row in session.execute(text(HUB_SECTORS_SQL),
                                   {"ids": [a["actor_id"] for a in actors]}).mappings():
            hub_rows.setdefault(row["actor_id"], []).append(dict(row))
    sectors = [dict(row) for row in session.execute(text(
        "SELECT code, name FROM sector WHERE active ORDER BY code")).mappings()]
    planned, unclear = [], []
    for actor in actors:
        entry = {"actor_id": actor["actor_id"], "name": actor["name"]}
        if actor["actor_id"] in hub_rows:
            planned.append({**entry, "via": "hub", "links": hub_links(hub_rows[actor["actor_id"]])})
            continue
        if not usable_description(actor["description"]):
            unclear.append({**entry, "reason": "no usable stored description (empty or placeholder)"})
            continue
        if client is None:
            unclear.append({**entry, "reason": "description classification not run"})
            continue
        if client.usage.cost_usd >= max_usd:
            unclear.append({**entry, "reason": "spending cap reached before this organization"})
            continue
        try:
            result = classify_from_description(client, actor, sectors)
        except Exception as exc:  # noqa: BLE001 - one failed read leaves one organization unlinked
            result = {"links": [], "unclear": f"classification failed: {type(exc).__name__}"}
        if result["links"]:
            planned.append({**entry, "via": "description", "links": result["links"]})
        else:
            unclear.append({**entry, "reason": result["unclear"]})
    by_via = {via: sum(1 for p in planned if p["via"] == via) for via in ("hub", "description")}
    return {"created_at": datetime.now(UTC).isoformat(), "model": MODEL,
            "summary": {"organizations": len(actors), "linked_via_hub": by_via["hub"],
                        "linked_via_description": by_via["description"], "unclear": len(unclear),
                        "links": sum(len(p["links"]) for p in planned),
                        "cost_usd": round(client.usage.cost_usd, 4) if client else 0.0},
            "planned": planned, "unclear": unclear}


def apply_plan(session, plan: dict, *, live: bool) -> dict:
    from agents.common.provenance import insert_source
    from agents.enrichment.decisions import link_actor_sector

    sources: dict[str, str | None] = {"hub": None, "description": None}
    if live:
        sources["hub"] = insert_source(
            session, source_url=HUB_SOURCE_URL, fetched_at=None, source_type="system",
            trust_tier="derived",
            description="Phase 1 sectors from GHUS hub membership (Phase 1 ecosystem mapping)")
        sources["description"] = insert_source(
            session, source_url=DESCRIPTION_SOURCE_URL, fetched_at=None,
            source_type="agent_enrichment", trust_tier="candidate",
            description=f"Phase 1 sectors classified from stored descriptions ({MODEL})")
    counts: dict[str, int] = {}
    for item in plan["planned"]:
        for link in item["links"]:
            outcome = link_actor_sector(
                session, actor_id=item["actor_id"], sector_code=link["sector"],
                source_id=sources[item["via"]], reason=link["reason"],
                match_strength=link["match_strength"], primary=link["primary"], live=live)
            counts[outcome["action"]] = counts.get(outcome["action"], 0) + 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", metavar="PLAN.json", help="decide the links; write nothing")
    mode.add_argument("--apply", metavar="PLAN.json", help="write a saved plan's links")
    parser.add_argument("--live", action="store_true", help="with --apply: save")
    parser.add_argument("--max-usd", type=float, default=0.50)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--no-model", action="store_true", help="hub links only, no model calls")
    parser.add_argument("--allow-shared-database", action="store_true")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    _guard(args.allow_shared_database)
    from agents.collection.discovery_requests import open_session

    if args.plan:
        client = None
        if not args.no_model:
            from agents.common.cost import CostMeter
            from agents.common.llm import ClaudeToolClient

            client = ClaudeToolClient(MODEL, cost_meter=CostMeter(max_usd=args.max_usd), **PRICING)
        with open_session() as session:
            plan = build_plan(session, client, max_usd=args.max_usd, limit=args.limit)
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
