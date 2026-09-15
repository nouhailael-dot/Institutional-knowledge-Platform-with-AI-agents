"""Bounded fetch and ingest for accepted open-web event candidates."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import text

from agents.common.cost import CostLimitExceeded
from agents.common.raw_storage import RawContentStore
from agents.common.resolve_route import load_event_candidates, load_person_candidates
from agents.discovery.extractors.event import EventExtractor
from agents.discovery.extractors.person import PersonExtractor
from agents.discovery.run import (
    _extract_stage_route_promote,
    _skip_audit_row,
    _storage_path_for_doc,
)
from agents.discovery.search.actor_scoring import (
    PROMPT_VERSION as ACTOR_ANALYSIS_VERSION,
)
from agents.discovery.search.actor_scoring import (
    ActorListwiseReranker,
    ActorRubricExtractor,
    PreExtractedActorExtractor,
    actor_score_band,
    actor_score_thresholds,
    read_analysis_cache,
    rerank_top_actor_candidates,
    rubric_hub_matches,
    rubric_sector_codes,
    score_actor_rubric,
    write_analysis_cache,
)
from agents.discovery.search.models import CandidateRecord
from agents.discovery.search.triage import (
    existing_actor_count_for_candidate,
    normalized_domain,
)
from agents.discovery.sources.base import FetchedDoc
from agents.discovery.sources.http_utils import RobotsAwareHttp
from agents.discovery.stage import InMemoryStageStore, SQLStageStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchPlan:
    candidates: list[CandidateRecord]
    eligible_pages: int
    eligible_new_domains: int
    page_cap_hit: bool
    domain_cap_hit: bool
    blocked_domains_skipped: int


@dataclass(frozen=True)
class ActorFetchOutcome:
    attention_reasons: list[str]
    candidates: list[CandidateRecord]


class OpenWebEventSource:
    """Fetch only URLs accepted by search triage, one level deep."""

    name = "open_web_search"
    entity_types = ("event", "actor", "person")

    def __init__(self, config: dict[str, object], *, http=None):
        self.config = config
        self.rate_limit_s = float(config.get("rate_limit_s", 1.0))
        strict_config = {**config, "strict_redirect_robots": True}
        self.http = http or RobotsAwareHttp(strict_config)

    def fetch(self, url: str) -> FetchedDoc:
        response = self.http.get(url)
        final_url = str(response.url)
        return FetchedDoc.from_content(
            url=final_url,
            content=response.text,
            content_type=response.headers.get("content-type", "text/html"),
            meta={
                "status_code": response.status_code,
                "source_name": self.name,
                "discovered_domain": normalized_domain(final_url),
                "untrusted_open_web_content": True,
            },
        )


class InMemoryDiscoveredDomainStore:
    def __init__(self, *, statuses: dict[str, str] | None = None):
        self.rows: dict[str, dict[str, object]] = {
            domain: {
                "domain": domain,
                "status": status,
                "pages_fetched": 0,
                "records_extracted": 0,
                "records_promoted": 0,
            }
            for domain, status in (statuses or {}).items()
        }

    def status_for(self, domain: str) -> str | None:
        row = self.rows.get(domain)
        return str(row["status"]) if row else None

    def touch(self, domain: str) -> None:
        self.rows.setdefault(
            domain,
            {
                "domain": domain,
                "status": "probation",
                "pages_fetched": 0,
                "records_extracted": 0,
                "records_promoted": 0,
            },
        )

    def add_counts(
        self,
        domain: str,
        *,
        pages_fetched: int = 0,
        records_extracted: int = 0,
        records_promoted: int = 0,
    ) -> None:
        self.touch(domain)
        row = self.rows[domain]
        row["pages_fetched"] = int(row["pages_fetched"]) + pages_fetched
        row["records_extracted"] = int(row["records_extracted"]) + records_extracted
        row["records_promoted"] = int(row["records_promoted"]) + records_promoted


class SQLDiscoveredDomainStore:
    def __init__(self, session):
        self.session = session

    def status_for(self, domain: str) -> str | None:
        row = self.session.execute(
            text("SELECT status FROM discovered_domain WHERE domain = :domain"),
            {"domain": domain},
        ).first()
        return str(row[0]) if row else None

    def touch(self, domain: str) -> None:
        self.session.execute(
            text(
                "INSERT INTO discovered_domain (domain, first_seen_at, last_seen_at, status) "
                "VALUES (:domain, now(), now(), 'probation') "
                "ON CONFLICT (domain) DO UPDATE SET last_seen_at = EXCLUDED.last_seen_at"
            ),
            {"domain": domain},
        )
        self.session.commit()

    def add_counts(
        self,
        domain: str,
        *,
        pages_fetched: int = 0,
        records_extracted: int = 0,
        records_promoted: int = 0,
    ) -> None:
        result = self.session.execute(
            text(
                "UPDATE discovered_domain SET last_seen_at = now(), "
                "pages_fetched = pages_fetched + :pages_fetched, "
                "records_extracted = records_extracted + :records_extracted, "
                "records_promoted = records_promoted + :records_promoted "
                "WHERE domain = :domain"
            ),
            {
                "domain": domain,
                "pages_fetched": pages_fetched,
                "records_extracted": records_extracted,
                "records_promoted": records_promoted,
            },
        )
        if result.rowcount != 1:
            self.session.rollback()
            raise RuntimeError(f"discovered_domain counter update missed domain {domain!r}")
        self.session.commit()


def plan_event_fetches(
    candidates: list[CandidateRecord],
    *,
    domain_store,
    config: dict[str, object],
) -> FetchPlan:
    return _plan_fetches(
        candidates,
        entity_type="event",
        domain_store=domain_store,
        config=config,
    )


def plan_person_fetches(
    candidates: list[CandidateRecord],
    *,
    domain_store,
    config: dict[str, object],
) -> FetchPlan:
    return _plan_fetches(
        candidates,
        entity_type="person",
        domain_store=domain_store,
        config=config,
    )


def plan_actor_fetches(
    candidates: list[CandidateRecord],
    *,
    domain_store,
    config: dict[str, object],
) -> FetchPlan:
    return _plan_fetches(
        candidates,
        entity_type="actor",
        domain_store=domain_store,
        config=config,
        require_fit_score=False,
    )


def _plan_fetches(
    candidates: list[CandidateRecord],
    *,
    entity_type: str,
    domain_store,
    config: dict[str, object],
    require_fit_score: bool = True,
) -> FetchPlan:
    max_pages = _positive_cap(config, "max_pages_fetched", 30)
    max_new_domains = _positive_cap(config, "max_new_domains", 10)
    floor = float(dict(config.get("fetch_fit_floor", {}) or {}).get(entity_type, 0.60))
    eligible = [
        candidate
        for candidate in candidates
        if candidate.entity_type == entity_type
        and candidate.triage_verdict == "accepted"
        and (
            not require_fit_score
            or (candidate.fit_score is not None and candidate.fit_score >= floor)
        )
    ]

    statuses: dict[str, str | None] = {}
    for candidate in eligible:
        statuses.setdefault(candidate.domain, domain_store.status_for(candidate.domain))
    eligible_new_domains = {domain for domain, status in statuses.items() if status is None}

    selected: list[CandidateRecord] = []
    selected_new_domains: set[str] = set()
    blocked_domains_skipped = 0
    domain_cap_hit = False
    page_cap_hit = False
    for candidate in eligible:
        domain = candidate.domain or normalized_domain(candidate.url)
        status = statuses.get(domain)
        if status == "blocked":
            blocked_domains_skipped += 1
            continue
        if status is None and domain not in selected_new_domains:
            if len(selected_new_domains) >= max_new_domains:
                domain_cap_hit = True
                continue
            selected_new_domains.add(domain)
        if len(selected) >= max_pages:
            page_cap_hit = True
            continue
        selected.append(candidate)

    return FetchPlan(
        candidates=selected,
        eligible_pages=len(eligible) - blocked_domains_skipped,
        eligible_new_domains=len(eligible_new_domains),
        page_cap_hit=page_cap_hit,
        domain_cap_hit=domain_cap_hit,
        blocked_domains_skipped=blocked_domains_skipped,
    )


def fetch_score_stage_actors(
    *,
    run_id: str,
    candidates: list[CandidateRecord],
    config: dict[str, object],
    root: Path,
    session,
    live: bool,
    run_log,
    cost_meter,
    stats: dict[str, object],
    audit_rows: list[dict[str, object]],
    actor_types: list[str],
    sector_codes: list[str],
    hub_names: list[str],
    actor_context: dict[str, object],
    source=None,
    rubric_extractor=None,
    reranker=None,
    raw_store=None,
    stage_store=None,
    domain_store=None,
    actor_resolver=None,
) -> ActorFetchOutcome:
    """Fetch gated actors, score stored-page evidence, then stage only the high band."""
    if not actor_types:
        raise RuntimeError("actor rubric pipeline requires actor types loaded from the database")
    if not sector_codes:
        raise RuntimeError("actor rubric pipeline requires seeded sector codes")
    if not hub_names:
        raise RuntimeError("actor rubric pipeline requires the canonical hub list")
    source = source or OpenWebEventSource(config)
    shared_client = None
    if rubric_extractor is None or reranker is None:
        shared_client = _extraction_client(config, cost_meter)
    rubric_extractor = rubric_extractor or ActorRubricExtractor(
        shared_client,
        max_tokens=int(config.get("actor_rubric_max_tokens", 4096)),
    )
    reranker = reranker or ActorListwiseReranker(
        shared_client,
        max_tokens=int(config.get("actor_rerank_max_tokens", 2048)),
    )
    raw_store = raw_store or RawContentStore.from_config(root, config)
    stage_store = stage_store or (
        InMemoryStageStore() if session is None else SQLStageStore(session)
    )
    domain_store = domain_store or (
        InMemoryDiscoveredDomainStore() if session is None else SQLDiscoveredDomainStore(session)
    )
    plan = plan_actor_fetches(candidates, domain_store=domain_store, config=config)
    stats["fetch_candidates"] = plan.eligible_pages
    stats["pages_selected"] = len(plan.candidates)
    stats["new_domains_eligible"] = plan.eligible_new_domains
    stats["blocked_domains_skipped"] = plan.blocked_domains_skipped
    attention_reasons = _cap_attention_reasons(plan, config)
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    docs: dict[str, tuple[FetchedDoc, str, str]] = {}

    for candidate in plan.candidates:
        candidate_domain = candidate.domain or normalized_domain(candidate.url)
        domain_store.touch(candidate_domain)
        page_fetched = False
        try:
            doc = source.fetch(candidate.url)
            page_fetched = True
            final_domain = normalized_domain(doc.url)
            if not final_domain:
                raise RuntimeError(f"fetched open-web page has invalid final URL {doc.url!r}")
            if final_domain != candidate_domain:
                raise RuntimeError(
                    "open-web candidate redirected across domains after admission: "
                    f"{candidate_domain!r} to {final_domain!r}"
                )
            domain_store.touch(final_domain)
            stats["pages_fetched"] += 1
            domain_store.add_counts(final_domain, pages_fetched=1)
            prior_raw = run_log.find_raw_document(url=doc.url, content_hash=doc.content_hash)
            storage_path = _storage_path_for_doc(
                raw_store, run_id=run_id, doc=doc, prior_raw=prior_raw
            )
            raw_document_id = run_log.write_raw_document(
                run_id=run_id, doc=doc, storage_path=storage_path
            )
            cache_path = (
                raw_store.base_dir
                / "actor_analysis"
                / f"{doc.content_hash}.{ACTOR_ANALYSIS_VERSION}.json"
            )
            analysis = read_analysis_cache(
                cache_path,
                actor_types=actor_types,
                sector_codes=sector_codes,
                hub_names=hub_names,
            )
            if analysis is None:
                analysis = rubric_extractor.extract(
                    doc,
                    actor_types=actor_types,
                    sector_codes=sector_codes,
                    hub_names=hub_names,
                )
                write_analysis_cache(cache_path, analysis)
                stats["actor_pages_analyzed"] = int(
                    stats.get("actor_pages_analyzed", 0) or 0
                ) + 1
            else:
                stats["skipped_unchanged"] += 1
            matched_sectors = rubric_sector_codes(analysis.rubric)
            matched_hubs = rubric_hub_matches(analysis.rubric)
            existing_count = existing_actor_count_for_candidate(
                url=candidate.url,
                hub_matches=matched_hubs,
                sector_codes=matched_sectors,
                actor_context=actor_context,
            )
            score = score_actor_rubric(
                analysis.rubric,
                existing_actor_count=existing_count,
                config=config,
            )
            by_id[candidate.candidate_id] = replace(
                candidate,
                page_fetched=True,
                fit_score=score.total,
                rubric=analysis.rubric,
                record_preview=analysis.record,
                score_breakdown=score.contributions,
                score_band=actor_score_band(score.total, config),
                hub_matches=matched_hubs,
                sector_codes=matched_sectors,
                distinctiveness=score.distinctiveness,
                existing_actor_count=existing_count,
            )
            docs[candidate.candidate_id] = (doc, final_domain, raw_document_id)
            cost_meter.enforce()
        except CostLimitExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - one untrusted page must not stop the batch.
            logger.warning("open-web actor fetch/rubric failed for %s: %s", candidate.url, exc)
            stats["fetch_failures"] += 1
            by_id[candidate.candidate_id] = replace(
                candidate,
                page_fetched=page_fetched,
                triage_verdict="analysis_failed",
                triage_reason=f"actor fetch or rubric failed: {exc}",
                score_band="analysis_failed",
            )
            audit_rows.append(
                {
                    "run_id": run_id,
                    "source": "open_web_search",
                    "entity_type": "actor",
                    "source_url": candidate.url,
                    "content_hash": "",
                    "natural_key": "",
                    "zone": "",
                    "score": "",
                    "target_entity_id": "",
                    "candidate_ids": [],
                    "status": "fetch_or_rubric_failed",
                    "error": str(exc),
                }
            )

    updated = [by_id[candidate.candidate_id] for candidate in candidates]
    scored = [candidate for candidate in updated if candidate.rubric is not None]
    reranked, rerank_attention = rerank_top_actor_candidates(
        scored,
        reranker=reranker,
        config=config,
    )
    attention_reasons.extend(rerank_attention)
    reranked_by_id = {candidate.candidate_id: candidate for candidate in reranked}
    updated = [reranked_by_id.get(candidate.candidate_id, candidate) for candidate in updated]

    final: list[CandidateRecord] = []
    for candidate in updated:
        if candidate.rubric is None:
            final.append(candidate)
            continue
        band = candidate.score_band or actor_score_band(float(candidate.fit_score or 0.0), config)
        verdict = "accepted" if band == "auto_high" else "rejected" if band == "auto_low" else "review"
        reason = f"actor rubric score {float(candidate.fit_score or 0.0):.3f} -> {band}"
        if band == "auto_high" and not (candidate.record_preview or {}).get("name"):
            band = "review"
            verdict = "review"
            reason = "actor rubric auto_high but canonical record is missing required name"
        final.append(
            replace(
                candidate,
                triage_verdict=verdict,
                triage_reason=reason,
                score_band=band,
            )
        )

    final_by_id = {candidate.candidate_id: candidate for candidate in final}
    auto_high = [candidate for candidate in final if candidate.score_band == "auto_high"]
    for candidate in auto_high:
        doc_entry = docs.get(candidate.candidate_id)
        if doc_entry is None:
            raise RuntimeError(f"auto_high actor candidate has no fetched document: {candidate.url}")
        doc, domain, raw_document_id = doc_entry
        before_extracted = int(stats["records_extracted"])
        before_promoted = int(stats["records_promoted"])
        try:
            _extract_stage_route_promote(
                doc=doc,
                raw_document_id=raw_document_id,
                run_id=run_id,
                source_name="open_web_search",
                entity_type="actor",
                extractor=PreExtractedActorExtractor(
                    candidate.record_preview or {}, sector_codes=candidate.sector_codes
                ),
                stage_store=stage_store,
                session=session,
                live=live,
                candidates=[],
                root=root,
                stats=stats,
                audit_rows=audit_rows,
                discovered_domain=domain,
                actor_resolver=actor_resolver,
            )
        finally:
            domain_store.add_counts(
                domain,
                records_extracted=int(stats["records_extracted"]) - before_extracted,
                records_promoted=int(stats["records_promoted"]) - before_promoted,
            )
        final_by_id[candidate.candidate_id] = candidate

    final = [final_by_id[candidate.candidate_id] for candidate in final]
    _attach_actor_band_stats(stats, final, config=config)
    if stats["fetch_failures"]:
        attention_reasons.append(
            f"open-web actor fetch/rubric failures: {stats['fetch_failures']} page(s)"
        )
    return ActorFetchOutcome(attention_reasons=attention_reasons, candidates=final)


def fetch_extract_stage_events(
    *,
    run_id: str,
    candidates: list[CandidateRecord],
    config: dict[str, object],
    root: Path,
    session,
    live: bool,
    run_log,
    cost_meter,
    stats: dict[str, object],
    audit_rows: list[dict[str, object]],
    source=None,
    extractor=None,
    raw_store=None,
    stage_store=None,
    domain_store=None,
    event_candidates=None,
    person_candidates=None,
    actor_resolver=None,
    run_date: date | None = None,
    person_create_preview: bool = False,
    _entity_type: str = "event",
) -> list[str]:
    if _entity_type not in {"event", "person"}:
        raise ValueError("open-web Phase 2 supports only event or person")
    if _entity_type == "person" and not bool(config.get("people_enabled", False)):
        raise RuntimeError(
            "open-web person fetch is disabled pending TARGETING_POLICY.md section 6 approval"
        )
    if person_create_preview and live:
        raise RuntimeError("person create preview cannot be combined with live writes")
    source = source or OpenWebEventSource(config)
    if extractor is None and _entity_type == "event":
        extractor = EventExtractor(
            _extraction_client(config, cost_meter),
            max_tokens=int(config.get("extraction_max_tokens", 2048)),
            untrusted_content=True,
            people_enabled=bool(config.get("people_enabled", False)),
        )
    elif extractor is None:
        extractor = PersonExtractor(
            _extraction_client(config, cost_meter),
            max_tokens=int(config.get("extraction_max_tokens", 2048)),
            people_enabled=True,
        )
    raw_store = raw_store or RawContentStore.from_config(root, config)
    stage_store = stage_store or (
        InMemoryStageStore() if session is None else SQLStageStore(session)
    )
    domain_store = domain_store or (
        InMemoryDiscoveredDomainStore() if session is None else SQLDiscoveredDomainStore(session)
    )
    if _entity_type == "event":
        canonical_candidates = (
            list(event_candidates)
            if event_candidates is not None
            else ([] if session is None else load_event_candidates(session))
        )
    else:
        canonical_candidates = (
            list(person_candidates)
            if person_candidates is not None
            else ([] if session is None else load_person_candidates(session))
        )

    plan = _plan_fetches(
        candidates,
        entity_type=_entity_type,
        domain_store=domain_store,
        config=config,
    )
    stats["fetch_candidates"] = plan.eligible_pages
    stats["pages_selected"] = len(plan.candidates)
    stats["new_domains_eligible"] = plan.eligible_new_domains
    stats["blocked_domains_skipped"] = plan.blocked_domains_skipped
    attention_reasons: list[str] = []
    if plan.page_cap_hit:
        attention_reasons.append(
            f"max_pages_fetched cap hit: {plan.eligible_pages} eligible, "
            f"{int(config.get('max_pages_fetched', 30))} selected"
        )
    if plan.domain_cap_hit:
        attention_reasons.append(
            f"max_new_domains cap hit: {plan.eligible_new_domains} eligible, "
            f"{int(config.get('max_new_domains', 10))} selected"
        )
    if (plan.eligible_pages or plan.blocked_domains_skipped) and not plan.candidates:
        logger.warning(
            "open-web Phase 2 had %d eligible page(s) but selected zero; blocked=%d",
            plan.eligible_pages,
            plan.blocked_domains_skipped,
        )

    for candidate in plan.candidates:
        candidate_domain = candidate.domain or normalized_domain(candidate.url)
        domain_store.touch(candidate_domain)
        try:
            doc = source.fetch(candidate.url)
            final_domain = normalized_domain(doc.url)
            if not final_domain:
                raise RuntimeError(f"fetched open-web page has invalid final URL {doc.url!r}")
            if final_domain != candidate_domain:
                raise RuntimeError(
                    "open-web candidate redirected across domains after admission: "
                    f"{candidate_domain!r} to {final_domain!r}"
                )
            domain_store.touch(final_domain)
            stats["pages_fetched"] += 1
            domain_store.add_counts(final_domain, pages_fetched=1)
            prior_raw = run_log.find_raw_document(url=doc.url, content_hash=doc.content_hash)
            storage_path = _storage_path_for_doc(
                raw_store, run_id=run_id, doc=doc, prior_raw=prior_raw
            )
            raw_document_id = run_log.write_raw_document(
                run_id=run_id, doc=doc, storage_path=storage_path
            )
            if prior_raw is not None:
                stats["skipped_unchanged"] += 1
                audit_rows.append(
                    _skip_audit_row(run_id, "open_web_search", _entity_type, doc)
                )
                continue

            before_extracted = int(stats["records_extracted"])
            before_promoted = int(stats["records_promoted"])
            try:
                _extract_stage_route_promote(
                    doc=doc,
                    raw_document_id=raw_document_id,
                    run_id=run_id,
                    source_name="open_web_search",
                    entity_type=_entity_type,
                    extractor=extractor,
                    stage_store=stage_store,
                    session=session,
                    live=live,
                    candidates=canonical_candidates,
                    root=root,
                    stats=stats,
                    audit_rows=audit_rows,
                    discovered_domain=final_domain,
                    qualification_config=dict(config.get("event_qualification", {})),
                    people_enabled=bool(config.get("people_enabled", False)),
                    person_create_preview=person_create_preview,
                    run_date=run_date or datetime.now(UTC).date(),
                    actor_resolver=actor_resolver,
                )
            finally:
                domain_store.add_counts(
                    final_domain,
                    records_extracted=int(stats["records_extracted"]) - before_extracted,
                    records_promoted=int(stats["records_promoted"]) - before_promoted,
                )
            cost_meter.enforce()
        except CostLimitExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - one untrusted page must not hide other outcomes.
            logger.warning("open-web fetch/extract failed for %s: %s", candidate.url, exc)
            stats["fetch_failures"] += 1
            audit_rows.append(
                {
                    "run_id": run_id,
                    "source": "open_web_search",
                    "entity_type": _entity_type,
                    "source_url": candidate.url,
                    "content_hash": "",
                    "natural_key": "",
                    "zone": "",
                    "score": candidate.fit_score,
                    "target_entity_id": "",
                    "candidate_ids": [],
                    "status": "fetch_or_extract_failed",
                    "error": str(exc),
                }
            )

    if stats["fetch_failures"]:
        attention_reasons.append(
            f"open-web fetch/extract failures: {stats['fetch_failures']} page(s)"
        )
    return attention_reasons


def fetch_extract_stage_people(**kwargs) -> list[str]:
    """Run accepted expertise or bounded-capture pages through person ingest."""
    return fetch_extract_stage_events(_entity_type="person", **kwargs)


def _cap_attention_reasons(plan: FetchPlan, config: dict[str, object]) -> list[str]:
    reasons: list[str] = []
    if plan.page_cap_hit:
        reasons.append(
            f"max_pages_fetched cap hit: {plan.eligible_pages} eligible, "
            f"{int(config.get('max_pages_fetched', 30))} selected"
        )
    if plan.domain_cap_hit:
        reasons.append(
            f"max_new_domains cap hit: {plan.eligible_new_domains} eligible, "
            f"{int(config.get('max_new_domains', 10))} selected"
        )
    return reasons


def _attach_actor_band_stats(
    stats: dict[str, object], candidates: list[CandidateRecord], *, config: dict[str, object]
) -> None:
    scored = [candidate for candidate in candidates if candidate.rubric is not None]
    auto_low, auto_high = actor_score_thresholds(config)
    stats["actor_score_auto_low"] = auto_low
    stats["actor_score_auto_high"] = auto_high
    stats["actor_scored"] = len(scored)
    for band in ("auto_high", "review", "auto_low"):
        count = sum(candidate.score_band == band for candidate in scored)
        stats[f"actor_band_{band}"] = count
        stats[f"actor_band_{band}_proportion"] = count / len(scored) if scored else 0.0


def _extraction_client(config: dict[str, object], cost_meter):
    from agents.common.llm import ClaudeToolClient

    pricing = dict(config.get("extraction_llm_pricing") or config.get("triage_llm_pricing", {}))
    return ClaudeToolClient(
        str(config.get("extraction_model") or config.get("triage_model", "claude-sonnet-5")),
        cost_meter=cost_meter,
        input_usd_per_million=float(pricing.get("input_usd_per_million", 0.0)),
        output_usd_per_million=float(pricing.get("output_usd_per_million", 0.0)),
    )


def _positive_cap(config: dict[str, object], key: str, default: int) -> int:
    value = int(config.get(key, default))
    if value <= 0:
        raise RuntimeError(f"open_web_discovery.{key} must be positive")
    return value
