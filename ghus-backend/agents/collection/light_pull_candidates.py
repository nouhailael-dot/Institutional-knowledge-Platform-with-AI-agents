"""Collect the full Light Pull for kept discovery candidates, or for existing actors.

    python -m agents.collection.light_pull_candidates --request-id ID [--live]
    python -m agents.collection.light_pull_candidates --search-run RUN_ID [--live]
    python -m agents.collection.light_pull_candidates --actors [--live]

Candidates (accepted or sent to Review): their own homepage, About page and one
topic page are read once (``light_pull_reader``) and every Light Pull box is
answered - found with a checked quote, or not stated on the pages read. The
answers are kept on the candidate, so Review shows every box before anyone
decides, and admission writes them as canonical facts through promotion when a
person verifies the actor. Nothing canonical is written here for candidates.

Existing actors (``--actors``): the same read, written through
``agents.enrichment.decisions.append_actor_fact`` - the approved immutable fact
writer, which corroborates, supersedes and routes conflicts. An actor is never
created or duplicated here.

Dry-run by default: pages are read and the model is called (that is the only
way to show what would be written), nothing is saved. ``--live`` saves. The
spend is capped by ``--max-usd`` (default ``light_pull_max_usd_per_run``) and
reported per organisation. Refuses any database but a local ``*_test`` one
unless ``--allow-shared-database`` is given by the operator.

``--missing-only`` (the Data Feed's "Complete missing information"): only the
boxes a candidate's record has no value for are read, and a value a GHUS person
supplied is never replaced - the new readings fill the empty boxes beside it.
``--estimate`` reads nothing and calls no model: it lists the candidates, the
boxes each would read, and the expected cost from what past reads cost.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]


def _guard(allow_shared: bool) -> None:
    raw = os.environ.get("DATABASE_URL", "")
    parts = urlsplit(raw.replace("postgresql+psycopg", "postgresql"))
    local = parts.hostname in {"127.0.0.1", "localhost", "::1"} and parts.path.endswith("_test")
    if not local and not allow_shared:
        raise SystemExit("light_pull_candidates: DATABASE_URL is not a local *_test database; "
                         "pass --allow-shared-database only as the authorised operator")


def _topic_terms_for_runs(session, run_ids: list[str]) -> dict[str, list[str]]:
    """The request's title, focus terms and sector names, per search run."""
    rows = session.execute(text(
        "SELECT cr.config_snapshot->>'search_run_id' AS run_id, s.title, s.focus_terms, "
        "s.sector_codes FROM actor_update_subscription s "
        "JOIN actor_update_subscription_run r "
        "  ON r.actor_update_subscription_id = s.actor_update_subscription_id "
        "JOIN collection_run cr ON cr.collection_run_id = r.collection_run_id "
        "WHERE cr.config_snapshot->>'search_run_id' = ANY(:ids)"
    ), {"ids": run_ids}).mappings()
    terms: dict[str, list[str]] = {}
    for row in rows:
        names = session.execute(text(
            "SELECT name FROM sector WHERE code = ANY(:codes)"
        ), {"codes": list(row["sector_codes"] or [])}).scalars().all()
        terms[str(row["run_id"])] = [t for t in [row["title"], *(row["focus_terms"] or []),
                                                 *names] if t]
    return terms


def _runs_for_request(session, request_id: str) -> list[str]:
    return [str(r) for r in session.execute(text(
        "SELECT cr.config_snapshot->>'search_run_id' FROM actor_update_subscription_run r "
        "JOIN collection_run cr ON cr.collection_run_id = r.collection_run_id "
        "WHERE r.actor_update_subscription_id = CAST(:id AS uuid) "
        "AND cr.config_snapshot->>'search_run_id' IS NOT NULL"
    ), {"id": request_id}).scalars().all()]


def candidate_targets(session, run_ids: list[str], *, force: bool, limit: int) -> list[dict]:
    rows = session.execute(text(
        "SELECT candidate_id::text AS candidate_id, run_id::text AS run_id, record_preview "
        "FROM search_candidate WHERE run_id::text = ANY(:ids) AND entity_type = 'actor' "
        "AND score_band IN ('auto_high', 'review') "
        "AND COALESCE(record_preview->>'website', '') <> '' "
        + ("" if force else "AND NOT (record_preview ? 'light_pull_read') ")
        + "ORDER BY score_band, fit_score DESC NULLS LAST LIMIT :limit"
    ), {"ids": run_ids, "limit": limit}).mappings().all()
    return [dict(r) for r in rows]


