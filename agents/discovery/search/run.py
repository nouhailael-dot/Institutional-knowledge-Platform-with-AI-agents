"""Open-web search and triage CLI.

Phase 1 deliberately stops at candidate search and triage. It does not fetch
candidate pages, stage records, route records, or write canonical tables.
"""

from __future__ import annotations

import argparse
import inspect
import logging
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from agents.common.config import load_sources_config
from agents.common.cost import CostLimitExceeded, CostMeter
from agents.common.llm import ClaudeToolClient
from agents.common.run_log import InMemoryRunLog, SQLRunLog, write_audit_csv
from agents.discovery.search.models import CandidateRecord, SearchResult, TriageDecision
from agents.discovery.search.phase2 import fetch_extract_stage_events
from agents.discovery.search.providers import SearchProvider, build_search_provider
from agents.discovery.search.query_generation import (
    QueryBundle,
    QueryGenerator,
    load_event_reference_examples,
    load_seeded_sectors,
)
from agents.discovery.search.report import write_candidate_report
from agents.discovery.search.store import InMemorySearchCandidateStore, SQLSearchCandidateStore
from agents.discovery.search.triage import (
    TRIAGE_INCOMPLETE_REASON_PREFIX,
    SearchTriageClient,
    actor_fit_weights,
    actor_partner_findability_floor,
    blocklist_domains_for_entity,
    deterministic_rejection,
    has_partner_route,
    is_triage_incomplete,
    known_source_domains,
    load_actor_hub_sector_counts,
    load_actor_triage_reference_examples,
    load_existing_actor_domains,
    normalized_domain,
    triage_verdict,
)

logger = logging.getLogger(__name__)


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
    audit_path = _audit_path(root, getattr(args, "audit_out", None))

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
            weights = actor_fit_weights(config)
            stats["actor_partner_findability_floor"] = actor_partner_findability_floor(config)
            stats["actor_fit_weight_partner_findability"] = weights["partner_findability"]
            stats["actor_fit_weight_distinctiveness"] = weights["distinctiveness"]

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
            store=store,
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

        if entity_type == "event" and bool(config.get("fetch_enabled", False)):
            attention_reasons.extend(
                fetch_extract_stage_events(
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
                    event_candidates=event_candidates,
                )
            )

        stats["candidates_written"] = store.write_candidates(candidate_rows)
        stats["accepted"] = sum(1 for row in candidate_rows if row.triage_verdict == "accepted")
        stats["rejected"] = sum(1 for row in candidate_rows if row.triage_verdict == "rejected")
        stats["triage_incomplete"] = sum(
            1 for row in candidate_rows if row.triage_verdict == "triage_incomplete"
        )
        if entity_type == "actor":
            _attach_actor_partner_stats(stats, candidate_rows)
        if stats["triage_incomplete"]:
            attention_reasons.append(
                f"triage_incomplete: {stats['triage_incomplete']} candidate(s) "
                "were not judged after retry"
            )
        stats["cost_usd"] = cost_meter.spent_usd
        stats["cost"] = cost_meter.snapshot()
        status = "attention" if attention_reasons else "succeeded"
        status_reason = "; ".join(attention_reasons)
        write_audit_csv(audit_path, audit_rows)
        run_log.close_run(
            run_id,
            status=status,
            stats=stats,
            cost_usd=cost_meter.spent_usd,
            status_reason=status_reason,
        )
        write_candidate_report(
            report_path,
            run_id=run_id,
            status=status,
            status_reason=status_reason,
            stats=stats,
            queries=generated_queries,
            candidates=candidate_rows,
        )
        return {
            "run_id": run_id,
            "status": status,
            "status_reason": status_reason,
            "stats": stats,
            "queries": generated_queries,
            "candidates": candidate_rows,
            "report_path": str(report_path),
            "audit_path": str(audit_path),
            "exit_code": 1 if status == "attention" else 0,
        }
    except CostLimitExceeded as exc:
        stats["cost_usd"] = cost_meter.spent_usd
        stats["cost"] = cost_meter.snapshot()
        stats["candidates_written"] = store.write_candidates(candidate_rows)
        status_reason = f"max_usd_per_run cap hit: {exc}"
        write_audit_csv(audit_path, audit_rows)
        run_log.close_run(
            run_id,
            status="attention",
            stats=stats,
            cost_usd=cost_meter.spent_usd,
            status_reason=status_reason,
        )
        write_candidate_report(
            report_path,
            run_id=run_id,
            status="attention",
            status_reason=status_reason,
            stats=stats,
            queries=generated_queries,
            candidates=candidate_rows,
        )
        return {
            "run_id": run_id,
            "status": "attention",
            "status_reason": status_reason,
            "stats": stats,
            "queries": generated_queries,
            "candidates": candidate_rows,
            "report_path": str(report_path),
            "audit_path": str(audit_path),
            "exit_code": 1,
        }
    except Exception as exc:
        stats["failures"] += 1
        stats["cost_usd"] = cost_meter.spent_usd
        stats["cost"] = cost_meter.snapshot()
        stats["candidates_written"] = store.write_candidates(candidate_rows)
        write_audit_csv(audit_path, audit_rows)
        run_log.fail_run(
            run_id,
            error=str(exc),
            stats=stats,
            cost_usd=cost_meter.spent_usd,
            status_reason=str(exc),
        )
        write_candidate_report(
            report_path,
            run_id=run_id,
            status="failed",
            status_reason=str(exc),
            stats=stats,
            queries=generated_queries,
            candidates=candidate_rows,
        )
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


