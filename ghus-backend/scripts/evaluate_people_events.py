"""Before / after: the rubric band alone vs the band capped by the quality gates.

    python -m scripts.evaluate_people_events [--stored]

1. The labelled set (evals/people_events_gold.jsonl): precision of what is
   accepted, recall of what is useful, what is filtered out, review workload,
   mandatory-field completeness of what is accepted.
2. --stored: every real event and person page already analysed by the agent
   (the cached rubric analyses beside the stored pages): how the decisions
   change, and why. Free: no page is fetched and no model is called.

Reads only; writes nothing.
"""

from __future__ import annotations

import argparse
import collections
import json
from datetime import date
from pathlib import Path

from agents.discovery.page_facts import page_text
from agents.discovery.quality_gates import cap_band, event_gate, linkedin_profile, person_gate
from agents.discovery.search.event_scoring import event_score_band, score_event_rubric
from agents.discovery.search.person_scoring import person_score_band, score_person_rubric

ROOT = Path(__file__).resolve().parents[1]
DECISION = {"auto_high": "accept", "review": "review", "auto_low": "exclude"}


def _rubric(flags: dict) -> dict:
    return {n: {"present": bool(v), "evidence": "stated" if v else None} for n, v in flags.items()}


def _band(entity: str, rubric: dict, config: dict) -> str:
    if entity == "person":
        return person_score_band(score_person_rubric(rubric, config=config).total, config)
    return event_score_band(score_event_rubric(rubric, config=config).total, config)


def _gate(entity, record, facts, url, text, html, rubric, run_date):
    if entity == "person":
        facts = dict(facts or {})
        linked = linkedin_profile(html or "", str(record.get("name") or ""))
        if linked:
            facts["linkedin_url"] = linked
        return person_gate(record, facts=facts, page_url=url, page_text=text, rubric=rubric)
    return event_gate(record, facts=facts, page_url=url, page_text=text, rubric=rubric,
                      run_date=run_date)


def metrics(rows: list[dict]) -> dict:
    """rows: {expected, decision, mandatory_ok}"""
    useful = [r for r in rows if r["expected"] in {"accept", "review"}]
    accepted = [r for r in rows if r["decision"] == "accept"]
    kept = [r for r in rows if r["decision"] in {"accept", "review"}]
    junk = [r for r in rows if r["expected"] == "exclude"]
    return {
        "cases": len(rows),
        "accept_precision": round(sum(r["expected"] == "accept" for r in accepted)
                                  / len(accepted), 2) if accepted else None,
        "useful_recall": round(sum(r["decision"] in {"accept", "review"} for r in useful)
                               / len(useful), 2) if useful else None,
        "junk_filtered": round(sum(r["decision"] == "exclude" for r in junk) / len(junk), 2)
        if junk else None,
        "review_workload": sum(r["decision"] == "review" for r in rows),
        "accepted": len(accepted),
        "accepted_with_all_mandatory": sum(r["mandatory_ok"] for r in accepted),
        "kept_but_should_be_excluded": sum(r["expected"] == "exclude" for r in kept),
        "exact_decision_match": round(sum(r["decision"] == r["expected"] for r in rows)
                                      / len(rows), 2),
    }


def gold(config: dict, run_date: date) -> dict:
    lines = (ROOT / "evals" / "people_events_gold.jsonl").read_text(encoding="utf-8").splitlines()
    cases = [json.loads(line) for line in lines if line.strip()]
    out = {}
    for entity in ("person", "event"):
        before, after = [], []
        for case in (c for c in cases if c["entity_type"] == entity):
            rubric = _rubric(case["rubric"])
            band = _band(entity, rubric, config)
            gate = _gate(entity, case["record"], case.get("facts"), case["page_url"],
                         case["page_text"], case.get("page_html"), rubric, run_date)
            mandatory_ok = not gate.missing_mandatory
            before.append({"expected": case["expected"], "decision": DECISION[band],
                           "mandatory_ok": mandatory_ok})
            after.append({"expected": case["expected"],
                          "decision": DECISION[cap_band(band, gate)],
                          "mandatory_ok": mandatory_ok})
        out[entity] = {"before": metrics(before), "after": metrics(after)}
    return out


def stored(config: dict, run_date: date) -> dict:
    """Real pages the agent already analysed: decisions before and after the gates."""
    raw = ROOT / "agents" / "raw_documents"
    pages = {p.stem: p for p in raw.rglob("*.html")}
    urls = _urls_by_hash()
    out = {}
    for entity, folder in (("event", "event_analysis"), ("person", "person_analysis")):
        transitions = collections.Counter()
        reasons = collections.Counter()
        missing = collections.Counter()
        seen = 0
        for cache in sorted((raw / folder).glob("*.json")):
            content_hash = cache.name.split(".")[0]
            page = pages.get(content_hash)
            if page is None:
                continue
            analysis = json.loads(cache.read_text(encoding="utf-8"))
            rubric, record = analysis.get("rubric") or {}, analysis.get("record") or {}
            html = page.read_text(encoding="utf-8", errors="replace")
            url = urls.get(content_hash) or record.get("website") or record.get("public_profile_url") or ""
            band = _band(entity, rubric, config)
            gate = _gate(entity, record, analysis.get("facts"), url, page_text(html), html,
                         rubric, run_date)
            after = cap_band(band, gate)
            seen += 1
            transitions[f"{DECISION[band]} -> {DECISION[after]}"] += 1
            if after != band:
                reasons[gate.reasons[0][:90]] += 1
            for field in gate.missing_mandatory:
                missing[field] += 1
        out[entity] = {"pages": seen, "transitions": dict(transitions.most_common()),
                       "why_lowered": dict(reasons.most_common(8)),
                       "missing_mandatory": dict(missing.most_common())}
    return out