# When no Light Pull has been paid for yet: one Sonnet call over three pages.
DEFAULT_COST_PER_ORGANISATION = 0.05
# Boxes that describe the record itself, not something its pages state.
_RECORD_BOX_KEYS = {"location": ("city", "location_city", "state", "state_code")}


def missing_boxes(record: dict) -> list[str]:
    """The Light Pull boxes this candidate has no value for, in reading order.

    A box already ``found`` - read earlier, or supplied by a GHUS person - is
    never asked again. Location is the record's own when it has a city or a
    state. "Why it matched" is about the topic a search was run for, which a
    record GHUS supplied through the Data Feed did not have. A Data Feed record
    that matches an actor already on the map is completed by updating that
    actor (Actor updates), not by reading it again here.
    """
    if ((record.get("data_feed") or {}).get("match") or {}).get("kind") == "existing":
        return []
    from agents.collection.light_pull import CATEGORY_LIGHT_FIELDS
    from agents.collection.light_pull_reader import COMMON_READ_FIELDS

    evidence = record.get("light_pull_evidence") or {}
    wanted = []
    for key in (*COMMON_READ_FIELDS,
                *CATEGORY_LIGHT_FIELDS.get(str(record.get("actor_category") or ""), ())):
        if (evidence.get(key) or {}).get("collection_state") == "found":
            continue
        if any(record.get(field) for field in _RECORD_BOX_KEYS.get(key, ())):
            continue
        if key == "why_matched" and "data_feed" in record:
            continue
        if key not in wanted:
            wanted.append(key)
    return wanted


def keep_supplied(existing: dict, read: dict) -> dict:
    """New readings for the empty boxes; every box already found stays as it was."""
    kept = {k: v for k, v in (existing or {}).items() if (v or {}).get("collection_state") == "found"}
    return {**read, **kept}


def cost_per_organisation(session) -> tuple[float, str]:
    """What one organisation's Light Pull has cost here, on average, and why that figure."""
    row = session.execute(text(
        "SELECT count(*), avg((record_preview->'light_pull_read'->>'cost_usd')::numeric) "
        "FROM search_candidate WHERE (record_preview->'light_pull_read'->>'cost_usd')::numeric > 0"
    )).one()
    if row[0]:
        return float(row[1]), f"average of {row[0]} earlier reads"
    return DEFAULT_COST_PER_ORGANISATION, "no earlier read; typical cost of one read"


def estimate(session, targets: list[dict], *, missing_only: bool) -> dict:
    per_org, basis = cost_per_organisation(session)
    organisations = []
    for row in targets:
        record = row.get("record_preview") or {}
        boxes = missing_boxes(record) if missing_only else None
        if boxes == []:
            continue
        organisations.append({"candidate_id": row.get("candidate_id"),
                              "name": record.get("name"), "website": record.get("website"),
                              "boxes": boxes})
    return {"mode": "estimate", "organisations": organisations,
            "per_organisation_usd": round(per_org, 4), "basis": basis,
            "estimated_usd": round(per_org * len(organisations), 2)}


def actor_targets(session, *, origin: str, force: bool, limit: int) -> list[dict]:
    """Existing actors with a Light Pull box that no page was read for."""
    rows = session.execute(text(
        "SELECT a.actor_id::text AS actor_id, a.name, a.website, a.actor_category, "
        "a.category_type, f.topic_id::text AS topic_id, t.name AS topic_name, "
        "array_agg(DISTINCT f.fact_key) AS open_keys "
        "FROM actor a JOIN actor_fact f ON f.actor_id = a.actor_id AND f.layer = 1 "
        "LEFT JOIN topic t ON t.topic_id = f.topic_id "
        "WHERE a.source_origin = :origin AND COALESCE(a.website, '') <> '' "
        + ("" if force else "AND f.collection_state <> 'found' ")
        + "GROUP BY 1, 2, 3, 4, 5, 6, 7 ORDER BY a.name LIMIT :limit"
    ), {"origin": origin, "limit": limit}).mappings().all()
    return [dict(r) for r in rows]


