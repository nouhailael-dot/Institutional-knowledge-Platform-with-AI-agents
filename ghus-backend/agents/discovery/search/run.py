"""Open-web discovery CLI: search, gate, page analysis, staging, and routing."""

from __future__ import annotations

import argparse
import inspect
import logging
import re
import time
from dataclasses import replace
from datetime import date
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import text

from agents.common.config import load_sources_config
from agents.common.cost import CostLimitExceeded, CostMeter
from agents.common.llm import ClaudeToolClient, llm_usage_delta, llm_usage_snapshot
from agents.common.resolve_route import load_actor_resolver_class
from agents.common.run_log import InMemoryRunLog, SQLRunLog, write_audit_csv
from agents.discovery.search.actor_scoring import actor_rubric_weights, actor_score_thresholds
from agents.discovery.search.event_scoring import event_rubric_weights, event_score_thresholds
from agents.discovery.search.models import CandidateRecord, SearchResult, TriageDecision
from agents.discovery.search.people_targets import profile_page_kind, search_linkedin
from agents.discovery.search.person_scoring import (
    person_rubric_weights,
    person_score_thresholds,
)
from agents.discovery.search.phase2 import (
    fetch_score_stage_actors,
    fetch_score_stage_events,
    fetch_score_stage_people,
)
from agents.discovery.search.providers import SearchProvider, build_search_provider
from agents.discovery.search.query_generation import (
    QueryBundle,
    QueryGenerator,
    load_active_sectors,
    load_actor_query_hubs,
    load_event_reference_examples,
    load_seeded_sectors,
)
from agents.discovery.search.report import (
    write_candidate_report,
    write_candidate_spreadsheet,
    write_rejection_report,
)
from agents.discovery.search.store import InMemorySearchCandidateStore, SQLSearchCandidateStore
from agents.discovery.search.triage import (
    TRIAGE_INCOMPLETE_REASON_PREFIX,
    SearchTriageClient,
    actor_document_rejection,
    blocklist_domains_for_entity,
    deterministic_rejection,
    is_triage_incomplete,
    known_source_domains,
    load_actor_hub_sector_counts,
    load_existing_actor_domains,
    normalized_domain,
    person_scope_rejection,
    registrable_domain,
)
from agents.discovery.search.us_scope import result_outside_us

logger = logging.getLogger(__name__)

API_CREDIT_EXHAUSTED_STATUS_REASON = "API credit exhausted"


class ApiCreditExhaustedError(RuntimeError):
    """Raised when the LLM provider rejects a request for insufficient credit."""


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_open_web_config(root: Path | None = None) -> dict[str, object]:
    config = load_sources_config(root or project_root())
    open_web = dict(config.get("open_web_discovery", {}))
    if not open_web:
        raise RuntimeError("agents/config/sources.yaml must define open_web_discovery")
    return open_web



def _attach_cost_per_relevant_actor(stats: dict[str, object]) -> None:
    """What one RELEVANT actor cost, not only what the run cost.

    Relevant = kept: auto-verified plus sent to Review. Accepted alone is also
    given, since that is the number that needs no person. None when nothing
    was kept (the run's whole spend bought no relevant actor).
    """
    if "actor_scored" not in stats:
        return
    cost = float(stats.get("cost_usd") or 0.0)
    accepted = int(stats.get("actor_band_auto_high", 0) or 0)
    kept = accepted + int(stats.get("actor_band_review", 0) or 0)
    stats["actor_relevant_kept"] = kept
    stats["cost_per_relevant_actor_usd"] = round(cost / kept, 4) if kept else None
    stats["cost_per_accepted_actor_usd"] = round(cost / accepted, 4) if accepted else None