EVENT_KEYS = ("start_date", "end_date", "city", "country", "sponsoring_orgs", "access_type",
              "event_type", "description")
EVENT_FACT_KEYS = ("organizer", "registration_url", "format", "themes", "event_status")
PERSON_KEYS = ("name", "affiliation", "role", "public_profile_url", "research_area")
PERSON_FACT_KEYS = ("department", "expertise", "relevant_work", "linkedin_url")


def live_sample(config: dict, run_date: date, size: int) -> dict:
    """Re-read ``size`` stored pages per kind with the improved extraction (paid, bounded).

    The same pages the old agent analysed (their cached analyses are the
    'before'), so the comparison is like for like. No page is fetched.
    """
    from agents.common.cost import CostMeter
    from agents.discovery.search.event_scoring import EventRubricExtractor
    from agents.discovery.search.person_scoring import PersonRubricExtractor
    from agents.discovery.search.phase2 import _extraction_client
    from agents.discovery.search.query_generation import load_seeded_sectors
    from agents.discovery.sources.base import FetchedDoc

    raw = ROOT / "agents" / "raw_documents"
    pages = {p.stem: p for p in raw.rglob("*.html")}
    urls = _urls_by_hash()
    sectors = [str(s.get("code") or "").upper() for s in load_seeded_sectors(ROOT)]
    out = {}
    for entity, folder in (("event", "event_analysis"), ("person", "person_analysis")):
        meter = CostMeter(max_usd=0.15 * size + 0.10)
        client = _extraction_client(config, meter)
        extractor = (EventRubricExtractor(client) if entity == "event"
                     else PersonRubricExtractor(client))
        rows = []
        for cache in sorted((raw / folder).glob("*.json")):
            if len(rows) >= size:
                break
            content_hash = cache.name.split(".")[0]
            before = json.loads(cache.read_text(encoding="utf-8"))
            old_record = before.get("record") or {}
            # The ledger's address, else the address the old record read from the page.
            url = urls.get(content_hash) or old_record.get("public_profile_url")                 or old_record.get("website")
            if content_hash not in pages or not url:
                continue
            if DECISION[_band(entity, before.get("rubric") or {}, config)] == "exclude":
                continue                       # compare on pages worth keeping
            html = pages[content_hash].read_text(encoding="utf-8", errors="replace")
            doc = FetchedDoc.from_content(url=str(url), content=html,
                                          content_type="text/html")
            spent = meter.spent_usd
            try:
                after = (extractor.extract(doc, sector_codes=sectors, hub_names=[],
                                           run_date=run_date) if entity == "event"
                         else extractor.extract(doc, sector_codes=sectors, hub_names=[],
                                                held_actor_names=[]))
            except Exception as exc:  # noqa: BLE001 - reported, not fatal
                rows.append({"url": doc.url, "error": f"{type(exc).__name__}: {exc}"[:200]})
                continue
            keys, fact_keys = ((EVENT_KEYS, EVENT_FACT_KEYS) if entity == "event"
                               else (PERSON_KEYS, PERSON_FACT_KEYS))
            filled_before = sum(old_record.get(k) not in (None, "", []) for k in keys)
            filled_after = sum(after.record.get(k) not in (None, "", []) for k in keys)
            facts_after = sum(after.facts.get(k) not in (None, "", []) for k in fact_keys)
            gate = _gate(entity, after.record, after.facts, doc.url, page_text(html), html,
                         after.rubric, run_date)
            rows.append({
                "url": doc.url,
                "record_fields_before": f"{filled_before}/{len(keys)}",
                "record_fields_after": f"{filled_after}/{len(keys)}",
                "new_facts": f"{facts_after}/{len(fact_keys)}",
                "quoted_facts": len((after.facts.get("evidence") or {})),
                "dropped_unquoted": after.facts.get("dropped") or [],
                "decision_before": DECISION[_band(entity, before.get("rubric") or {}, config)],
                "decision_after": DECISION[cap_band(_band(entity, after.rubric, config), gate)],
                "completeness": gate.completeness,
                "why": gate.reasons[0] if gate.reasons else "",
                "cost_usd": round(meter.spent_usd - spent, 4),
            })
        out[entity] = {"pages": rows, "total_usd": round(meter.spent_usd, 4),
                       "model": str(config.get("extraction_model"))}
    return out