def _reader(config: dict, max_usd: float, *, reader_class=None):
    """The page reader with its client and cost meter; Light Pull unless a reader
    class of another layer is given (``deep_pull_reader.DeepPullReader``)."""
    from agents.collection.light_pull_reader import LightPullReader
    from agents.common.cost import CostMeter
    from agents.common.llm import ClaudeToolClient
    from agents.discovery.search.phase2 import OpenWebEventSource

    pricing = dict(config.get("light_pull_llm_pricing")
                   or config.get("extraction_llm_pricing") or {})
    model = str(config.get("light_pull_model") or config.get("extraction_model"))
    meter = CostMeter(max_usd=max_usd)
    client = ClaudeToolClient(
        model, cost_meter=meter,
        input_usd_per_million=float(pricing.get("input_usd_per_million", 0.0)),
        output_usd_per_million=float(pricing.get("output_usd_per_million", 0.0)),
    )
    if os.environ.get("ANTHROPIC_API_KEY"):
        from anthropic import Anthropic

        # One organisation's call must not hold the run for the SDK's default
        # ten minutes: a stalled call fails after 180 s, is retried once, and
        # is then recorded against that organisation only.
        client._client = Anthropic(timeout=180.0, max_retries=1)
    source = OpenWebEventSource(config)
    reader_class = reader_class or LightPullReader
    return reader_class(client, source.fetch, fallback=_fallback(config, meter)), meter, model


def _fallback(config: dict, meter):
    """Other sources when an organisation's own site refuses: its parent's official
    site (free), then at most ``fallback_web_searches`` paid searches (default 1),
    inside the same per-organisation cost cap."""
    from agents.collection.site_access import BLOCKED_SITES, BlockedSites, Fallback

    section = dict(config.get("actor_updates") or {})
    searches = int(section.get("fallback_web_searches", 1))
    search = None
    if searches > 0 and os.environ.get("ANTHROPIC_API_KEY"):
        from agents.discovery.search.providers import build_search_provider

        provider = build_search_provider(config, cost_meter=meter)
        search = lambda query: provider.search(query, count=5)
    return Fallback(blocked=BlockedSites(BLOCKED_SITES), search=search, max_searches=searches)