def run_search_triage(
    args,
    *,
    session=None,
    root: Path | None = None,
    run_log=None,
    store=None,
    search_provider: SearchProvider | None = None,
    llm_client=None,
    query_generator=None,
    triage_client=None,
    cost_meter: CostMeter | None = None,
    search_client=None,
    fetch_source=None,
    extractor=None,
    raw_store=None,
    stage_store=None,
    domain_store=None,
    event_candidates=None,
    person_candidates=None,
    actor_resolver=None,
    run_date: date | None = None,
) -> dict[str, object]:
    root = root or project_root()
    full_config = load_sources_config(root)
    config = dict(full_config.get("open_web_discovery", {}))
    if not config:
        raise RuntimeError("agents/config/sources.yaml must define open_web_discovery")

    entity_type = str(getattr(args, "entity", "") or "").strip()
    if entity_type not in {"event", "actor", "person"}:
        raise ValueError("--entity must be one of event, actor, person")
    discovery_request = getattr(args, "discovery_request", None)
    if discovery_request is not None and getattr(discovery_request, "entity", "actor") != entity_type:
        raise ValueError(
            f"this discovery request finds {getattr(discovery_request, 'entity', 'actor')}s, "
            f"not {entity_type}s")
    live = bool(getattr(args, "live", False))
    offline = bool(getattr(args, "offline", False))
    person_create_preview = bool(getattr(args, "preview_person_create", False))
    people_enabled_for_run = bool(getattr(args, "enable_people_for_run", False))
    if people_enabled_for_run and live:
        raise RuntimeError("--enable-people-for-run cannot be combined with --live")
    if people_enabled_for_run:
        config["people_enabled"] = True
    if entity_type == "person" and not bool(config.get("people_enabled", False)):
        raise RuntimeError(
            "open-web people discovery is disabled pending TARGETING_POLICY.md section 6 approval"
        )
    if person_create_preview and live:
        raise RuntimeError("--preview-person-create cannot be combined with --live")
    owned_session = False
    if session is None and not offline:
        from src.db.session import SessionLocal

        session = SessionLocal()
        owned_session = True

    # A requested run has its own, stricter ceiling (request_max_usd_per_run);
    # so does the automatic event run (event_max_usd_per_run, 2026-10-23: every
    # recorded live event run cost under $2.40). Actors and people keep theirs.
    if getattr(args, "discovery_request", None) is not None:
        run_ceiling = float(config.get("request_max_usd_per_run",
                                       config.get("max_usd_per_run", 5.0)))
    elif entity_type == "event":
        run_ceiling = float(config.get("event_max_usd_per_run",
                                       config.get("max_usd_per_run", 5.0)))
    else:
        run_ceiling = float(config.get("max_usd_per_run", 5.0))
    cost_meter = cost_meter or CostMeter(max_usd=run_ceiling)
    llm_client = llm_client or _build_llm_client(config, cost_meter)
    run_log = run_log or (InMemoryRunLog() if offline else SQLRunLog(session))
    store = store or (
        InMemorySearchCandidateStore() if offline else SQLSearchCandidateStore(session)
    )
    if offline and search_provider is None:
        raise RuntimeError("--offline open-web search requires an injected search_provider")
    built_provider = search_provider is None
    search_provider = search_provider or build_search_provider(
        config, cost_meter=cost_meter, client=search_client
    )
    query_generator = query_generator or QueryGenerator(llm_client, config)
    triage_client = triage_client or SearchTriageClient(llm_client, config)
    report_path = _report_path(root, getattr(args, "report_out", None))
    rejection_report_path = _rejection_report_path(
        root,
        getattr(args, "rejection_report_out", None),
        report_path=report_path,
    )
    audit_path = _audit_path(root, getattr(args, "audit_out", None))
    spreadsheet_path = _spreadsheet_path(
        root,
        getattr(args, "spreadsheet_out", None),
        report_path=report_path,
    )

    run_id = run_log.start_run(
        source_name="open_web_search",
        entity_type=entity_type,
        live=live,
        config=config,
    )
    _report_progress(cost_meter, run_log, run_id)
    stats = _empty_stats()
    # Real searches only: a test's stub client must never fill the shared cache.
    if (built_provider and search_client is None and not offline
            and entity_type in {"event", "person"}):
        # Repeated searches within a few days are answered from disk, not paid
        # for again (agents/discovery/search/search_cache.py). Actors unchanged.
        from agents.common.raw_storage import RawContentStore
        from agents.discovery.search.search_cache import CachedSearchProvider

        search_provider = CachedSearchProvider(
            search_provider,
            RawContentStore.from_config(root, config).base_dir / "search_cache",
            ttl_hours=float(config.get("search_cache_ttl_hours", 72)),
            stats=stats,
        )
    # Automatic (the weekly job, a command line) or on request (a Discovery-page
    # request): two run types, recorded on every run so Review can tell them apart.
    stats["run_trigger"] = "on_request" if discovery_request is not None else "automatic"
    candidate_rows: list[CandidateRecord] = []
    audit_rows: list[dict[str, object]] = []
    generated_queries: dict[str, list[str]] = {entity_type: []}
    run_lock = None

    try:
        if live and session is not None and entity_type in _LIVE_RUN_LOCKS:
            # Two live event (or people) runs at once - the weekly job and a
            # request, say - would each stage the same find. One at a time.
            run_lock = _LIVE_RUN_LOCKS[entity_type]
            if not session.execute(text("SELECT pg_try_advisory_lock(:k)"),
                                   {"k": run_lock}).scalar():
                run_lock = None
                raise RuntimeError(
                    f"another live {entity_type} discovery run is in progress; "
                    "this one was not started so the two cannot stage the same records")
        raw_lookup = InMemorySearchCandidateStore(
            seen_raw_urls=store.load_seen_raw_urls()
        )
        generate_kwargs = {"session": session, "project_root": root}
        if discovery_request is not None:
            # A requested run searches only what was asked for (see
            # agents/discovery/search/discovery_request.py).
            generate_kwargs["request"] = discovery_request
            stats["discovery_request_id"] = discovery_request.subscription_id
            stats["discovery_request_title"] = discovery_request.title
            if entity_type != "actor":
                stats["discovery_request_scope"] = discovery_request.describe()
        bundle: QueryBundle = query_generator.generate(entity_type, **generate_kwargs)
        cost_meter.enforce()
        generated_queries[entity_type] = bundle.queries
        stats["queries_generated"] = len(bundle.queries)
        stats["deterministic_queries"] = len(bundle.deterministic_queries)
        stats["llm_queries"] = len(bundle.llm_queries)
        stats["reference_count"] = bundle.reference_count
        if entity_type == "actor":
            _attach_actor_query_metadata(stats, bundle.metadata or {})
            auto_low, auto_high = actor_score_thresholds(config)
            stats["actor_score_auto_low"] = auto_low
            stats["actor_score_auto_high"] = auto_high
            for name, weight in actor_rubric_weights(config).items():
                stats[f"actor_rubric_weight_{name}"] = weight
        elif entity_type == "event":
            auto_low, auto_high = event_score_thresholds(config)
            stats["event_score_auto_low"] = auto_low
            stats["event_score_auto_high"] = auto_high
            for name, weight in event_rubric_weights(config).items():
                stats[f"event_rubric_weight_{name}"] = weight
        elif entity_type == "person":
            auto_low, auto_high = person_score_thresholds(config)
            stats["person_score_auto_low"] = auto_low
            stats["person_score_auto_high"] = auto_high
            for name, weight in person_rubric_weights(config).items():
                stats[f"person_rubric_weight_{name}"] = weight
            stats["person_query_distinct_hubs"] = int(
                dict(bundle.metadata or {}).get("distinct_hubs_covered") or 0
            )
            stats["person_query_sector_codes"] = ", ".join(
                str(value)
                for value in dict(bundle.metadata or {}).get("sector_codes_covered", []) or []
            )

        attention_reasons: list[str] = []
        queries = bundle.queries
        max_searches = int(
            config.get("actor_max_searches", config.get("max_searches", 40))
            if entity_type == "actor"
            else config.get("max_searches", 40)
        )
        if len(queries) > max_searches:
            attention_reasons.append(
                f"max_searches cap hit: generated {len(queries)}, executed {max_searches}"
            )
            queries = queries[:max_searches]

        if entity_type == "actor":
            use_case_queries = {
                str(query)
                for query in (bundle.metadata or {}).get("use_case_queries", []) or []
            }
            stats["actor_use_case_queries_generated"] = len(use_case_queries)
            stats["actor_use_case_queries_executed"] = sum(
                1 for query in queries if query in use_case_queries
            )

        search_results: list[SearchResult] = []
        stage_start = cost_meter.spent_usd
        # People requests search only their target institutions' own sites
        # (agents/discovery/search/people_targets.py).
        query_domains = dict((bundle.metadata or {}).get("query_domains") or {})
        for query in queries:
            stats["searches_executed"] += 1
            count = int(config.get("results_per_query", 10))
            results = (search_provider.search(query, count=count,
                                              allowed_domains=query_domains[query])
                       if query_domains.get(query)
                       else search_provider.search(query, count=count))
            cost_meter.enforce()
            search_results.extend(results)
        stats["search_results"] = len(search_results)
        stats["cost_stage_search_usd"] = round(cost_meter.spent_usd - stage_start, 6)
        deduplicated_results = _deduplicate_search_results(search_results)
        stats["search_results_unique"] = len(deduplicated_results)
        stats["search_results_deduplicated"] = len(search_results) - len(deduplicated_results)

        directories: list[SearchResult] = []
        pending_results = _deterministic_triage(
            run_id=run_id,
            entity_type=entity_type,
            results=deduplicated_results,
            raw_lookup=raw_lookup,
            config=config,
            full_config=full_config,
            session=session,
            candidate_rows=candidate_rows,
            stats=stats,
            directories=directories,
        )
        if entity_type == "person" and directories:
            pending_results.extend(_people_from_directories(
                directories, pending_results, config=config, root=root,
                request=discovery_request, fetch_source=fetch_source, stats=stats))

        triaged_results, capped_count = _cap_triage_candidates(
            run_id=run_id,
            entity_type=entity_type,
            pending_results=pending_results,
            config=config,
            candidate_rows=candidate_rows,
        )
        if capped_count:
            attention_reasons.append(
                "max_candidates_triaged cap hit: "
                f"{len(_unique_by_url(pending_results))} survivors, "
                f"{len(triaged_results)} sent to LLM"
            )
            stats["triage_cap_rejected"] = capped_count

        triage_usage_client = getattr(triage_client, "llm_client", llm_client)
        triage_usage_before = llm_usage_snapshot(triage_usage_client)
        stage_start = cost_meter.spent_usd
        try:
            decisions = _llm_triage(
                entity_type=entity_type,
                results=triaged_results,
                triage_client=triage_client,
                config=config,
                session=session,
                root=root,
                cost_meter=cost_meter,
                actor_query_metadata=bundle.metadata or {},
            )
        finally:
            _attach_llm_cache_stats(
                stats,
                prefix="triage",
                before=triage_usage_before,
                client=triage_usage_client,
            )
            stats["cost_stage_triage_usd"] = round(cost_meter.spent_usd - stage_start, 6)
        _append_llm_triaged_rows(
            run_id=run_id,
            entity_type=entity_type,
            pending_results=pending_results,
            decisions=decisions,
            config=config,
            candidate_rows=candidate_rows,
        )
        if entity_type == "actor":
            stats["actor_domain_duplicates_collapsed"] = (
                _collapse_accepted_actor_domains(candidate_rows)
            )

        if entity_type == "actor" and bool(config.get("fetch_enabled", False)):
            hubs = load_actor_query_hubs(session) if session is not None else []
            hub_names = [str(hub.get("name") or "").strip() for hub in hubs]
            if not hub_names:
                hub_names = [
                    str(hub.get("name") or "").strip()
                    for hub in (bundle.metadata or {}).get("selected_hubs", []) or []
                    if isinstance(hub, dict) and str(hub.get("name") or "").strip()
                ]
            actor_types = [
                str(value).strip()
                for value in (bundle.metadata or {}).get("actor_type_enum", []) or []
                if str(value).strip()
            ]
            if not actor_types:
                actor_types = [
                    str(value).strip()
                    for value in config.get("actor_type_enum", []) or []
                    if str(value).strip()
                ]
            # From the database: sectors added in Review are used from the next run.
            sectors = load_active_sectors(session, root)
            candidate_hubs = _candidate_hubs_from_query_plan(
                triaged_results,
                bundle.metadata or {},
            )
            actor_context = {
                "coverage_counts": load_actor_hub_sector_counts(session),
                "candidate_hubs": candidate_hubs,
                "candidate_topics": _candidate_topics(session, candidate_hubs),
            }
            if discovery_request is not None:
                actor_context["discovery_scope"] = discovery_request.quality_scope()
                actor_context["candidate_topics"] = _request_topics(
                    session, discovery_request, triaged_results
                )
                actor_context["max_new_actors"] = discovery_request.max_new_actors
                # The request's topic, for candidates that were never search
                # results (official-site re-reads and leads).
                actor_context["request_topic"] = _request_topics(
                    session, discovery_request, [SearchResult(
                        url="request:", title="", snippet="", provider="", query="")]
                ).get("request:")
            actor_context.update(_lead_context(
                config, cost_meter, session=session, sectors=sectors,
                request=discovery_request,
            ))
            if actor_resolver is None and session is not None:
                actor_resolver = load_actor_resolver_class()(session, project_root=root)
            actor_outcome = fetch_score_stage_actors(
                run_id=run_id,
                candidates=candidate_rows,
                config=config,
                root=root,
                session=session,
                live=live,
                run_log=run_log,
                cost_meter=cost_meter,
                stats=stats,
                audit_rows=audit_rows,
                actor_types=actor_types,
                sector_codes=[str(sector.get("code") or "").upper() for sector in sectors],
                hub_names=hub_names,
                actor_context=actor_context,
                source=fetch_source,
                rubric_extractor=extractor,
                raw_store=raw_store,
                stage_store=stage_store,
                domain_store=domain_store,
                actor_resolver=actor_resolver,
            )
            candidate_rows = actor_outcome.candidates
            attention_reasons.extend(actor_outcome.attention_reasons)
        elif entity_type == "event" and bool(config.get("fetch_enabled", False)):
            hubs = load_actor_query_hubs(session) if session is not None else []
            event_outcome = fetch_score_stage_events(
                run_id=run_id,
                candidates=candidate_rows,
                config={
                    **config,
                    "event_qualification": dict(full_config.get("event_qualification", {})),
                },
                root=root,
                session=session,
                live=live,
                run_log=run_log,
                cost_meter=cost_meter,
                stats=stats,
                audit_rows=audit_rows,
                sector_codes=[
                    str(sector.get("code") or "").upper()
                    for sector in load_seeded_sectors(root)
                ],
                hub_names=[str(hub.get("name") or "").strip() for hub in hubs],
                source=fetch_source,
                rubric_extractor=extractor,
                raw_store=raw_store,
                stage_store=stage_store,
                domain_store=domain_store,
                event_candidates=event_candidates,
                actor_resolver=actor_resolver,
                run_date=run_date,
                request=discovery_request,
            )
            candidate_rows = event_outcome.candidates
            attention_reasons.extend(event_outcome.attention_reasons)
        elif entity_type == "person" and bool(config.get("fetch_enabled", False)):
            hubs = load_actor_query_hubs(session) if session is not None else []
            person_outcome = fetch_score_stage_people(
                run_id=run_id,
                candidates=candidate_rows,
                config=config,
                root=root,
                session=session,
                live=live,
                run_log=run_log,
                cost_meter=cost_meter,
                stats=stats,
                audit_rows=audit_rows,
                sector_codes=[
                    str(sector.get("code") or "").upper()
                    for sector in load_seeded_sectors(root)
                ],
                hub_names=[str(hub.get("name") or "").strip() for hub in hubs],
                source=fetch_source,
                rubric_extractor=extractor,
                raw_store=raw_store,
                stage_store=stage_store,
                domain_store=domain_store,
                person_candidates=person_candidates,
                actor_resolver=actor_resolver,
                request=discovery_request,
                # A real search only: the bio-or-LinkedIn rule's last resort.
                linkedin_search=(partial(search_linkedin, search_provider.search)
                                 if built_provider and not offline else None),
                own_sites=stats.pop("_person_own_sites", None),
            )
            candidate_rows = person_outcome.candidates
            attention_reasons.extend(person_outcome.attention_reasons)

        stats["accepted"] = sum(1 for row in candidate_rows if row.triage_verdict == "accepted")
        stats["rejected"] = sum(1 for row in candidate_rows if row.triage_verdict == "rejected")
        stats["triage_incomplete"] = sum(
            1 for row in candidate_rows if row.triage_verdict == "triage_incomplete"
        )
        if stats["triage_incomplete"]:
            attention_reasons.append(
                f"triage_incomplete: {stats['triage_incomplete']} candidate(s) "
                "were not judged after retry"
            )
        stats["cost_usd"] = cost_meter.spent_usd
        stats["cost"] = cost_meter.snapshot()
        _attach_cost_per_relevant_actor(stats)
        status = "attention" if attention_reasons else "succeeded"
        status_reason = "; ".join(attention_reasons)

        # Reports are written before any database write. Triage results cannot be
        # recovered if a DB failure discards them; the rows can be reconstructed
        # from the report. A paid run was lost this way in September 2026.
        write_audit_csv(audit_path, audit_rows)
        write_candidate_report(
            report_path,
            run_id=run_id,
            status=status,
            status_reason=status_reason,
            stats=stats,
            queries=generated_queries,
            candidates=candidate_rows,
        )
        write_candidate_spreadsheet(spreadsheet_path, candidate_rows)
        write_rejection_report(
            rejection_report_path,
            run_id=run_id,
            status=status,
            status_reason=status_reason,
            candidates=candidate_rows,
        )

        try:
            stats["candidates_written"] = store.write_candidates(candidate_rows)
        except Exception as exc:  # noqa: BLE001 - reports are already safe on disk
            logger.error(
                "candidate persistence failed after reports were written: %s", exc
            )
            _rollback_session(session)
            stats["candidates_written"] = 0
            status = "attention"
            status_reason = "; ".join(
                filter(None, [status_reason, f"candidate persistence failed: {exc}"])
            )

        run_log.close_run(
            run_id,
            status=status,
            stats=stats,
            cost_usd=cost_meter.spent_usd,
            status_reason=status_reason,
        )
        return {
            "run_id": run_id,
            "status": status,
            "status_reason": status_reason,
            "stats": stats,
            "queries": generated_queries,
            "candidates": candidate_rows,
            "report_path": str(report_path),
            "rejection_report_path": str(rejection_report_path),
            "audit_path": str(audit_path),
            "spreadsheet_path": str(spreadsheet_path),
            "exit_code": 1 if status == "attention" else 0,
        }
    except CostLimitExceeded as exc:
        stats["cost_usd"] = cost_meter.spent_usd
        stats["cost"] = cost_meter.snapshot()
        _attach_cost_per_relevant_actor(stats)
        status_reason = f"max_usd_per_run cap hit: {exc}"
        write_audit_csv(audit_path, audit_rows)
        write_candidate_report(
            report_path,
            run_id=run_id,
            status="attention",
            status_reason=status_reason,
            stats=stats,
            queries=generated_queries,
            candidates=candidate_rows,
        )
        write_candidate_spreadsheet(spreadsheet_path, candidate_rows)
        write_rejection_report(
            rejection_report_path,
            run_id=run_id,
            status="attention",
            status_reason=status_reason,
            candidates=candidate_rows,
        )
        try:
            stats["candidates_written"] = store.write_candidates(candidate_rows)
        except Exception as write_exc:  # noqa: BLE001 - reports already on disk
            logger.error("candidate persistence failed: %s", write_exc)
            _rollback_session(session)
            stats["candidates_written"] = 0
        run_log.close_run(
            run_id,
            status="attention",
            stats=stats,
            cost_usd=cost_meter.spent_usd,
            status_reason=status_reason,
        )
        return {
            "run_id": run_id,
            "status": "attention",
            "status_reason": status_reason,
            "stats": stats,
            "queries": generated_queries,
            "candidates": candidate_rows,
            "report_path": str(report_path),
            "rejection_report_path": str(rejection_report_path),
            "audit_path": str(audit_path),
            "spreadsheet_path": str(spreadsheet_path),
            "exit_code": 1,
        }
    except Exception as exc:
        status_reason = _failure_status_reason(exc)
        _rollback_session(session)
        stats["failures"] += 1
        stats["cost_usd"] = cost_meter.spent_usd
        stats["cost"] = cost_meter.snapshot()
        _attach_cost_per_relevant_actor(stats)
        write_audit_csv(audit_path, audit_rows)
        write_candidate_report(
            report_path,
            run_id=run_id,
            status="failed",
            status_reason=status_reason,
            stats=stats,
            queries=generated_queries,
            candidates=candidate_rows,
        )
        write_candidate_spreadsheet(spreadsheet_path, candidate_rows)
        write_rejection_report(
            rejection_report_path,
            run_id=run_id,
            status="failed",
            status_reason=status_reason,
            candidates=candidate_rows,
        )
        try:
            stats["candidates_written"] = store.write_candidates(candidate_rows)
        except Exception as write_exc:  # noqa: BLE001 - reports already on disk
            logger.error("candidate persistence failed: %s", write_exc)
            _rollback_session(session)
            stats["candidates_written"] = 0
        try:
            run_log.fail_run(
                run_id,
                error=str(exc),
                stats=stats,
                cost_usd=cost_meter.spent_usd,
                status_reason=status_reason,
            )
        except Exception as log_exc:  # noqa: BLE001 - never mask the original error
            logger.error("fail_run could not be recorded: %s", log_exc)
        raise
    finally:
        if run_lock is not None:
            try:
                session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": run_lock})
            except Exception:  # noqa: BLE001 - an aborted transaction; clear it, then unlock
                _rollback_session(session)
                session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": run_lock})
        if owned_session and session is not None:
            session.close()