def _urls_by_hash() -> dict[str, str]:
    """Page addresses from the run ledger, when a database is configured."""
    try:
        from sqlalchemy import text

        from src.db.session import SessionLocal

        with SessionLocal() as session:
            return {r[0]: r[1] for r in session.execute(text(
                "SELECT content_hash, url FROM raw_document WHERE content_hash IS NOT NULL"))}
    except Exception:  # noqa: BLE001 - addresses are a refinement, not required
        return {}


def run_metrics(run_ids: list[str]) -> dict:
    """What recorded runs did, per run and per mode (automatic / on request). Free: a read.

    Useful record = sent to Review with every mandatory field backed
    (quality.completeness complete or incomplete, never insufficient).
    """
    from sqlalchemy import text

    from src.db.session import SessionLocal

    out: dict = {"runs": [], "by_mode": {}}
    with SessionLocal() as session:
        for run_id in run_ids:
            run = session.execute(text(
                "SELECT entity_type, mode, status, cost_usd, stats FROM scrape_run "
                "WHERE run_id = CAST(:id AS uuid)"), {"id": run_id}).mappings().first()
            if run is None:
                continue
            rows = session.execute(text(
                "SELECT score_band, triage_verdict, triage_reason, "
                "record_preview->'quality'->>'completeness' AS completeness, "
                "record_preview->'quality'->>'outcome' AS outcome, "
                "jsonb_array_length(COALESCE(record_preview->'quality'->'missing_priority', "
                "'[]'::jsonb)) AS missing_priority "
                "FROM search_candidate WHERE run_id = CAST(:id AS uuid)"),
                {"id": run_id}).mappings().all()
            stats = dict(run["stats"] or {})
            kept = [r for r in rows if r["score_band"] in ("auto_high", "review")]
            useful = [r for r in kept if r["completeness"] in ("complete", "incomplete")]
            cost = float(run["cost_usd"] or 0.0)
            reasons: dict[str, int] = {}
            for r in rows:
                if r["score_band"] not in ("auto_high", "review"):
                    why = str(r["triage_reason"] or r["triage_verdict"] or "not recorded")
                    key = ("outside the request" if "outside the request" in why
                           else "already on the map or in Review" if "already" in why
                           else "needs more research, not resolved" if "Needs more research" in why
                           else "quality gate" if "quality gate" in why
                           else str(r["triage_verdict"] or "other"))
                    reasons[key] = reasons.get(key, 0) + 1
            row = {
                "run_id": run_id, "entity": run["entity_type"],
                "mode": stats.get("run_trigger") or (
                    "on_request" if stats.get("discovery_request_id") else "automatic"),
                "status": run["status"], "searches": stats.get("searches_executed"),
                "pages_read": stats.get("pages_fetched"), "candidates": len(rows),
                "sent_to_review": len(kept), "complete": sum(r["completeness"] == "complete"
                                                             for r in kept),
                "useful": len(useful), "excluded": len(rows) - len(kept),
                "exclusion_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
                "followups": {"tried": stats.get("followups_attempted", 0),
                              "resolved": stats.get("followups_resolved", 0)},
                "duplicates_skipped": int(stats.get("held_event_skips", 0) or 0)
                + int(stats.get("pending_review_skips", 0) or 0),
                "cost_usd": round(cost, 4),
                "cost_by_stage": {k.removeprefix("cost_stage_").removesuffix("_usd"): v
                                  for k, v in stats.items()
                                  if k.startswith("cost_stage_") and v},
                "cost_per_useful_record": round(cost / len(useful), 4) if useful else None,
            }
            out["runs"].append(row)
            mode = out["by_mode"].setdefault(f"{row['entity']}:{row['mode']}", {
                "runs": 0, "sent_to_review": 0, "useful": 0, "cost_usd": 0.0})
            mode["runs"] += 1
            mode["sent_to_review"] += row["sent_to_review"]
            mode["useful"] += row["useful"]
            mode["cost_usd"] = round(mode["cost_usd"] + cost, 4)
    for mode in out["by_mode"].values():
        mode["cost_per_useful_record"] = (round(mode["cost_usd"] / mode["useful"], 4)
                                          if mode["useful"] else None)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stored", action="store_true")
    parser.add_argument("--live-sample", type=int, default=0,
                        help="re-read this many stored pages per kind with the improved "
                             "extraction (paid; default 0: nothing is paid for)")
    parser.add_argument("--run-date", default="2026-10-22")
    parser.add_argument("--runs", nargs="*", default=[],
                        help="recorded search run ids to measure (free: a read)")
    args = parser.parse_args(argv)
    from agents.discovery.search.run import load_open_web_config

    config = load_open_web_config()
    run_date = date.fromisoformat(args.run_date)
    report = {"labelled_set": gold(config, run_date)}
    if args.stored:
        report["stored_pages"] = stored(config, run_date)
    if args.live_sample > 0:
        report["live_sample"] = live_sample(config, run_date, min(args.live_sample, 10))
    if args.runs:
        report["runs"] = run_metrics(args.runs)
    print(json.dumps(report, indent=1, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