def _summary(name: str, read, cost: float) -> dict:
    found = sorted(k for k, v in read.evidence.items() if v["collection_state"] == "found")
    missing = sorted(k for k, v in read.evidence.items() if v["collection_state"] != "found")
    return {"name": name, "pages_read": read.pages, "found": found, "not_stated": missing,
            "rejected_answers": read.rejected, "error": read.error, "cost_usd": round(cost, 4)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--request-id")
    target.add_argument("--search-run", action="append")
    target.add_argument("--actors", action="store_true")
    parser.add_argument("--origin", default="claude_discovered")
    parser.add_argument("--live", action="store_true", help="save; absent means dry-run")
    parser.add_argument("--force", action="store_true", help="re-read already-read ones")
    parser.add_argument("--max-usd", type=float, default=None)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--allow-shared-database", action="store_true")
    parser.add_argument("--missing-only", action="store_true",
                        help="candidates: read only empty boxes; never replace a value")
    parser.add_argument("--estimate", action="store_true",
                        help="list what would be read and its expected cost; no model call")
    args = parser.parse_args(argv)
    if args.actors and (args.missing_only or args.estimate):
        parser.error("--missing-only and --estimate apply to candidates")

    sys.path.insert(0, str(ROOT))
    _guard(args.allow_shared_database)
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)  # API key only; the caller's DATABASE_URL wins
    _guard(args.allow_shared_database)
    from agents.collection.discovery_requests import open_session
    from agents.common.cost import CostLimitExceeded
    from agents.discovery.search.run import load_open_web_config

    config = load_open_web_config(ROOT)
    max_usd = float(args.max_usd if args.max_usd is not None
                    else config.get("light_pull_max_usd_per_run", 0.50))
    if args.estimate:
        with open_session() as session:
            run_ids = (_runs_for_request(session, args.request_id) if args.request_id
                       else list(args.search_run))
            targets = candidate_targets(session, run_ids, force=args.force, limit=args.limit)
            report = estimate(session, targets, missing_only=args.missing_only)
        report["max_usd"] = max_usd
        print(json.dumps(report, indent=2, default=str))
        return 0
    reader, meter, model = _reader(config, max_usd)
    report: dict = {"mode": "live" if args.live else "dry-run", "model": model,
                    "max_usd": max_usd, "organisations": [], "stopped": None}
    session = open_session()
    try:
        if args.actors:
            from agents.enrichment.decisions import ActorFactWrite, append_actor_fact

            targets = actor_targets(session, origin=args.origin, force=args.force,
                                    limit=args.limit)
        else:
            run_ids = (_runs_for_request(session, args.request_id) if args.request_id
                       else list(args.search_run))
            topics = _topic_terms_for_runs(session, run_ids)
            targets = candidate_targets(session, run_ids, force=args.force, limit=args.limit)
        for index, row in enumerate(targets, 1):
            label = row.get("name") or (row.get("record_preview") or {}).get("name")
            print(f"[{index}/{len(targets)}] {label}", file=sys.stderr, flush=True)
            before = meter.spent_usd
            read_at = datetime.now(UTC)
            try:
                if args.actors:
                    read = reader.read(name=row["name"], website=row["website"],
                                       actor_category=row["actor_category"],
                                       category_type=str(row.get("category_type") or ""),
                                       topic_terms=[row.get("topic_name") or ""],
                                       read_at=read_at)
                else:
                    record = row["record_preview"] or {}
                    wanted = missing_boxes(record) if args.missing_only else None
                    if wanted == []:
                        continue
                    read = reader.read(name=str(record.get("name") or ""),
                                       website=str(record["website"]),
                                       actor_category=record.get("actor_category"),
                                       category_type=str(record.get("category_type") or ""),
                                       topic_terms=topics.get(row["run_id"], []),
                                       read_at=read_at, fields=wanted)
            except CostLimitExceeded as exc:
                report["stopped"] = f"budget of ${max_usd:.2f} reached: {exc}"
                break
            except Exception as exc:  # noqa: BLE001 - one organisation must not end the run
                # A timeout or API error is a fact about this call, not about the
                # organisation: nothing is saved for it, and it is read next time.
                name = row.get("name") or (row.get("record_preview") or {}).get("name")
                report["organisations"].append({
                    "name": str(name), "error": f"{type(exc).__name__}: {exc}"[:300],
                    "pages_read": [], "found": [], "not_stated": [], "rejected_answers": {},
                    "cost_usd": round(meter.spent_usd - before, 4)})
                continue
            name = row.get("name") or (row.get("record_preview") or {}).get("name")
            report["organisations"].append(_summary(str(name), read, meter.spent_usd - before))
            if not args.live or not read.pages:
                continue
            if args.actors:
                for key, fact in read.evidence.items():
                    if key not in (row["open_keys"] or []) and not args.force:
                        continue
                    append_actor_fact(session, ActorFactWrite(
                        actor_id=row["actor_id"], topic_id=row["topic_id"],
                        fact_type="light_pull", field_key=key, value=fact["value"], layer=1,
                        collection_state=fact["collection_state"],
                        confidence=fact["confidence"], source_url=fact["source_url"],
                        date_read=read_at, source_origin="newly_found",
                        created_by="agent:light_pull_reader",
                    ), live=True)
            else:
                from agents.discovery.search.store import attach_light_pull

                evidence = read.evidence
                if args.missing_only:
                    evidence = keep_supplied(
                        (row["record_preview"] or {}).get("light_pull_evidence") or {}, evidence)
                attach_light_pull(session, row["candidate_id"], evidence=evidence,
                                  read=read.as_record(model=model, read_at=read_at))
            session.commit()
    finally:
        session.close()
    report["spent_usd"] = round(meter.spent_usd, 4)
    kept = len(report["organisations"])
    report["cost_per_organisation_usd"] = round(meter.spent_usd / kept, 4) if kept else None
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