# One live run per entity at a time (agents/collection/subscription_runner.py
# holds 550_001 for the request runner itself).
_LIVE_RUN_LOCKS = {"event": 580_001, "person": 580_002}


PROGRESS_EVERY_SECONDS = 10.0


def _report_progress(cost_meter: CostMeter, run_log, run_id: str) -> None:
    """Let the Discovery page show what a running run has spent, every few seconds."""
    record = getattr(run_log, "record_progress", None)
    if record is None or cost_meter.on_change is not None:
        return
    last = [0.0]

    def note(spent: float) -> None:
        now = time.monotonic()
        if now - last[0] >= PROGRESS_EVERY_SECONDS:
            last[0] = now
            record(run_id, spent_usd=spent)

    cost_meter.on_change = note


def _build_llm_client(config: dict[str, object], cost_meter: CostMeter) -> ClaudeToolClient:
    pricing = dict(config.get("triage_llm_pricing") or config.get("llm_pricing", {}))
    return ClaudeToolClient(
        str(config.get("triage_model") or config.get("claude_model", "claude-haiku-4-5")),
        cost_meter=cost_meter,
        input_usd_per_million=float(pricing.get("input_usd_per_million", 0.0)),
        output_usd_per_million=float(pricing.get("output_usd_per_million", 0.0)),
    )