def _deterministic_triage(
    *,
    run_id: str,
    entity_type: str,
    results: list[SearchResult],
    store,
    config: dict[str, object],
    full_config: dict[str, object],
    session,
    candidate_rows: list[CandidateRecord],
    stats: dict[str, object],
) -> list[SearchResult]:
    pending: list[SearchResult] = []
    configured_domains = known_source_domains(full_config)
    blocklist_domains = blocklist_domains_for_entity(entity_type, config)
    existing_actor_domains = load_existing_actor_domains(session) if entity_type == "actor" else []
    if entity_type == "actor":
        stats["actor_existing_domain_blocklist_count"] = len(existing_actor_domains)
    for result in results:
        domain = normalized_domain(result.url)
        rejected = deterministic_rejection(
            result,
            raw_lookup=store,
            blocklist_domains=blocklist_domains,
            known_source_domains=configured_domains,
            existing_actor_domains=existing_actor_domains,
            non_content_paths=config.get("non_content_path_fragments", []) or [],
            reject_seen_raw_urls=not (
                entity_type == "event" and bool(config.get("fetch_enabled", False))
            ),
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


def _attach_actor_partner_stats(
    stats: dict[str, object],
    candidate_rows: list[CandidateRecord],
) -> None:
    evaluated = [
        row
        for row in candidate_rows
        if row.partner_signals is not None
        and not str(row.triage_reason or "").lower().startswith(
            TRIAGE_INCOMPLETE_REASON_PREFIX
        )
    ]
    route_rejected = sum(row.triage_reason == "no partner route" for row in evaluated)
    stats["actor_partner_evaluated"] = len(evaluated)
    stats["actor_partner_route_rejected"] = route_rejected
    stats["actor_partner_route_rejected_proportion"] = (
        route_rejected / len(evaluated) if evaluated else 0.0
    )


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
    references = (
        load_actor_triage_reference_examples(session)
        if entity_type == "actor"
        else load_event_reference_examples(session)
    )
    actor_context = None
    if entity_type == "actor":
        actor_context = {
            "coverage_counts": load_actor_hub_sector_counts(session),
            "candidate_hubs": _candidate_hubs_from_query_plan(
                results,
                actor_query_metadata or {},
            ),
        }
    decisions: dict[str, TriageDecision] = {}
    batch_size = int(config.get("triage_batch_size", 20))
    if batch_size <= 0:
        raise RuntimeError("open_web_discovery.triage_batch_size must be positive")
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
    except Exception as exc:  # noqa: BLE001 - a malformed/failed LLM batch must not kill the run.
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
    partner_floor = (
        actor_partner_findability_floor(config) if entity_type == "actor" else None
    )
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
        verdict = triage_verdict(
            decision,
            floor=floor,
            entity_type=entity_type,
            partner_floor=partner_floor,
        )
        reason = decision.reason
        if entity_type == "actor" and verdict == "rejected" and decision.accepted:
            if not has_partner_route(decision, floor=float(partner_floor or 0.0)):
                reason = "no partner route"
        elif (
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
                actor_triage=decision if entity_type == "actor" else None,
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
        "failures": 0,
        "cost_usd": 0.0,
    }


def _report_path(root: Path, explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
        return path if path.is_absolute() else root / path
    return root / "agents" / "runs" / "open-web-discovery.md"


def _audit_path(root: Path, explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
        return path if path.is_absolute() else root / path
    return root / "agents" / "runs" / "open-web-discovery-audit.csv"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entity", choices=["event", "actor", "person"], required=True)
    parser.add_argument("--report-out")
    parser.add_argument("--audit-out")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--offline", action="store_true")
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
