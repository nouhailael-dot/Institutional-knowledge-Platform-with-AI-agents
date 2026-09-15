"""Open-web search and triage CLI.

Phase 1 deliberately stops at candidate search and triage. It does not fetch
candidate pages, stage records, route records, or write canonical tables.
"""

from __future__ import annotations

import argparse
import inspect
import logging
from dataclasses import replace
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from agents.common.config import load_sources_config
from agents.common.cost import CostLimitExceeded, CostMeter
from agents.common.llm import ClaudeToolClient
from agents.common.resolve_route import load_actor_resolver_class
from agents.common.run_log import InMemoryRunLog, SQLRunLog, write_audit_csv
from agents.discovery.search.actor_scoring import actor_rubric_weights, actor_score_thresholds
from agents.discovery.search.models import CandidateRecord, SearchResult, TriageDecision
from agents.discovery.search.phase2 import (
    fetch_extract_stage_events,
    fetch_extract_stage_people,
    fetch_score_stage_actors,
)
from agents.discovery.search.providers import SearchProvider, build_search_provider
from agents.discovery.search.query_generation import (
    QueryBundle,
    QueryGenerator,
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
    blocklist_domains_for_entity,
    deterministic_rejection,
    has_person_topic_evidence,
    is_triage_incomplete,
    known_source_domains,
    load_actor_hub_sector_counts,
    load_existing_actor_domains,
    normalized_domain,
    person_scope_rejection,
    registrable_domain,
    triage_verdict,
)

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

    cost_meter = cost_meter or CostMeter(max_usd=float(config.get("max_usd_per_run", 5.0)))
    llm_client = llm_client or _build_llm_client(config, cost_meter)
    run_log = run_log or (InMemoryRunLog() if offline else SQLRunLog(session))
    store = store or (
        InMemorySearchCandidateStore() if offline else SQLSearchCandidateStore(session)
    )
    if offline and search_provider is None:
        raise RuntimeError("--offline open-web search requires an injected search_provider")
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
    stats = _empty_stats()
    candidate_rows: list[CandidateRecord] = []
    audit_rows: list[dict[str, object]] = []
    generated_queries: dict[str, list[str]] = {entity_type: []}

    try:
        raw_lookup = InMemorySearchCandidateStore(
            seen_raw_urls=store.load_seen_raw_urls()
        )
        bundle: QueryBundle = query_generator.generate(
            entity_type, session=session, project_root=root
        )
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
        elif entity_type == "person":
            stats["person_relevance_floor"] = float(
                dict(config.get("accept_floor", {}) or {}).get("person", 0.75)
            )
            stats["person_query_distinct_hubs"] = int(
                dict(bundle.metadata or {}).get("distinct_hubs_covered") or 0
            )
            stats["person_query_sector_codes"] = ", ".join(
                str(value)
                for value in dict(bundle.metadata or {}).get("sector_codes_covered", []) or []
            )

        attention_reasons: list[str] = []
        queries = bundle.queries
        max_searches = int(config.get("max_searches", 40))
        if len(queries) > max_searches:
            attention_reasons.append(
                f"max_searches cap hit: generated {len(queries)}, executed {max_searches}"
            )
            queries = queries[:max_searches]

        search_results: list[SearchResult] = []
        for query in queries:
            stats["searches_executed"] += 1
            results = search_provider.search(query, count=int(config.get("results_per_query", 10)))
            cost_meter.enforce()
            search_results.extend(results)
        stats["search_results"] = len(search_results)
        deduplicated_results = _deduplicate_search_results(search_results)
        stats["search_results_unique"] = len(deduplicated_results)
        stats["search_results_deduplicated"] = len(search_results) - len(deduplicated_results)

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
        )

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
            sectors = load_seeded_sectors(root)
            actor_context = {
                "coverage_counts": load_actor_hub_sector_counts(session),
                "candidate_hubs": _candidate_hubs_from_query_plan(
                    triaged_results,
                    bundle.metadata or {},
                ),
            }
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
            attention_reasons.extend(
                fetch_extract_stage_events(
                    run_id=run_id,
                    candidates=candidate_rows,
                    config={
                        **config,
                        "event_qualification": dict(
                            full_config.get("event_qualification", {})
                        ),
                    },
                    root=root,
                    session=session,
                    live=live,
                    run_log=run_log,
                    cost_meter=cost_meter,
                    stats=stats,
                    audit_rows=audit_rows,
                    source=fetch_source,
                    extractor=extractor,
                    raw_store=raw_store,
                    stage_store=stage_store,
                    domain_store=domain_store,
                    event_candidates=event_candidates,
                    actor_resolver=actor_resolver,
                    run_date=run_date,
                )
            )
        elif entity_type == "person" and bool(config.get("fetch_enabled", False)):
            attention_reasons.extend(
                fetch_extract_stage_people(
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
                    source=fetch_source,
                    extractor=extractor,
                    raw_store=raw_store,
                    stage_store=stage_store,
                    domain_store=domain_store,
                    person_candidates=person_candidates,
                    actor_resolver=actor_resolver,
                    run_date=run_date,
                    person_create_preview=person_create_preview,
                )
            )

        stats["accepted"] = sum(1 for row in candidate_rows if row.triage_verdict == "accepted")
        stats["rejected"] = sum(1 for row in candidate_rows if row.triage_verdict == "rejected")
        stats["triage_incomplete"] = sum(
            1 for row in candidate_rows if row.triage_verdict == "triage_incomplete"
        )
        if entity_type == "person":
            floor = float(dict(config.get("accept_floor", {}) or {}).get("person", 0.75))
            stats["person_rejected_below_floor"] = sum(
                1
                for row in candidate_rows
                if row.fit_score is not None
                and row.fit_score < floor
                and row.triage_verdict == "rejected"
            )
        if stats["triage_incomplete"]:
            attention_reasons.append(
                f"triage_incomplete: {stats['triage_incomplete']} candidate(s) "
                "were not judged after retry"
            )
        stats["cost_usd"] = cost_meter.spent_usd
        stats["cost"] = cost_meter.snapshot()
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
        if owned_session and session is not None:
            session.close()


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
        if rejected is None and entity_type == "person":
            rejected = person_scope_rejection(
                result,
                held_actor_domains=existing_actor_domains,
                config=config,
            )
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
    sectors = load_seeded_sectors(root)
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
    batch_size_key = "actor_triage_batch_size" if entity_type == "actor" else "triage_batch_size"
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


def _candidate_hubs_from_query_plan(
    results: list[SearchResult],
    metadata: dict[str, object],
) -> dict[str, tuple[str, ...]]:
    hubs_by_query: dict[str, str] = {}
    for item in metadata.get("query_plan", []) or []:
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
    floors = dict(config.get("accept_floor", {}) or {})
    floor = float(floors.get(entity_type, 0.5))
    decided_urls = set(decisions)
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
            if entity_type == "actor" and is_triage_incomplete(decision)
            else ("accepted" if decision.is_entity_type else "rejected")
            if entity_type == "actor"
            else triage_verdict(
                decision,
                floor=floor,
                entity_type=entity_type,
            )
        )
        reason = decision.reason
        if (
            entity_type == "person"
            and verdict == "rejected"
            and decision.accepted
            and not has_person_topic_evidence(decision)
        ):
            reason = "insufficient direct sector and topic evidence"
        elif (
            entity_type != "actor"
            and
            result.url in decided_urls
            and verdict == "rejected"
            and decision.fit_score is not None
            and not is_triage_incomplete(decision)
        ):
            reason = f"{reason}; fit_score below accepted floor {floor:.2f}"
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
                    decision if entity_type in {"actor", "person"} else None
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