def _failure_status_reason(exc: Exception) -> str:
    if isinstance(exc, ApiCreditExhaustedError) or _is_api_credit_exhausted(exc):
        return API_CREDIT_EXHAUSTED_STATUS_REASON
    return str(exc)


def _is_api_credit_exhausted(exc: Exception) -> bool:
    details = [str(exc), repr(exc)]
    for attribute in ("body", "message", "response"):
        value = getattr(exc, attribute, None)
        if value is not None:
            details.append(repr(value))
    error_text = " ".join(details).casefold()
    return "invalid_request_error" in error_text and "credit" in error_text


def _rollback_session(session) -> None:
    rollback = getattr(session, "rollback", None)
    if not callable(rollback):
        return
    try:
        rollback()
    except Exception:  # Preserve the original run failure.
        logger.exception("Could not roll back the session before recording run failure")


def _people_from_directories(directories, pending, *, config, root, request, fetch_source,
                             stats) -> list[SearchResult]:
    """Profile pages of the people a directory lists on the topic - no model call.

    At most ``person_directory_pages`` directories (default 3) are opened, and
    at most ``person_leads_per_directory`` people (default 6) taken from each.
    """
    from agents.discovery.search.people_targets import directory_leads
    from agents.discovery.search.phase2 import OpenWebEventSource

    source = fetch_source or OpenWebEventSource(config)
    themes: list[str] = []
    if request is not None:
        themes = list(request.themes(load_seeded_sectors(root)))
    known = {r.url for r in pending}
    leads: list[SearchResult] = []
    own_sites = stats.setdefault("_person_own_sites", {})
    for directory in directories[: int(config.get("person_directory_pages", 3))]:
        try:
            doc = source.fetch(directory.url)
        except Exception as exc:  # noqa: BLE001 - one directory never stops the run
            logger.info("people directory %s not read: %s", directory.url, exc)
            continue
        stats["person_directories_read"] = int(stats.get("person_directories_read", 0) or 0) + 1
        for lead in directory_leads(doc.content, doc.url, themes,
                                    limit=int(config.get("person_leads_per_directory", 6))):
            if lead["url"] in known:
                continue
            known.add(lead["url"])
            leads.append(SearchResult(url=lead["url"], title=lead["name"],
                                      snippet=lead["context"], provider="directory",
                                      query=f"listed on {directory.url}"))
            if lead.get("own_site"):
                own_sites[lead["url"]] = lead["own_site"]
    stats["person_directory_leads"] = len(leads)
    return leads


