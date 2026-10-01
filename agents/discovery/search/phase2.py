"""Bounded fetch and ingest for accepted open-web event candidates."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import text

from agents.common.cost import CostLimitExceeded
from agents.common.llm import llm_usage_delta, llm_usage_snapshot
from agents.common.raw_storage import RawContentStore
from agents.common.resolve_route import (
    RouteDecision,
    load_event_candidates,
    load_person_affiliation_candidates,
    load_person_candidates,
    route_person,
)
from agents.discovery.event_qualification import qualify_event
from agents.discovery.extractors.actor import ActorRecordValidationError
from agents.discovery.extractors.event import EventExtractor, EventRecordValidationError
from agents.discovery.extractors.person import PersonExtractor
from agents.discovery.normalize import event_natural_key, parse_date_to_iso
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
from agents.discovery.search.event_scoring import (
    PROMPT_VERSION as EVENT_ANALYSIS_VERSION,
)
from agents.discovery.search.event_scoring import (
    EventListwiseReranker,
    EventPageAnalysis,
    EventRubricExtractor,
    PreExtractedEventExtractor,
    event_score_band,
    event_score_thresholds,
    legacy_event_analysis,
    rerank_top_event_candidates,
    score_event_rubric,
)
from agents.discovery.search.event_scoring import (
    read_analysis_cache as read_event_analysis_cache,
)
from agents.discovery.search.event_scoring import (
    write_analysis_cache as write_event_analysis_cache,
)
from agents.discovery.search.models import CandidateRecord
from agents.discovery.search.person_scoring import (
    PROMPT_VERSION as PERSON_ANALYSIS_VERSION,
)
from agents.discovery.search.person_scoring import (
    PersonListwiseReranker,
    PersonPageAnalysis,
    PersonRubricExtractor,
    PreExtractedPersonExtractor,
    legacy_person_analysis,
    person_score_band,
    person_score_thresholds,
    rerank_top_person_candidates,
    score_person_rubric,
)
from agents.discovery.search.person_scoring import (
    read_analysis_cache as read_person_analysis_cache,
)
from agents.discovery.search.person_scoring import (
    write_analysis_cache as write_person_analysis_cache,
)
from agents.discovery.search.triage import (
    existing_actor_count_for_candidate,
    normalized_domain,
    registrable_domain,
)
from agents.discovery.sources.base import FetchedDoc
from agents.discovery.sources.http_utils import RobotsAwareHttp
from agents.discovery.stage import InMemoryStageStore, SQLStageStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchPlan:
    candidates: list[CandidateRecord]
    backfill_candidates: list[CandidateRecord]
    eligible_pages: int
    eligible_new_domains: int
    page_cap_hit: bool
    domain_cap_hit: bool
    blocked_domains_skipped: int
    duplicates_collapsed: int = 0
    duplicate_of: dict[str, str] | None = None


@dataclass(frozen=True)
class ScoredFetchOutcome:
    attention_reasons: list[str]
    candidates: list[CandidateRecord]


ActorFetchOutcome = ScoredFetchOutcome
EventFetchOutcome = ScoredFetchOutcome
PersonFetchOutcome = ScoredFetchOutcome


class _DeterministicReranker:
    """Test/injected-extractor fallback that preserves rubric ordering."""

    def rerank_group(self, candidates: list[CandidateRecord]) -> list[tuple[str, str]]:
        return [
            (candidate.url, "deterministic rubric order retained for injected extractor")
            for candidate in candidates
        ]


class _NoParticipantExtractor:
    def extract(self, _doc: FetchedDoc) -> list[dict[str, object]]:
        return []


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
    collapsed, duplicate_of = _collapse_candidates_by_registrable_domain(candidates)
    plan = _plan_fetches(
        collapsed,
        entity_type="event",
        domain_store=domain_store,
        config=config,
        require_fit_score=False,
    )
    return replace(
        plan,
        duplicates_collapsed=len(duplicate_of),
        duplicate_of=duplicate_of,
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
        require_fit_score=False,
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
    backfill: list[CandidateRecord] = []
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
        if len(selected) >= max_pages:
            page_cap_hit = True
            backfill.append(candidate)
            continue
        if status is None and domain not in selected_new_domains:
            if len(selected_new_domains) >= max_new_domains:
                domain_cap_hit = True
                backfill.append(candidate)
                continue
            selected_new_domains.add(domain)
        selected.append(candidate)

    return FetchPlan(
        candidates=selected,
        backfill_candidates=backfill,
        eligible_pages=len(eligible) - blocked_domains_skipped,
        eligible_new_domains=len(eligible_new_domains),
        page_cap_hit=page_cap_hit,
        domain_cap_hit=domain_cap_hit,
        blocked_domains_skipped=blocked_domains_skipped,
    )


def _collapse_candidates_by_registrable_domain(
    candidates: list[CandidateRecord],
) -> tuple[list[CandidateRecord], dict[str, str]]:
    survivors: list[CandidateRecord] = []
    positions: dict[str, int] = {}
    duplicate_of: dict[str, str] = {}
    for candidate in candidates:
        if candidate.entity_type != "event" or candidate.triage_verdict != "accepted":
            survivors.append(candidate)
            continue
        domain = registrable_domain(candidate.domain or candidate.url)
        if not domain or domain not in positions:
            positions[domain] = len(survivors)
            survivors.append(candidate)
            continue
        index = positions[domain]
        current = survivors[index]
        current_score = -1.0 if current.fit_score is None else current.fit_score
        candidate_score = -1.0 if candidate.fit_score is None else candidate.fit_score
        if candidate_score > current_score:
            survivors[index] = candidate
            duplicate_of[current.candidate_id] = candidate.candidate_id
            for duplicate_id, survivor_id in list(duplicate_of.items()):
                if survivor_id == current.candidate_id:
                    duplicate_of[duplicate_id] = candidate.candidate_id
        else:
            duplicate_of[candidate.candidate_id] = current.candidate_id
    return survivors, duplicate_of


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
        content_max_chars=int(config.get("actor_rubric_content_max_chars", 8000)),
        classification_enabled=True,
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
    stats["pages_selected"] = 0
    stats["new_domains_eligible"] = plan.eligible_new_domains
    stats["blocked_domains_skipped"] = plan.blocked_domains_skipped
    attention_reasons = _cap_attention_reasons(plan, config)
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    docs: dict[str, tuple[FetchedDoc, str, str]] = {}
    rubric_usage_client = getattr(rubric_extractor, "llm_client", None)
    rubric_usage_before = llm_usage_snapshot(rubric_usage_client)
    _attach_prompt_cache_stats(
        stats,
        prefix="actor_rubric",
        before=rubric_usage_before,
        client=rubric_usage_client,
    )
    _attach_actor_content_stats(stats, rubric_extractor, config=config)

    analysis_page_budget = _positive_cap(config, "max_pages_fetched", 30)
    loaded_pages = 0
    attempted_pages = 0
    primary_ids = {candidate.candidate_id for candidate in plan.candidates}
    for candidate in [*plan.candidates, *plan.backfill_candidates]:
        if loaded_pages >= analysis_page_budget:
            break
        attempted_pages += 1
        candidate_domain = candidate.domain or normalized_domain(candidate.url)
        domain_store.touch(candidate_domain)
        page_fetched = False
        try:
            doc = source.fetch(candidate.url)
            page_fetched = True
            loaded_pages += 1
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
        except ActorRecordValidationError as exc:
            logger.warning("open-web actor record validation failed for %s: %s", candidate.url, exc)
            stats["actor_record_validation_failures"] = int(
                stats.get("actor_record_validation_failures", 0) or 0
            ) + 1
            by_id[candidate.candidate_id] = replace(
                candidate,
                page_fetched=page_fetched,
                triage_verdict="analysis_failed",
                triage_reason=f"actor record validation failed: {exc}",
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
                    "status": "record_validation_failed",
                    "error": str(exc),
                }
            )
        except Exception as exc:  # noqa: BLE001 - one untrusted page must not stop the batch.
            logger.warning("open-web actor fetch/rubric failed for %s: %s", candidate.url, exc)
            stats["fetch_failures"] += 1
            _record_fetch_failure(stats, exc)
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
        finally:
            _attach_prompt_cache_stats(
                stats,
                prefix="actor_rubric",
                before=rubric_usage_before,
                client=rubric_usage_client,
            )
            _attach_actor_content_stats(stats, rubric_extractor, config=config)

    stats["pages_selected"] = attempted_pages
    stats["fetch_backfill_attempts"] = sum(
        1
        for candidate in [*plan.candidates, *plan.backfill_candidates][:attempted_pages]
        if candidate.candidate_id not in primary_ids
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
    validation_failures = int(stats.get("actor_record_validation_failures", 0) or 0)
    if validation_failures:
        attention_reasons.append(
            f"open-web actor record validation failures: {validation_failures} page(s)"
        )
    return ActorFetchOutcome(attention_reasons=attention_reasons, candidates=final)


def fetch_score_stage_events(
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
    sector_codes: list[str],
    hub_names: list[str],
    source=None,
    rubric_extractor=None,
    reranker=None,
    participant_extractor=None,
    raw_store=None,
    stage_store=None,
    domain_store=None,
    event_candidates=None,
    actor_resolver=None,
    run_date: date | None = None,
) -> EventFetchOutcome:
    """Fetch gated events, score page evidence, then route by score and qualification."""
    if not sector_codes:
        raise RuntimeError("event rubric pipeline requires seeded sector codes")
    current_date = run_date or datetime.now(UTC).date()
    source = source or OpenWebEventSource(config)
    injected_extractor = rubric_extractor is not None
    shared_client = None if injected_extractor else _extraction_client(config, cost_meter)
    rubric_extractor = rubric_extractor or EventRubricExtractor(
        shared_client,
        max_tokens=int(config.get("event_rubric_max_tokens", 4096)),
    )
    if reranker is None:
        reranker = (
            _DeterministicReranker()
            if injected_extractor
            else EventListwiseReranker(
                shared_client,
                max_tokens=int(config.get("event_rerank_max_tokens", 2048)),
            )
        )
    if participant_extractor is None:
        participant_extractor = (
            _NoParticipantExtractor()
            if injected_extractor
            else EventExtractor(
                shared_client,
                max_tokens=int(config.get("extraction_max_tokens", 2048)),
                untrusted_content=True,
                people_enabled=bool(config.get("people_enabled", False)),
            )
        )
    raw_store = raw_store or RawContentStore.from_config(root, config)
    stage_store = stage_store or (
        InMemoryStageStore() if session is None else SQLStageStore(session)
    )
    domain_store = domain_store or (
        InMemoryDiscoveredDomainStore() if session is None else SQLDiscoveredDomainStore(session)
    )
    canonical_candidates = (
        list(event_candidates)
        if event_candidates is not None
        else ([] if session is None else load_event_candidates(session))
    )
    plan = plan_event_fetches(candidates, domain_store=domain_store, config=config)
    stats["fetch_candidates"] = plan.eligible_pages
    stats["pages_selected"] = len(plan.candidates)
    stats["event_domain_duplicates_collapsed"] = plan.duplicates_collapsed
    stats["new_domains_eligible"] = plan.eligible_new_domains
    stats["blocked_domains_skipped"] = plan.blocked_domains_skipped
    attention_reasons = _cap_attention_reasons(plan, config)
    duplicate_of = plan.duplicate_of or {}
    by_id = {
        candidate.candidate_id: (
            replace(
                candidate,
                triage_verdict="duplicate",
                triage_reason="event candidate collapsed by registrable domain before fetch",
                duplicate_of=duplicate_of[candidate.candidate_id],
                score_band="duplicate",
            )
            if candidate.candidate_id in duplicate_of
            else candidate
        )
        for candidate in candidates
    }
    docs: dict[
        str,
        tuple[FetchedDoc, str, str, list[dict[str, object]], list[dict[str, object]], bool],
    ] = {}

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
                / "event_analysis"
                / f"{doc.content_hash}.{EVENT_ANALYSIS_VERSION}.json"
            )
            analysis = read_event_analysis_cache(
                cache_path,
                sector_codes=sector_codes,
                run_date=current_date,
            )
            participant_actors: list[dict[str, object]] = []
            participant_people: list[dict[str, object]] = []
            unchanged = prior_raw is not None
            if unchanged:
                stats["skipped_unchanged"] += 1
                audit_rows.append(
                    _skip_audit_row(run_id, "open_web_search", "event", doc)
                )
                if analysis is None:
                    reason = (
                        "unchanged event page has no rubric cache; use stored-page replay "
                        "to initialize the new scorer"
                    )
                    logger.warning("%s: %s", candidate.url, reason)
                    by_id[candidate.candidate_id] = replace(
                        candidate,
                        page_fetched=True,
                        triage_verdict="skipped_unchanged",
                        triage_reason=reason,
                    )
                    continue
            if analysis is None:
                extracted = (
                    rubric_extractor.extract(
                        doc,
                        sector_codes=sector_codes,
                        hub_names=hub_names,
                        run_date=current_date,
                    )
                    if isinstance(rubric_extractor, EventRubricExtractor)
                    else rubric_extractor.extract(doc)
                )
                if isinstance(extracted, EventPageAnalysis):
                    analysis = extracted
                elif isinstance(extracted, list):
                    if len(extracted) != 1 or not isinstance(extracted[0], dict):
                        raise RuntimeError(
                            "event gate page must extract exactly one event record"
                        )
                    raw_record = extracted[0]
                    analysis = legacy_event_analysis(
                        raw_record,
                        sector_codes=sector_codes,
                        run_date=current_date,
                    )
                    participant_actors = [
                        item
                        for item in list(raw_record.get("participant_actors") or [])
                        if isinstance(item, dict)
                    ]
                    participant_people = [
                        item
                        for item in list(raw_record.get("participant_people") or [])
                        if isinstance(item, dict)
                    ]
                else:
                    raise TypeError("event rubric extractor returned an unsupported result")
                write_event_analysis_cache(cache_path, analysis)
                stats["event_pages_analyzed"] = int(
                    stats.get("event_pages_analyzed", 0) or 0
                ) + 1
            score = score_event_rubric(analysis.rubric, config=config)
            qualification = qualify_event(
                {
                    **analysis.record,
                    "participant_actors": participant_actors,
                    "participant_people": participant_people,
                },
                run_date=current_date,
                config=dict(config.get("event_qualification", {})),
                rubric=analysis.rubric,
            )
            raw_band = event_score_band(score.total, config)
            by_id[candidate.candidate_id] = replace(
                candidate,
                page_fetched=True,
                fit_score=score.total,
                rubric=analysis.rubric,
                record_preview=analysis.record,
                score_breakdown=score.contributions,
                score_band=_qualification_capped_event_band(
                    raw_band,
                    qualification=qualification,
                    record=analysis.record,
                    run_date=current_date,
                ),
                sector_codes=tuple(analysis.record.get("sector_codes") or []),
                qualification_paths=qualification.paths,
            )
            docs[candidate.candidate_id] = (
                doc,
                final_domain,
                raw_document_id,
                participant_actors,
                participant_people,
                unchanged,
            )
            cost_meter.enforce()
        except CostLimitExceeded:
            raise
        except EventRecordValidationError as exc:
            logger.warning("open-web event record validation failed for %s: %s", candidate.url, exc)
            stats["event_record_validation_failures"] = int(
                stats.get("event_record_validation_failures", 0) or 0
            ) + 1
            by_id[candidate.candidate_id] = replace(
                candidate,
                page_fetched=page_fetched,
                triage_verdict="analysis_failed",
                triage_reason=f"event record validation failed: {exc}",
                score_band="analysis_failed",
            )
            audit_rows.append(
                {
                    "run_id": run_id,
                    "source": "open_web_search",
                    "entity_type": "event",
                    "source_url": candidate.url,
                    "content_hash": "",
                    "natural_key": "",
                    "zone": "",
                    "score": "",
                    "target_entity_id": "",
                    "candidate_ids": [],
                    "status": "record_validation_failed",
                    "error": str(exc),
                }
            )
        except Exception as exc:  # noqa: BLE001 - one untrusted page must not stop the batch.
            logger.warning("open-web event fetch/rubric failed for %s: %s", candidate.url, exc)
            stats["fetch_failures"] += 1
            by_id[candidate.candidate_id] = replace(
                candidate,
                page_fetched=page_fetched,
                triage_verdict="analysis_failed",
                triage_reason=f"event fetch or rubric failed: {exc}",
                score_band="analysis_failed",
            )
            audit_rows.append(
                {
                    "run_id": run_id,
                    "source": "open_web_search",
                    "entity_type": "event",
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
    updated, event_duplicate_count = _collapse_extracted_event_duplicates(updated)
    stats["event_record_duplicates_collapsed"] = event_duplicate_count
    scored = [
        candidate
        for candidate in updated
        if candidate.rubric is not None and candidate.score_band != "duplicate"
    ]
    reranked, rerank_attention = rerank_top_event_candidates(
        scored,
        reranker=reranker,
        config=config,
    )
    attention_reasons.extend(rerank_attention)
    reranked_by_id = {candidate.candidate_id: candidate for candidate in reranked}
    updated = [reranked_by_id.get(candidate.candidate_id, candidate) for candidate in updated]

    final: list[CandidateRecord] = []
    for candidate in updated:
        if candidate.score_band == "duplicate":
            final.append(candidate)
            continue
        if candidate.rubric is None:
            final.append(candidate)
            continue
        band = candidate.score_band or event_score_band(float(candidate.fit_score or 0.0), config)
        verdict = "accepted" if band == "auto_high" else "rejected" if band == "auto_low" else "review"
        reason = f"event rubric score {float(candidate.fit_score or 0.0):.3f} -> {band}"
        record = candidate.record_preview or {}
        if band != "auto_low" and not record.get("title"):
            band = "auto_low"
            verdict = "rejected"
            reason = "event page did not yield a required title"
        elif (
            band == "auto_low"
            and not candidate.qualification_paths
            and _event_record_is_past(record, current_date)
        ):
            reason = (
                "event qualification capped rubric score at auto_low: past and not minable"
            )
        elif band == "review" and not candidate.qualification_paths:
            reason = (
                "event qualification capped rubric score at review: upcoming and neither "
                "attendable nor minable"
            )
        final.append(
            replace(
                candidate,
                triage_verdict=verdict,
                triage_reason=reason,
                score_band=band,
            )
        )

    routable = [
        candidate
        for candidate in final
        if candidate.score_band in {"auto_high", "review"}
    ]
    for candidate in routable:
        doc_entry = docs.get(candidate.candidate_id)
        if doc_entry is None:
            raise RuntimeError(
                f"routable event candidate has no fetched document: {candidate.url}"
            )
        doc, domain, raw_document_id, participant_actors, participant_people, unchanged = doc_entry
        if unchanged:
            continue
        if (
            candidate.score_band == "auto_high"
            and "minable" in candidate.qualification_paths
            and not participant_actors
            and not participant_people
        ):
            participant_records = participant_extractor.extract(doc)
            if participant_records:
                participant_record = participant_records[0]
                participant_actors = [
                    item
                    for item in list(participant_record.get("participant_actors") or [])
                    if isinstance(item, dict)
                ]
                participant_people = [
                    item
                    for item in list(participant_record.get("participant_people") or [])
                    if isinstance(item, dict)
                ]
            cost_meter.enforce()
        before_extracted = int(stats["records_extracted"])
        before_promoted = int(stats["records_promoted"])
        try:
            _extract_stage_route_promote(
                doc=doc,
                raw_document_id=raw_document_id,
                run_id=run_id,
                source_name="open_web_search",
                entity_type="event",
                extractor=PreExtractedEventExtractor(
                    candidate.record_preview or {},
                    participant_actors=participant_actors,
                    participant_people=participant_people,
                ),
                stage_store=stage_store,
                session=session,
                live=live,
                candidates=canonical_candidates,
                root=root,
                stats=stats,
                audit_rows=audit_rows,
                discovered_domain=domain,
                qualification_config=dict(config.get("event_qualification", {})),
                people_enabled=bool(config.get("people_enabled", False)),
                run_date=current_date,
                actor_resolver=actor_resolver,
                event_rubric=candidate.rubric,
                event_review_metadata=(
                    {
                        "review_kind": "rubric_band",
                        "search_candidate_id": candidate.candidate_id,
                        "rubric_score": candidate.fit_score,
                        "rubric": candidate.rubric,
                        "score_breakdown": candidate.score_breakdown,
                        "rerank_position": candidate.rerank_position,
                        "rerank_reason": candidate.rerank_reason,
                        "qualification_paths": list(candidate.qualification_paths),
                    }
                    if candidate.score_band == "review"
                    else None
                ),
            )
        finally:
            domain_store.add_counts(
                domain,
                records_extracted=int(stats["records_extracted"]) - before_extracted,
                records_promoted=int(stats["records_promoted"]) - before_promoted,
            )

    _attach_event_band_stats(stats, final, config=config)
    if stats["fetch_failures"]:
        attention_reasons.append(
            f"open-web event fetch/rubric failures: {stats['fetch_failures']} page(s)"
        )
    validation_failures = int(stats.get("event_record_validation_failures", 0) or 0)
    if validation_failures:
        attention_reasons.append(
            f"open-web event record validation failures: {validation_failures} page(s)"
        )
    return EventFetchOutcome(attention_reasons=attention_reasons, candidates=final)


def _qualification_capped_event_band(
    band: str,
    *,
    qualification,
    record: dict[str, object],
    run_date: date,
) -> str:
    start_date_value = record.get("start_date") or record.get("next_date")
    try:
        start_date_text = parse_date_to_iso(start_date_value)
    except ValueError:
        start_date_text = None
    start_date = date.fromisoformat(start_date_text) if start_date_text else None
    if start_date is not None and start_date < run_date and not qualification.minable:
        return "auto_low"
    if (
        start_date is not None
        and start_date >= run_date
        and not qualification.attendable
        and not qualification.minable
        and band == "auto_high"
    ):
        return "review"
    return band


def _event_record_is_past(record: dict[str, object], run_date: date) -> bool:
    value = record.get("start_date") or record.get("next_date")
    try:
        parsed = parse_date_to_iso(value)
    except ValueError:
        return False
    return bool(parsed and date.fromisoformat(parsed) < run_date)


def _collapse_extracted_event_duplicates(
    candidates: list[CandidateRecord],
) -> tuple[list[CandidateRecord], int]:
    groups: dict[str, list[tuple[int, CandidateRecord]]] = {}
    for index, candidate in enumerate(candidates):
        record = candidate.record_preview or {}
        title = str(record.get("title") or record.get("name") or "").strip()
        start_date = str(record.get("start_date") or record.get("next_date") or "").strip()
        if not title or not start_date or candidate.rubric is None:
            continue
        groups.setdefault(event_natural_key(title, start_date), []).append((index, candidate))

    updated = list(candidates)
    collapsed = 0
    for rows in groups.values():
        if len(rows) < 2:
            continue

        def survivor_rank(item: tuple[int, CandidateRecord]) -> tuple[int, float, int]:
            index, candidate = item
            record = candidate.record_preview or {}
            own_domain = registrable_domain(str(record.get("website") or ""))
            candidate_domain = registrable_domain(candidate.domain or candidate.url)
            score = -1.0 if candidate.fit_score is None else candidate.fit_score
            return (int(bool(own_domain and own_domain == candidate_domain)), score, -index)

        survivor_index, survivor = max(rows, key=survivor_rank)
        for index, candidate in rows:
            if index == survivor_index:
                continue
            updated[index] = replace(
                candidate,
                triage_verdict="duplicate",
                triage_reason="duplicate event name and start date after extraction",
                duplicate_of=survivor.candidate_id,
                score_band="duplicate",
            )
            collapsed += 1
    return updated, collapsed


def _record_fetch_failure(stats: dict[str, object], exc: Exception) -> None:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code is not None:
        key = f"fetch_failure_status_{int(status_code)}"
    else:
        key = f"fetch_failure_exception_{type(exc).__name__}"
    stats[key] = int(stats.get(key, 0) or 0) + 1


def fetch_score_stage_people(
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
    sector_codes: list[str],
    hub_names: list[str],
    source=None,
    rubric_extractor=None,
    reranker=None,
    raw_store=None,
    stage_store=None,
    domain_store=None,
    person_candidates=None,
    affiliation_candidates=None,
    actor_resolver=None,
) -> PersonFetchOutcome:
    """Fetch person profiles, score page evidence, then resolve identity in code."""
    if not bool(config.get("people_enabled", False)):
        raise RuntimeError(
            "open-web person fetch is disabled pending TARGETING_POLICY.md section 6 approval"
        )
    if not sector_codes:
        raise RuntimeError("person rubric pipeline requires seeded sector codes")
    source = source or OpenWebEventSource(config)
    injected_extractor = rubric_extractor is not None
    shared_client = None if injected_extractor else _extraction_client(config, cost_meter)
    rubric_extractor = rubric_extractor or PersonRubricExtractor(
        shared_client,
        max_tokens=int(config.get("person_rubric_max_tokens", 3072)),
    )
    if reranker is None:
        reranker = (
            _DeterministicReranker()
            if injected_extractor
            else PersonListwiseReranker(
                shared_client,
                max_tokens=int(config.get("person_rerank_max_tokens", 2048)),
            )
        )
    raw_store = raw_store or RawContentStore.from_config(root, config)
    stage_store = stage_store or (
        InMemoryStageStore() if session is None else SQLStageStore(session)
    )
    domain_store = domain_store or (
        InMemoryDiscoveredDomainStore() if session is None else SQLDiscoveredDomainStore(session)
    )
    canonical_candidates = (
        list(person_candidates)
        if person_candidates is not None
        else ([] if session is None else load_person_candidates(session))
    )
    canonical_affiliations = (
        list(affiliation_candidates)
        if affiliation_candidates is not None
        else ([] if session is None else load_person_affiliation_candidates(session))
    )
    if actor_resolver is None and session is not None:
        from agents.common.resolve_route import load_actor_resolver_class

        actor_resolver = load_actor_resolver_class()(session, project_root=root)
    held_actor_names = [
        str(candidate.get("affiliation") or candidate.get("name") or "").strip()
        for candidate in canonical_affiliations
        if str(candidate.get("affiliation") or candidate.get("name") or "").strip()
    ]
    plan = plan_person_fetches(candidates, domain_store=domain_store, config=config)
    stats["fetch_candidates"] = plan.eligible_pages
    stats["pages_selected"] = len(plan.candidates)
    stats["new_domains_eligible"] = plan.eligible_new_domains
    stats["blocked_domains_skipped"] = plan.blocked_domains_skipped
    attention_reasons = _cap_attention_reasons(plan, config)
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    docs: dict[str, tuple[FetchedDoc, str, str, bool]] = {}

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
                / "person_analysis"
                / f"{doc.content_hash}.{PERSON_ANALYSIS_VERSION}.json"
            )
            analysis = read_person_analysis_cache(
                cache_path,
                held_actor_names=held_actor_names,
            )
            unchanged = prior_raw is not None
            if unchanged:
                stats["skipped_unchanged"] += 1
                audit_rows.append(
                    _skip_audit_row(run_id, "open_web_search", "person", doc)
                )
                if analysis is None:
                    reason = (
                        "unchanged person page has no rubric cache; use stored-page replay "
                        "to initialize the new scorer"
                    )
                    logger.warning("%s: %s", candidate.url, reason)
                    by_id[candidate.candidate_id] = replace(
                        candidate,
                        page_fetched=True,
                        triage_verdict="skipped_unchanged",
                        triage_reason=reason,
                    )
                    continue
            if analysis is None:
                extracted = (
                    rubric_extractor.extract(
                        doc,
                        sector_codes=sector_codes,
                        hub_names=hub_names,
                        held_actor_names=held_actor_names,
                    )
                    if isinstance(rubric_extractor, PersonRubricExtractor)
                    else rubric_extractor.extract(doc)
                )
                if isinstance(extracted, PersonPageAnalysis):
                    analysis = extracted
                elif isinstance(extracted, list):
                    if len(extracted) != 1 or not isinstance(extracted[0], dict):
                        raise RuntimeError(
                            "person gate page must extract exactly one person record"
                        )
                    analysis = legacy_person_analysis(
                        extracted[0], held_actor_names=held_actor_names
                    )
                else:
                    raise TypeError("person rubric extractor returned an unsupported result")
                write_person_analysis_cache(cache_path, analysis)
                stats["person_pages_analyzed"] = int(
                    stats.get("person_pages_analyzed", 0) or 0
                ) + 1
            score = score_person_rubric(analysis.rubric, config=config)
            by_id[candidate.candidate_id] = replace(
                candidate,
                page_fetched=True,
                fit_score=score.total,
                rubric=analysis.rubric,
                record_preview=analysis.record,
                score_breakdown=score.contributions,
                score_band=person_score_band(score.total, config),
            )
            docs[candidate.candidate_id] = (
                doc,
                final_domain,
                raw_document_id,
                unchanged,
            )
            cost_meter.enforce()
        except CostLimitExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - one untrusted page must not stop the batch.
            logger.warning("open-web person fetch/rubric failed for %s: %s", candidate.url, exc)
            stats["fetch_failures"] += 1
            by_id[candidate.candidate_id] = replace(
                candidate,
                page_fetched=page_fetched,
                triage_verdict="analysis_failed",
                triage_reason=f"person fetch or rubric failed: {exc}",
                score_band="analysis_failed",
            )
            audit_rows.append(
                {
                    "run_id": run_id,
                    "source": "open_web_search",
                    "entity_type": "person",
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
    reranked, rerank_attention = rerank_top_person_candidates(
        scored,
        reranker=reranker,
        config=config,
    )
    attention_reasons.extend(rerank_attention)
    reranked_by_id = {candidate.candidate_id: candidate for candidate in reranked}
    updated = [reranked_by_id.get(candidate.candidate_id, candidate) for candidate in updated]

    routes: dict[str, RouteDecision] = {}
    final: list[CandidateRecord] = []
    for candidate in updated:
        if candidate.rubric is None:
            final.append(candidate)
            continue
        band = candidate.score_band or person_score_band(
            float(candidate.fit_score or 0.0), config
        )
        verdict = (
            "accepted"
            if band == "auto_high"
            else "rejected"
            if band == "auto_low"
            else "review"
        )
        reason = f"person rubric score {float(candidate.fit_score or 0.0):.3f} -> {band}"
        record = candidate.record_preview or {}
        identity_outcome = None
        route = None
        if band != "auto_low" and not record.get("name"):
            band = "auto_low"
            verdict = "rejected"
            reason = "person page did not yield a required name"
        elif band == "review":
            identity_outcome = "not_evaluated"
            route = RouteDecision(
                zone="review",
                score=float(candidate.fit_score or 0.0),
                metadata={
                    "review_kind": "rubric_band",
                    "identity_outcome": identity_outcome,
                    "identity_reason": "relevance score is in the review band",
                },
            )
        elif band == "auto_high":
            identity_route = route_person(
                record,
                canonical_candidates,
                allow_create=True,
                affiliation_candidates=canonical_affiliations,
                actor_resolver=actor_resolver,
            )
            identity_outcome = str(
                dict(identity_route.metadata or {}).get("identity_outcome") or "review"
            )
            route = replace(
                identity_route,
                score=float(candidate.fit_score or 0.0),
            )
        if route is not None:
            route = replace(
                route,
                metadata={
                    **dict(route.metadata or {}),
                    "score_band": band,
                    "rubric": candidate.rubric,
                    "score_breakdown": candidate.score_breakdown,
                    "rerank_position": candidate.rerank_position,
                    "rerank_reason": candidate.rerank_reason,
                },
            )
            routes[candidate.candidate_id] = route
        final.append(
            replace(
                candidate,
                triage_verdict=verdict,
                triage_reason=reason,
                score_band=band,
                identity_outcome=identity_outcome,
            )
        )

    routable = [
        candidate
        for candidate in final
        if candidate.score_band in {"auto_high", "review"}
    ]
    for candidate in routable:
        doc_entry = docs.get(candidate.candidate_id)
        route = routes.get(candidate.candidate_id)
        if doc_entry is None or route is None:
            raise RuntimeError(
                f"routable person candidate is missing document or route: {candidate.url}"
            )
        doc, domain, raw_document_id, unchanged = doc_entry
        if unchanged:
            continue
        before_extracted = int(stats["records_extracted"])
        before_promoted = int(stats["records_promoted"])
        try:
            _extract_stage_route_promote(
                doc=doc,
                raw_document_id=raw_document_id,
                run_id=run_id,
                source_name="open_web_search",
                entity_type="person",
                extractor=PreExtractedPersonExtractor(candidate.record_preview or {}),
                stage_store=stage_store,
                session=session,
                live=live,
                candidates=canonical_candidates,
                root=root,
                stats=stats,
                audit_rows=audit_rows,
                discovered_domain=domain,
                people_enabled=True,
                person_affiliation_candidates=canonical_affiliations,
                actor_resolver=actor_resolver,
                person_review_metadata={
                    "review_kind": "rubric_band"
                    if candidate.score_band == "review"
                    else "identity",
                    "rubric_score": candidate.fit_score,
                    "rubric": candidate.rubric,
                    "score_breakdown": candidate.score_breakdown,
                    "rerank_position": candidate.rerank_position,
                    "rerank_reason": candidate.rerank_reason,
                    "score_band": candidate.score_band,
                    "identity_outcome": candidate.identity_outcome,
                },
            )
        finally:
            domain_store.add_counts(
                domain,
                records_extracted=int(stats["records_extracted"]) - before_extracted,
                records_promoted=int(stats["records_promoted"]) - before_promoted,
            )

    _attach_person_band_stats(stats, final, config=config)
    if stats["fetch_failures"]:
        attention_reasons.append(
            f"open-web person fetch/rubric failures: {stats['fetch_failures']} page(s)"
        )
    return PersonFetchOutcome(attention_reasons=attention_reasons, candidates=final)


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


def _attach_event_band_stats(
    stats: dict[str, object], candidates: list[CandidateRecord], *, config: dict[str, object]
) -> None:
    scored = [
        candidate
        for candidate in candidates
        if candidate.rubric is not None and candidate.score_band != "duplicate"
    ]
    auto_low, auto_high = event_score_thresholds(config)
    stats["event_score_auto_low"] = auto_low
    stats["event_score_auto_high"] = auto_high
    stats["event_scored"] = len(scored)
    for band in ("auto_high", "review", "auto_low"):
        count = sum(candidate.score_band == band for candidate in scored)
        stats[f"event_band_{band}"] = count
        stats[f"event_band_{band}_proportion"] = count / len(scored) if scored else 0.0
    for path in ("attendable", "minable"):
        count = sum(path in candidate.qualification_paths for candidate in scored)
        stats[f"event_qualification_{path}"] = count
        stats[f"event_qualification_{path}_proportion"] = (
            count / len(scored) if scored else 0.0
        )


def _attach_person_band_stats(
    stats: dict[str, object], candidates: list[CandidateRecord], *, config: dict[str, object]
) -> None:
    scored = [candidate for candidate in candidates if candidate.rubric is not None]
    auto_low, auto_high = person_score_thresholds(config)
    stats["person_score_auto_low"] = auto_low
    stats["person_score_auto_high"] = auto_high
    stats["person_scored"] = len(scored)
    for band in ("auto_high", "review", "auto_low"):
        count = sum(candidate.score_band == band for candidate in scored)
        stats[f"person_band_{band}"] = count
        stats[f"person_band_{band}_proportion"] = count / len(scored) if scored else 0.0
    for outcome in sorted(
        {
            candidate.identity_outcome
            for candidate in scored
            if candidate.identity_outcome
        }
    ):
        stats[f"person_identity_{outcome}"] = sum(
            candidate.identity_outcome == outcome for candidate in scored
        )


def _extraction_client(config: dict[str, object], cost_meter):
    from agents.common.llm import ClaudeToolClient

    pricing = dict(config.get("extraction_llm_pricing") or config.get("triage_llm_pricing", {}))
    return ClaudeToolClient(
        str(config.get("extraction_model") or config.get("triage_model", "claude-sonnet-5")),
        cost_meter=cost_meter,
        input_usd_per_million=float(pricing.get("input_usd_per_million", 0.0)),
        output_usd_per_million=float(pricing.get("output_usd_per_million", 0.0)),
    )


def _attach_prompt_cache_stats(
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


def _attach_actor_content_stats(
    stats: dict[str, object],
    extractor,
    *,
    config: dict[str, object],
) -> None:
    stats["actor_rubric_content_max_chars"] = int(
        getattr(
            extractor,
            "content_max_chars",
            config.get("actor_rubric_content_max_chars", 8000),
        )
    )
    stats["actor_rubric_pages_prepared"] = int(
        getattr(extractor, "pages_prepared", 0) or 0
    )
    stats["actor_rubric_pages_truncated"] = int(
        getattr(extractor, "pages_truncated", 0) or 0
    )
    stats["actor_rubric_source_chars"] = int(
        getattr(extractor, "source_chars_total", 0) or 0
    )
    stats["actor_rubric_cleaned_chars"] = int(
        getattr(extractor, "cleaned_chars_total", 0) or 0
    )
    stats["actor_rubric_sent_chars"] = int(
        getattr(extractor, "sent_chars_total", 0) or 0
    )


def _positive_cap(config: dict[str, object], key: str, default: int) -> int:
    value = int(config.get(key, default))
    if value <= 0:
        raise RuntimeError(f"open_web_discovery.{key} must be positive")
    return value