def _deterministic_triage(
    *,
    run_id: str,
    entity_type: str,
    results: list[SearchResult],
    raw_lookup,
    config: dict[str, object],
    full_config: dict[str, object],
    session,
    candidate_rows: list[CandidateRecord],
    stats: dict[str, object],
    directories: list[SearchResult] | None = None,
) -> list[SearchResult]:
    pending: list[SearchResult] = []
    configured_domains = known_source_domains(full_config)
    blocklist_domains = blocklist_domains_for_entity(entity_type, config)
    existing_actor_domains = (
        load_existing_actor_domains(session)
        if entity_type in {"actor", "person"}
        else []
    )
    if entity_type == "actor":
        stats["actor_existing_domain_blocklist_count"] = len(existing_actor_domains)
    for result in results:
        domain = normalized_domain(result.url)
        rejected = deterministic_rejection(
            result,
            raw_lookup=raw_lookup,
            blocklist_domains=blocklist_domains,
            known_source_domains=configured_domains,
            existing_actor_domains=(existing_actor_domains if entity_type == "actor" else []),
            non_content_paths=config.get("non_content_path_fragments", []) or [],
            reject_seen_raw_urls=not (
                entity_type in {"event", "person"}
                and bool(config.get("fetch_enabled", False))
            ),
            entity_type=entity_type,
        )
        if rejected is None and entity_type == "actor":
            rejected = actor_document_rejection(result.url)
        if rejected is None and entity_type == "person":
            rejected = person_scope_rejection(
                result,
                held_actor_domains=existing_actor_domains,
                config=config,
            )
        if rejected is None and entity_type == "person" \
                and bool(config.get("person_profile_pages_only", True)):
            # A complete profile is on the person's own profile page; a people
            # directory is a list of leads to follow (people_targets.py).
            kind = profile_page_kind(result.url)
            if kind == "directory":
                if directories is not None:
                    directories.append(result)
                rejected = SimpleNamespace(domain=domain, reason=(
                    "A people directory, not one person's profile: the profiles of the "
                    "people it lists on this topic are read instead."))
            elif kind == "other":
                rejected = SimpleNamespace(domain=domain, reason=(
                    "Not a person's profile page: news, events, documents and other pages "
                    "never hold a complete profile."))
        if rejected is None and entity_type in {"event", "person"}:
            # United States only, decided before any paid triage or read
            # (agents/discovery/search/us_scope.py). Actors are unchanged.
            abroad = result_outside_us(result.url, result.title, result.snippet)
            if abroad is not None:
                stats["outside_us_rejected"] = int(stats.get("outside_us_rejected", 0) or 0) + 1
                rejected = SimpleNamespace(domain=domain, reason=abroad)
        if rejected is not None:
            stats["deterministic_rejected"] += 1
            candidate_rows.append(
                CandidateRecord.from_result(
                    run_id=run_id,
                    entity_type=entity_type,
                    result=result,
                    domain=rejected.domain or domain,
                    triage_verdict="rejected",
                    triage_reason=rejected.reason,
                    fit_score=None,
                )
            )
        else:
            pending.append(result)
    stats["deterministic_survivors"] = len(pending)
    if not pending:
        logger.warning("open-web deterministic triage left zero candidates for LLM triage")
    return pending


def _collapse_accepted_actor_domains(candidate_rows: list[CandidateRecord]) -> int:
    grouped: dict[str, list[tuple[int, CandidateRecord]]] = {}
    for index, candidate in enumerate(candidate_rows):
        if candidate.entity_type != "actor" or candidate.triage_verdict != "accepted":
            continue
        domain = registrable_domain(candidate.domain)
        if domain:
            grouped.setdefault(domain, []).append((index, candidate))

    collapsed = 0
    for candidates in grouped.values():
        if len(candidates) < 2:
            continue
        survivor_index, survivor = max(
            candidates,
            key=lambda item: (
                -1.0 if item[1].fit_score is None else item[1].fit_score,
                -item[0],
            ),
        )
        for index, candidate in candidates:
            if index == survivor_index:
                continue
            candidate_rows[index] = replace(
                candidate,
                triage_verdict="duplicate",
                duplicate_of=survivor.candidate_id,
            )
            collapsed += 1
    return collapsed


def _attach_actor_query_metadata(stats: dict[str, object], metadata: dict[str, object]) -> None:
    stats["actor_query_grid_size"] = int(metadata.get("query_grid_size") or 0)
    actor_types = [str(value) for value in metadata.get("actor_types", []) or []]
    stats["actor_type_count"] = len(actor_types)
    selected_hubs = []
    for hub in metadata.get("selected_hubs", []) or []:
        if not isinstance(hub, dict):
            continue
        name = str(hub.get("name") or "").strip()
        if not name:
            continue
        count = hub.get("actor_count")
        selected_hubs.append(f"{name} ({count})")
    stats["actor_selected_thinnest_hubs"] = "; ".join(selected_hubs)


def _cap_triage_candidates(
    *,
    run_id: str,
    entity_type: str,
    pending_results: list[SearchResult],
    config: dict[str, object],
    candidate_rows: list[CandidateRecord],
) -> tuple[list[SearchResult], int]:
    unique = _unique_by_url(pending_results)
    max_triaged = int(config.get("max_candidates_triaged", 200))
    triaged = unique[:max_triaged]
    capped_urls = {result.url for result in unique[max_triaged:]}
    if not capped_urls:
        return triaged, 0

    capped_count = 0
    for result in pending_results:
        if result.url not in capped_urls:
            continue
        capped_count += 1
        candidate_rows.append(
            CandidateRecord.from_result(
                run_id=run_id,
                entity_type=entity_type,
                result=result,
                domain=normalized_domain(result.url),
                triage_verdict="rejected",
                triage_reason="max_candidates_triaged cap hit before LLM triage",
                fit_score=None,
            )
        )
    return triaged, capped_count


def _llm_triage(
    *,
    entity_type: str,
    results: list[SearchResult],
    triage_client,
    config: dict[str, object],
    session,
    root: Path,
    cost_meter: CostMeter,
    actor_query_metadata: dict[str, object] | None = None,
) -> dict[str, TriageDecision]:
    if not results:
        return {}
    sectors = (
        load_active_sectors(session, root) if entity_type == "actor" else load_seeded_sectors(root)
    )
    if entity_type == "event":
        references = load_event_reference_examples(session)
    else:
        references = []
    actor_context = None
    if entity_type == "person":
        actor_context = {
            "candidate_hubs": _candidate_hubs_from_query_plan(
                results,
                actor_query_metadata or {},
            )
        }
    decisions: dict[str, TriageDecision] = {}
    batch_size_key = (
        f"{entity_type}_triage_batch_size"
        if entity_type in {"actor", "event", "person"}
        else "triage_batch_size"
    )
    batch_size = int(config.get(batch_size_key, config.get("triage_batch_size", 20)))
    if batch_size <= 0:
        raise RuntimeError(f"open_web_discovery.{batch_size_key} must be positive")
    for index in range(0, len(results), batch_size):
        batch = results[index : index + batch_size]
        batch_decisions = _triage_batch_with_retry(
            batch,
            triage_client=triage_client,
            entity_type=entity_type,
            sectors=sectors,
            references=references,
            actor_context=actor_context,
        )
        decisions.update(batch_decisions)
        cost_meter.enforce()
    return decisions


def _triage_batch_with_retry(
    batch: list[SearchResult],
    *,
    triage_client,
    entity_type: str,
    sectors: list[dict[str, str]],
    references: list[dict[str, object]],
    actor_context: dict[str, object] | None = None,
) -> dict[str, TriageDecision]:
    decisions = _triage_once(
        batch,
        triage_client=triage_client,
        entity_type=entity_type,
        sectors=sectors,
        references=references,
        actor_context=actor_context,
    )
    if decisions is None:
        logger.warning("LLM triage batch failed; retrying split batch once")
        return _retry_split_batch_once(
            batch,
            triage_client=triage_client,
            entity_type=entity_type,
            sectors=sectors,
            references=references,
            actor_context=actor_context,
            incomplete_reason="batch failed after split retry",
        )

    batch_decisions = _only_batch_decisions(batch, decisions)
    if _has_decision_for_every_candidate(batch, batch_decisions):
        return batch_decisions

    missing = [candidate for candidate in batch if candidate.url not in batch_decisions]
    logger.warning(
        "LLM triage returned %d/%d decision(s); retrying split batch once",
        len(batch_decisions),
        len(batch),
    )
    split_decisions = _retry_split_batch_once(
        batch,
        triage_client=triage_client,
        entity_type=entity_type,
        sectors=sectors,
        references=references,
        actor_context=actor_context,
        incomplete_reason="candidate omitted after split retry",
    )
    for url, decision in batch_decisions.items():
        split_decisions[url] = decision
    still_missing = [candidate for candidate in missing if candidate.url not in split_decisions]
    split_decisions.update(
        _incomplete_decisions(still_missing, "candidate omitted after split retry")
    )
    return _only_batch_decisions(batch, split_decisions)


def _triage_once(
    batch: list[SearchResult],
    *,
    triage_client,
    entity_type: str,
    sectors: list[dict[str, str]],
    references: list[dict[str, object]],
    actor_context: dict[str, object] | None = None,
) -> dict[str, TriageDecision] | None:
    try:
        kwargs = {
            "entity_type": entity_type,
            "sectors": sectors,
            "references": references,
        }
        if actor_context is not None and _triage_supports_actor_context(triage_client):
            kwargs["actor_context"] = actor_context
        return triage_client.triage(batch, **kwargs)
    except Exception as exc:  # A malformed/failed LLM batch must not kill the run.
        if _is_api_credit_exhausted(exc):
            raise ApiCreditExhaustedError(API_CREDIT_EXHAUSTED_STATUS_REASON) from exc
        logger.warning("LLM triage call failed for %d candidate(s): %s", len(batch), exc)
        return None


def _retry_split_batch_once(
    batch: list[SearchResult],
    *,
    triage_client,
    entity_type: str,
    sectors: list[dict[str, str]],
    references: list[dict[str, object]],
    actor_context: dict[str, object] | None = None,
    incomplete_reason: str,
) -> dict[str, TriageDecision]:
    if not batch:
        return {}

    split_at = max(1, len(batch) // 2)
    chunks = [batch[:split_at], batch[split_at:]]
    decisions: dict[str, TriageDecision] = {}
    for chunk in chunks:
        if not chunk:
            continue
        retry_decisions = _triage_once(
            chunk,
            triage_client=triage_client,
            entity_type=entity_type,
            sectors=sectors,
            references=references,
            actor_context=actor_context,
        )
        if retry_decisions is None:
            decisions.update(_incomplete_decisions(chunk, incomplete_reason))
            continue
        chunk_decisions = _only_batch_decisions(chunk, retry_decisions)
        missing = [candidate for candidate in chunk if candidate.url not in chunk_decisions]
        if missing:
            logger.warning(
                "LLM triage split retry returned %d/%d decision(s)",
                len(chunk_decisions),
                len(chunk),
            )
        decisions.update(chunk_decisions)
        decisions.update(_incomplete_decisions(missing, incomplete_reason))
    return _only_batch_decisions(batch, decisions)


def _triage_supports_actor_context(triage_client) -> bool:
    try:
        parameters = inspect.signature(triage_client.triage).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        parameter.name == "actor_context"
        or parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )


def _candidate_topics(
    session, candidate_hubs: dict[str, tuple[str, ...]]
) -> dict[str, dict[str, str]]:
    """Architecture V2: each actor is found for the topic of the hub its query targeted."""
    if session is None:
        return {}
    has_topics = session.execute(
        text("SELECT to_regclass('public.topic') IS NOT NULL AS present")
    ).mappings().first()
    if not has_topics or not has_topics.get("present"):
        return {}
    hub_topics = {
        str(row["name"]): {"topic_id": str(row["topic_id"]), "code": str(row["code"])}
        for row in session.execute(text(
            "SELECT h.name, h.topic_id::text AS topic_id, t.code FROM hub h "
            "JOIN topic t ON t.topic_id = h.topic_id"
        )).mappings().all()
    }
    topics: dict[str, dict[str, str]] = {}
    for url, hub_names in candidate_hubs.items():
        hub_name = next((name for name in hub_names if name in hub_topics), None)
        if hub_name:
            topics[url] = {**hub_topics[hub_name], "hub_name": hub_name}
    return topics


def _lead_context(config, cost_meter, *, session, sectors, request) -> dict[str, object]:
    """What the lead step needs: a cheap model, and the map to dedupe against.

    Leads are names to be checked, not decisions, so the cheapest model reads
    the titles and snippets; every name is then verified for free on its own
    site and scored by the same model and gates as any other page.
    """
    if int(config.get("actor_max_leads_per_run", 20)) <= 0:
        return {}
    pricing = dict(config.get("actor_lead_llm_pricing") or config.get("search_llm_pricing") or {})
    client = ClaudeToolClient(
        str(config.get("actor_lead_model", "claude-haiku-4-5")),
        cost_meter=cost_meter,
        input_usd_per_million=float(pricing.get("input_usd_per_million", 0.0)),
        output_usd_per_million=float(pricing.get("output_usd_per_million", 0.0)),
    )
    names = {code: name for code, name in ((s["code"], s["name"]) for s in sectors)}
    if request is not None:
        topic = ", ".join(names.get(code, code) for code in request.sector_codes)
        if request.focus_terms:
            topic += " - especially " + ", ".join(request.focus_terms)
        area = ", ".join(request.geographies())
    else:
        topic, area = ", ".join(names.values()), "the United States"
    existing_names: list[str] = []
    if session is not None:
        existing_names = [
            re.sub(r"[^a-z0-9]+", " ", str(row[0]).casefold()).strip()
            for row in session.execute(text(
                "SELECT name FROM actor WHERE merged_into_actor_id IS NULL AND name IS NOT NULL"
            )).all()
        ]
    return {
        "lead_client": client,
        "lead_topic": topic,
        "lead_area": area,
        "existing_actor_domains": [
            d for d in (registrable_domain(x) for x in load_existing_actor_domains(session)) if d
        ] if session is not None else [],
        "existing_actor_names": existing_names,
    }


def _request_topics(session, request, results) -> dict[str, dict[str, str]]:
    """Every candidate of a requested run is found for the requested topic.

    Topics mirror sectors by code. With several requested sectors the first is
    the topic of record; the quality gate has already required the page to
    evidence at least one of them.
    """
    if session is None:
        return {}
    code = request.sector_codes[0]
    row = session.execute(
        text("SELECT topic_id::text AS topic_id, code FROM topic WHERE code = :code"),
        {"code": code},
    ).mappings().first()
    if row is None:
        return {}
    topic = {
        "topic_id": str(row["topic_id"]),
        "code": str(row["code"]),
        "request_title": request.title,
    }
    return {result.url: topic for result in results}


def _candidate_hubs_from_query_plan(
    results: list[SearchResult],
    metadata: dict[str, object],
) -> dict[str, tuple[str, ...]]:
    hubs_by_query: dict[str, str] = {}
    query_plan = [
        *(metadata.get("query_plan", []) or []),
        *(metadata.get("use_case_query_plan", []) or []),
    ]
    for item in query_plan:
        if not isinstance(item, dict):
            continue
        query = str(item.get("query") or "").strip()
        hub_name = str(item.get("hub_name") or "").strip()
        if query and hub_name:
            hubs_by_query[query] = hub_name

    candidate_hubs: dict[str, tuple[str, ...]] = {}
    for result in results:
        hubs: list[str] = []
        for query in result.query.split(" | "):
            hub_name = hubs_by_query.get(query)
            if hub_name and hub_name not in hubs:
                hubs.append(hub_name)
        candidate_hubs[result.url] = tuple(hubs)
    return candidate_hubs


def _deduplicate_search_results(results: list[SearchResult]) -> list[SearchResult]:
    grouped: dict[str, SearchResult] = {}
    queries_by_url: dict[str, list[str]] = {}
    for result in results:
        url = normalize_candidate_url(result.url)
        if not url:
            url = result.url.strip()
        if url not in grouped:
            grouped[url] = replace(result, url=url)
            queries_by_url[url] = []
        if result.query not in queries_by_url[url]:
            queries_by_url[url].append(result.query)

    deduplicated: list[SearchResult] = []
    for url, result in grouped.items():
        deduplicated.append(replace(result, query=" | ".join(queries_by_url[url])))
    return deduplicated


def normalize_candidate_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    parsed = urlsplit(text)
    if not parsed.scheme or not parsed.netloc:
        return text.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))


def _only_batch_decisions(
    batch: list[SearchResult],
    decisions: dict[str, TriageDecision],
) -> dict[str, TriageDecision]:
    batch_urls = {candidate.url for candidate in batch}
    return {url: decision for url, decision in decisions.items() if url in batch_urls}


def _has_decision_for_every_candidate(
    batch: list[SearchResult],
    decisions: dict[str, TriageDecision],
) -> bool:
    return len(decisions) == len(batch) and all(candidate.url in decisions for candidate in batch)


def _incomplete_decisions(
    candidates: list[SearchResult],
    reason: str,
) -> dict[str, TriageDecision]:
    return {
        candidate.url: TriageDecision(
            url=candidate.url,
            is_entity_type=False,
            plausible_sector=False,
            fit_score=None,
            reason=f"{TRIAGE_INCOMPLETE_REASON_PREFIX} {reason}",
        )
        for candidate in candidates
    }


def _append_llm_triaged_rows(
    *,
    run_id: str,
    entity_type: str,
    pending_results: list[SearchResult],
    decisions: dict[str, TriageDecision],
    config: dict[str, object],
    candidate_rows: list[CandidateRecord],
) -> None:
    capped_urls = {
        row.url
        for row in candidate_rows
        if row.triage_reason == "max_candidates_triaged cap hit before LLM triage"
    }
    for result in pending_results:
        if result.url in capped_urls:
            continue
        decision = decisions.get(result.url)
        if decision is None:
            decision = TriageDecision(
                url=result.url,
                is_entity_type=False,
                plausible_sector=False,
                fit_score=None,
                reason=f"{TRIAGE_INCOMPLETE_REASON_PREFIX} candidate was not assigned a decision",
            )
        verdict = (
            "triage_incomplete"
            if entity_type in {"actor", "event", "person"}
            and is_triage_incomplete(decision)
            else ("accepted" if decision.is_entity_type else "rejected")
            if entity_type in {"actor", "event", "person"}
            else "rejected"
        )
        reason = decision.reason
        candidate_rows.append(
            CandidateRecord.from_result(
                run_id=run_id,
                entity_type=entity_type,
                result=result,
                domain=normalized_domain(result.url),
                triage_verdict=verdict,
                triage_reason=reason,
                fit_score=decision.fit_score,
                triage_details=(
                    decision if entity_type in {"actor", "event", "person"} else None
                ),
            )
        )


def _unique_by_url(results: list[SearchResult]) -> list[SearchResult]:
    seen: set[str] = set()
    unique: list[SearchResult] = []
    for result in results:
        if result.url in seen:
            continue
        seen.add(result.url)
        unique.append(result)
    return unique


def _empty_stats() -> dict[str, object]:
    return {
        "queries_generated": 0,
        "deterministic_queries": 0,
        "llm_queries": 0,
        "reference_count": 0,
        "searches_executed": 0,
        "search_results": 0,
        "search_results_unique": 0,
        "search_results_deduplicated": 0,
        "deterministic_rejected": 0,
        "deterministic_survivors": 0,
        "triage_cap_rejected": 0,
        "triage_incomplete": 0,
        "candidates_written": 0,
        "accepted": 0,
        "rejected": 0,
        "fetch_candidates": 0,
        "pages_selected": 0,
        "pages_fetched": 0,
        "new_domains_eligible": 0,
        "blocked_domains_skipped": 0,
        "fetch_failures": 0,
        "skipped_unchanged": 0,
        "records_extracted": 0,
        "records_in_sector": 0,
        "records_out_of_sector": 0,
        "records_relevant": 0,
        "records_staged": 0,
        "records_promoted": 0,
        "absorbed": 0,
        "queued_for_review": 0,
        "created": 0,
        "already_held": 0,
        "failures": 0,
        "cost_usd": 0.0,
    }


def _attach_llm_cache_stats(
    stats: dict[str, object],
    *,
    prefix: str,
    before: dict[str, int],
    client,
) -> None:
    usage = llm_usage_delta(before, llm_usage_snapshot(client))
    stats[f"{prefix}_llm_calls"] = usage["calls"]
    stats[f"{prefix}_cache_write_tokens"] = usage["cache_write_tokens"]
    stats[f"{prefix}_cache_read_tokens"] = usage["cache_read_tokens"]
    stats[f"{prefix}_cache_hit_rate"] = usage["cache_hit_rate"]


def _report_path(root: Path, explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
        return path if path.is_absolute() else root / path
    return root / "agents" / "runs" / "open-web-discovery.md"


def _rejection_report_path(
    root: Path,
    explicit: str | None,
    *,
    report_path: Path,
) -> Path:
    if explicit:
        path = Path(explicit)
        return path if path.is_absolute() else root / path
    suffix = report_path.suffix or ".md"
    return report_path.with_name(f"{report_path.stem}-rejections{suffix}")


def _audit_path(root: Path, explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
        return path if path.is_absolute() else root / path
    return root / "agents" / "runs" / "open-web-discovery-audit.csv"


def _spreadsheet_path(root: Path, explicit: str | None, *, report_path: Path) -> Path:
    if explicit:
        path = Path(explicit)
        return path if path.is_absolute() else root / path
    return report_path.with_name(f"{report_path.stem}-records.csv")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entity", choices=["event", "actor", "person"], required=True)
    parser.add_argument("--report-out")
    parser.add_argument("--rejection-report-out")
    parser.add_argument("--audit-out")
    parser.add_argument("--spreadsheet-out")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument(
        "--preview-person-create",
        action="store_true",
        help="dry-run person identity routes using create/skip/review; never permits writes",
    )
    parser.add_argument(
        "--enable-people-for-run",
        action="store_true",
        help="enable person discovery for this dry run only; never permits live writes",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    result = run_search_triage(args)
    print(
        "open-web discovery run_id={run_id} status={status} report={report_path}".format(
            **result
        )
    )
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
