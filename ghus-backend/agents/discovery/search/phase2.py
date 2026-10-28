"""Bounded fetch and ingest for accepted open-web event candidates."""

from __future__ import annotations

import hashlib
import logging
import os
import re
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
from agents.discovery.page_facts import page_text, reading_text
from agents.discovery.quality_gates import (
    OFFICIAL_EVENT_PAGES,
    cap_band,
    event_gate,
    held_event_match,
    person_gate,
    same_event,
)
from agents.discovery.run import (
    _extract_stage_route_promote,
    _skip_audit_row,
    _storage_path_for_doc,
)
from agents.discovery.search.actor_currency import assess_currency, site_moved
from agents.discovery.search.actor_official import (
    HARVESTABLE_REASON,
    harvest_leads,
    homepage,
    official_bundle,
    site_is_official,
    website_from_source,
)
from agents.discovery.search.actor_quality import (
    assess_actor,
    quality_config,
)
from agents.discovery.search.actor_scoring import (
    PROMPT_VERSION as ACTOR_ANALYSIS_VERSION,
)
from agents.discovery.search.actor_scoring import (
    ActorListwiseReranker,
    ActorPageAnalysis,
    ActorRubricExtractor,
    PreExtractedActorExtractor,
    actor_score_band,
    actor_score_thresholds,
    needs_classification,
    prepare_actor_rubric_content,
    read_analysis_cache,
    rerank_top_actor_candidates,
    rubric_hub_matches,
    rubric_sector_codes,
    score_actor_rubric,
    write_analysis_cache,
)
from agents.discovery.search.discovery_request import (
    apply_new_actor_cap,
    event_outside_request,
    person_outside_request,
)
from agents.discovery.search.followup import (
    FollowupBudget,
    event_followup_urls,
    merge_event_reads,
    pending_review_events,
    pending_review_people,
    person_followup_urls,
    person_key,
    same_person,
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
from agents.discovery.search.models import CandidateRecord, SearchResult
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


# The rubric criteria that say something about THIS organisation, strongest
# first. "Why it matched" should name what the actor does that makes it belong
# here, not restate how the crawler reached the page.
_MATCH_EVIDENCE_PRIORITY = (
    "use_cases",
    "research_development_or_programmes",
    "sector_coverage",
    "partnerships_or_tech_transfer",
    "open_programmes",
    "distinctiveness",
    "partnership_precedent",
    "network_membership",
    "real_operating_entity",
)


def _match_evidence(rubric: dict[str, object] | None) -> str | None:
    """The best piece of page evidence about the actor, as the rubric recorded it."""
    if not isinstance(rubric, dict):
        return None
    for key in _MATCH_EVIDENCE_PRIORITY:
        item = rubric.get(key)
        if not isinstance(item, dict) or item.get("present") is not True:
            continue
        evidence = str(item.get("evidence") or "").strip()
        if len(evidence) < 20:            # a fragment explains nothing
            continue
        if not evidence.endswith((".", "!", "?")):
            evidence += "."
        return evidence
    return None


# Gates an official-site read can clear: the page was not the organisation's
# own, or did not say enough about it.
_FIXABLE_BY_OFFICIAL_PAGE = frozenset({
    "third_party_page", "website_unverified", "weak_description",
    "thin_evidence", "entity_unconfirmed", "no_substantive_work",
})
# Rejections not worth mining for names: already read, already mapped, blocked.
_NOT_A_LEAD_SOURCE = ("already in raw_document", "actor already in database", "blocked domain")


def _name_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(name or "").casefold()).strip()


def _official_candidate(original, *, run_id, url, name, reason, source_url=None):
    """A candidate for reading an organisation's own site (homepage + About)."""
    home = homepage(url) or url
    query = original.query if original is not None else f"lead from {source_url}"
    return CandidateRecord.from_result(
        run_id=run_id,
        entity_type="actor",
        result=SearchResult(url=home, title=name, snippet=reason,
                            provider="official_site", query=query),
        domain=normalized_domain(home),
        triage_verdict="accepted",
        triage_reason=reason,
        fit_score=None,
    )


def _resolve_lead_websites(leads, source, *, limit: int, stats) -> list:
    """Fill a missing website from the link in the article that named the lead."""
    pages: dict[str, FetchedDoc | None] = {}
    resolved = []
    for lead in leads:
        if lead.website or not lead.source_url:
            resolved.append(lead)
            continue
        if lead.source_url not in pages and len(pages) < limit:
            try:
                pages[lead.source_url] = source.fetch(lead.source_url)
            except Exception:  # noqa: BLE001 - an unreachable article just yields nothing
                pages[lead.source_url] = None
        page = pages.get(lead.source_url)
        website = website_from_source(page, lead.name) if page is not None else None
        if website:
            stats["actor_lead_websites_resolved"] = int(
                stats.get("actor_lead_websites_resolved", 0) or 0) + 1
            lead = replace(lead, website=website)
        resolved.append(lead)
    return resolved


def _lead_sources(candidates, actor_context, limit: int = 120) -> list[dict]:
    """Rejected results that are ABOUT organisations: news, lists, documents."""
    rows = []
    for candidate in candidates:
        reason = str(candidate.triage_reason or "")
        record = candidate.record_preview or {}
        name = str(record.get("name") or "").strip()
        if (candidate.rubric is not None and candidate.score_band == "auto_low" and name
                and registrable_domain(candidate.url)
                != registrable_domain(str(record.get("website") or ""))):
            # Read and scored low, but on someone else's site (a ProPublica or
            # registry profile): the organisation it names may be strong on its
            # own site, so it is offered as a lead - judged there, never here.
            rows.append({"url": candidate.url, "title": name,
                         "snippet": str(record.get("description") or "")[:300]})
            if len(rows) >= limit:
                break
            continue
        if candidate.triage_verdict != "rejected" or candidate.rubric is not None:
            continue
        if reason.startswith(_NOT_A_LEAD_SOURCE) or not HARVESTABLE_REASON.search(reason):
            continue
        rows.append({"url": candidate.url, "title": candidate.title, "snippet": candidate.snippet})
        if len(rows) >= limit:
            break
    return rows


def _classify_kept(final, analyses, rubric_extractor, actor_context, stats, can_spend=None):
    """Classify only what is kept (accepted or for review), after banding.

    A rejected page never needed its category. An accepted one cannot be
    created without it, so if classification fails it goes to Review instead,
    with the reason. A page that turns out to describe an event or a person is
    rejected, with the reason.
    """
    result = []
    for candidate in final:
        analysis = analyses.get(candidate.candidate_id)
        if (candidate.score_band not in {"auto_high", "review"} or analysis is None
                or not needs_classification(analysis)):
            result.append(candidate)
            continue
        if can_spend is not None and not can_spend():
            # Strict budget: no classification call it cannot afford. An
            # accepted actor cannot be created without its category.
            stats["actor_classification_budget_skips"] = int(
                stats.get("actor_classification_budget_skips", 0) or 0) + 1
            if candidate.score_band == "auto_high":
                candidate = replace(
                    candidate, score_band="review", triage_verdict="review",
                    triage_reason=f"{candidate.triage_reason} Not classified within the run's "
                                  "budget; a person sets its category.")
            result.append(candidate)
            continue
        try:
            classified = rubric_extractor.classify(analysis)
            stats["actor_pages_classified"] = int(stats.get("actor_pages_classified", 0) or 0) + 1
            result.append(replace(candidate, record_preview=_with_found_for_topic(
                classified.record, actor_context, candidate.url, candidate.sector_codes,
                candidate.rubric,
            )))
        except CostLimitExceeded:
            raise
        except RuntimeError as exc:
            if "not an actor" in str(exc):
                result.append(replace(
                    candidate, score_band="auto_low", triage_verdict="rejected",
                    triage_reason=f"The page describes something other than an organisation: {exc}",
                ))
            else:
                result.append(_classification_failed(candidate, exc, stats))
        except Exception as exc:  # noqa: BLE001 - one page must not stop the run
            result.append(_classification_failed(candidate, exc, stats))
    return result


def _classification_failed(candidate, exc, stats):
    logger.warning("actor classification failed for %s: %s", candidate.url, exc)
    stats["actor_classification_failures"] = int(
        stats.get("actor_classification_failures", 0) or 0) + 1
    if candidate.score_band == "auto_high":
        return replace(candidate, score_band="review", triage_verdict="review",
                       triage_reason=f"{candidate.triage_reason} Could not be classified "
                                     f"automatically ({exc}); a person sets its category.")
    return candidate


def _actor_audit_row(run_id, url, status, exc) -> dict[str, object]:
    return {
        "run_id": run_id, "source": "open_web_search", "entity_type": "actor",
        "source_url": url, "content_hash": "", "natural_key": "", "zone": "", "score": "",
        "target_entity_id": "", "candidate_ids": [], "status": status, "error": str(exc),
    }


def _with_found_for_topic(
    record: dict[str, object] | None,
    actor_context: dict[str, object],
    url: str,
    sector_codes: tuple[str, ...],
    rubric: dict[str, object] | None = None,
) -> dict[str, object] | None:
    """Attach the topic the actor was found for, and why this actor belongs to it.

    The reason used to be a template naming only the hub and the crawl - true,
    but it said nothing about the organisation, so a reviewer could not tell
    from it why this actor and not any other. It now leads with the page's own
    evidence about the actor, which the rubric has already quoted, and ends with
    the hub it was matched to. Nothing new is inferred: if the rubric recorded
    no usable evidence, the statement says only what is actually known.
    """

    # A requested run's topic applies to every candidate it reads, including
    # official-site re-reads and leads, whose URLs were never search results.
    topic = (actor_context.get("candidate_topics") or {}).get(url)         or actor_context.get("request_topic")
    if not record or not topic:
        return record
    evidenced = topic["code"] in {str(code).upper() for code in sector_codes}
    evidence = _match_evidence(rubric)
    target = (
        f"Found for the discovery request '{topic['request_title']}' ({topic['code']})"
        if topic.get("request_title")
        else f"Matched to the {topic['code']} hub '{topic['hub_name']}'"
    )
    placement = target + (
        " on the page's own sector evidence." if evidenced
        else ", pending confirmation of its sector."
    )
    return {
        **record,
        "topic_id": topic["topic_id"],
        "match_strength": "strong" if evidenced else "moderate",
        "match_reason": f"{evidence} {placement}" if evidence else placement,
    }


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
    # Thresholds and gate settings come from configuration, so recalibrating the
    # bands is a config change, never a code change.
    quality_settings = quality_config(config)
    quality_reasons: dict[str, tuple[str, ...]] = {}
    lazy_classification = bool(config.get("actor_lazy_classification", True))
    source = source or OpenWebEventSource(config)
    shared_client = None
    if rubric_extractor is None or reranker is None:
        shared_client = _extraction_client(config, cost_meter)
    rubric_extractor = rubric_extractor or ActorRubricExtractor(
        shared_client,
        max_tokens=int(config.get("actor_rubric_max_tokens", 4096)),
        content_max_chars=int(config.get("actor_rubric_content_max_chars", 8000)),
        # Classification is a second model call per page. It is only needed for
        # candidates that are kept, so by default it runs after banding.
        classification_enabled=not lazy_classification,
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
    analyses: dict[str, ActorPageAnalysis] = {}
    quality_gates: dict[str, tuple[str, ...]] = {}
    today = datetime.now(UTC).date()
    # Strict budget, stopped gracefully: no page is started that the remaining
    # budget cannot finish, and everything already paid for is still banded,
    # classified and promoted. (A run that hit the ceiling used to raise and
    # discard every analysed page.)
    est_page_usd = float(config.get("actor_est_page_usd", 0.03))
    reserve_usd = float(config.get("actor_budget_reserve_usd", 0.05))
    ceiling = cost_meter.max_usd

    page_costs: list[float] = []

    def budget_left() -> bool:
        # The estimate learns from what pages actually cost in this run.
        expected = est_page_usd
        if page_costs:
            expected = max(est_page_usd, sum(page_costs) / len(page_costs))
        return ceiling is None or (
            cost_meter.spent_usd + expected + reserve_usd <= float(ceiling)
        )

    def not_read(candidate: CandidateRecord, reason: str) -> None:
        by_id[candidate.candidate_id] = replace(
            candidate, triage_verdict="not_read", triage_reason=reason, score_band=None
        )

    def analyse(candidate: CandidateRecord, *, official_name: str | None = None) -> None:
        """Fetch, read, score and judge one candidate. ``official_name`` marks a
        read of that organisation's own site (homepage + About page)."""
        nonlocal loaded_pages
        spent_before = cost_meter.spent_usd
        candidate_domain = candidate.domain or normalized_domain(candidate.url)
        domain_store.touch(candidate_domain)
        page_fetched = False
        try:
            if official_name is not None:
                doc = official_bundle(source, candidate.url)
            else:
                doc = source.fetch(candidate.url)
            page_fetched = True
            loaded_pages += 1
            final_domain = normalized_domain(doc.url)
            if not final_domain:
                raise RuntimeError(f"fetched open-web page has invalid final URL {doc.url!r}")
            if official_name is not None:
                # Free checks before any money is spent on the page: is this
                # really that organisation's site, and does it still exist?
                if registrable_domain(doc.url) != registrable_domain(candidate.url) \
                        and not site_is_official(official_name, doc):
                    moved = site_moved(candidate.url, doc.url)
                    by_id[candidate.candidate_id] = replace(
                        candidate, page_fetched=True, triage_verdict="rejected",
                        score_band="auto_low",
                        triage_reason=(
                            f"'{official_name}' appears merged, acquired or renamed: {moved}, "
                            "and that site does not name it."
                        ),
                    )
                    stats["actor_currency_rejected"] = int(
                        stats.get("actor_currency_rejected", 0) or 0) + 1
                    return
                if not site_is_official(official_name, doc):
                    by_id[candidate.candidate_id] = replace(
                        candidate, page_fetched=True, triage_verdict="rejected",
                        score_band=None,
                        triage_reason=(
                            f"Official site not confirmed: {final_domain} does not name "
                            f"'{official_name}'."
                        ),
                    )
                    stats["actor_official_unconfirmed"] = int(
                        stats.get("actor_official_unconfirmed", 0) or 0) + 1
                    return
            elif final_domain != candidate_domain:
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
            analyses[candidate.candidate_id] = analysis
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
                record=analysis.record,
            )
            website = analysis.record.get("website")
            currency = assess_currency(
                name=str(analysis.record.get("name") or official_name or ""),
                page_text=(doc.content if official_name is not None
                           else prepare_actor_rubric_content(
                               doc.content, content_type=doc.content_type,
                               max_chars=200_000).text),
                page_url=doc.url,
                stated_website=website,
                official_final_url=doc.url if official_name is not None else None,
                on_own_site=registrable_domain(doc.url) == registrable_domain(website),
                today=today,
                # Raw page for dates (footers); an official bundle lists its years.
                year_text=doc.content,
            )
            # Three bands, decided on relevance AND by hard gates the model
            # cannot talk its way past - see agents/discovery/search/actor_quality.
            quality = assess_actor(
                score=score.total,
                page_url=doc.url,
                record=analysis.record,
                rubric=analysis.rubric,
                config=quality_settings,
                scope=actor_context.get("discovery_scope"),
                record_sector_codes=matched_sectors,
                currency=currency,
                priority=score.priority,
            )
            quality_reasons[candidate.candidate_id] = quality.reasons
            quality_gates[candidate.candidate_id] = quality.gates_failed
            band, reasons = quality.band, quality.reasons
            # Classify a KEPT page now, inside the budgeted read, so its cost is
            # counted with the page. (Classifying everything at the end ran out
            # of budget on the 2026-10-15 replay and sent an accepted actor -
            # the NSF Energy Storage Engine - back to Review.) Rejected pages are
            # never classified.
            if lazy_classification and band in {"auto_high", "review"} \
                    and needs_classification(analysis):
                try:
                    analysis = rubric_extractor.classify(analysis)
                    analyses[candidate.candidate_id] = analysis
                    write_analysis_cache(cache_path, analysis)
                    stats["actor_pages_classified"] = int(
                        stats.get("actor_pages_classified", 0) or 0) + 1
                except CostLimitExceeded:
                    raise
                except Exception as exc:  # noqa: BLE001 - one page must not stop the run
                    if "not an actor" in str(exc):
                        band = "auto_low"
                        reasons = (*reasons, (f"The page describes something other than an "
                                              f"organisation: {exc}"))
                    else:
                        stats["actor_classification_failures"] = int(
                            stats.get("actor_classification_failures", 0) or 0) + 1
                        if band == "auto_high":
                            band = "review"
                            reasons = (*reasons, (f"Could not be classified automatically "
                                                  f"({exc}); a person sets its category."))
                quality_reasons[candidate.candidate_id] = reasons
            by_id[candidate.candidate_id] = replace(
                candidate,
                page_fetched=True,
                fit_score=score.total,
                rubric=analysis.rubric,
                record_preview=_with_found_for_topic(
                    analysis.record, actor_context, candidate.url, matched_sectors,
                    analysis.rubric,
                ),
                score_breakdown=score.contributions,
                score_band=band,
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
            audit_rows.append(_actor_audit_row(run_id, candidate.url, "record_validation_failed", exc))
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
            audit_rows.append(_actor_audit_row(run_id, candidate.url, "fetch_or_rubric_failed", exc))
        finally:
            if cost_meter.spent_usd > spent_before:
                page_costs.append(cost_meter.spent_usd - spent_before)
            _attach_prompt_cache_stats(
                stats,
                prefix="actor_rubric",
                before=rubric_usage_before,
                client=rubric_usage_client,
            )
            _attach_actor_content_stats(stats, rubric_extractor, config=config)

    stage_start = cost_meter.spent_usd
    # Shares of what is left for reading, so direct results cannot spend the
    # money meant for official-site re-reads and named leads (on the first
    # replay they did, and 21 named organisations were never read).
    pipeline_budget = (
        None if ceiling is None
        else max(0.0, float(ceiling) - cost_meter.spent_usd - reserve_usd)
    )

    def share_used(since: float, share_key: str, default: float) -> bool:
        if pipeline_budget is None:
            return False
        return cost_meter.spent_usd - since >= float(config.get(share_key, default)) * pipeline_budget

    queue = [*plan.candidates, *plan.backfill_candidates]
    for index, candidate in enumerate(queue):
        if loaded_pages >= analysis_page_budget:
            break
        if share_used(stage_start, "actor_direct_budget_share", 0.45):
            for skipped in queue[index:]:
                not_read(skipped, (
                    "Not read: direct search results used their share of this run's budget; "
                    "the rest is kept for official-site reads and named leads."
                ))
            stats["actor_direct_share_stop"] = 1
            break
        if not budget_left():
            for skipped in queue[index:]:
                not_read(skipped, (
                    f"Not read: the run's budget of ${float(ceiling):.2f} was reached "
                    "before this page."
                ))
            stats["actor_budget_stop"] = 1
            attention_reasons.append(f"run budget ${float(ceiling):.2f} reached; reading stopped")
            break
        attempted_pages += 1
        analyse(candidate)
    stats["cost_stage_pages_usd"] = round(cost_meter.spent_usd - stage_start, 6)

    stats["pages_selected"] = attempted_pages
    stats["fetch_backfill_attempts"] = sum(
        1
        for candidate in queue[:attempted_pages]
        if candidate.candidate_id not in primary_ids
    )

    # ---- official-site re-reads: strong candidates held only for want of the
    # organisation's own page get one read of its homepage + About page.
    stage_start = cost_meter.spent_usd
    read_domains = {
        registrable_domain(c.url) for c in by_id.values() if c.page_fetched
    }
    followups: list[tuple[CandidateRecord, CandidateRecord]] = []
    read_official_domains: set[str | None] = set()
    for candidate in sorted(by_id.values(), key=lambda c: -float(c.fit_score or 0.0)):
        if len(followups) >= int(config.get("actor_max_official_followups", 8)):
            break
        if candidate.provider == "official_site":
            continue
        gates = set(quality_gates.get(candidate.candidate_id) or ())
        # A page the reader could not see at all (no name, no evidence) is not
        # evidence against the organisation: its site's homepage + About page
        # get the same single re-read, under the same budget share.
        unreadable = candidate.score_band == "auto_low" and "unreadable_page" in gates
        if not unreadable and (
                candidate.score_band != "review"
                or float(candidate.fit_score or 0.0)
                < float(config.get("actor_followup_min_score", 0.6))
                or not gates & _FIXABLE_BY_OFFICIAL_PAGE):
            continue
        record = candidate.record_preview or {}
        target = homepage(record.get("website") or "") or homepage(candidate.url)
        if not target or registrable_domain(target) in read_official_domains:
            continue
        if not unreadable and target.rstrip("/") == candidate.url.rstrip("/"):
            continue
        if not budget_left() or share_used(stage_start, "actor_followup_budget_share", 0.15):
            break
        name = str(record.get("name") or candidate.title or "")
        followup = _official_candidate(
            candidate, run_id=run_id, url=target, name=name,
            reason=f"Re-read on its official site after: {', '.join(sorted(gates))}.",
        )
        by_id[followup.candidate_id] = followup
        analyse(followup, official_name=name)
        read_domains.add(registrable_domain(target))
        read_official_domains.add(registrable_domain(target))
        followups.append((candidate, followup))
    for original, followup in followups:
        result = by_id[followup.candidate_id]
        if result.score_band in {"auto_high", "review", "auto_low"} and result.rubric is not None:
            by_id[original.candidate_id] = replace(
                by_id[original.candidate_id], score_band=None, triage_verdict="superseded",
                triage_reason=f"Re-read on its official site {result.url}; judged there.",
            )
    stats["actor_official_followups"] = len(followups)
    stats["cost_stage_followups_usd"] = round(cost_meter.spent_usd - stage_start, 6)

    # ---- leads: organisations NAMED in results rejected as news, lists or
    # documents, read on their own (confirmed) sites.
    stage_start = cost_meter.spent_usd
    lead_client = actor_context.get("lead_client")
    if lead_client is not None and int(config.get("actor_max_leads_per_run", 20)) > 0:
        lead_rows = _lead_sources(by_id.values(), actor_context)
        existing_domains = set(actor_context.get("existing_actor_domains") or ())
        existing_names = set(actor_context.get("existing_actor_names") or ())
        try:
            leads = harvest_leads(
                lead_client, lead_rows,
                topic=str(actor_context.get("lead_topic") or "the GHUS sectors"),
                area=str(actor_context.get("lead_area") or "the United States"),
                max_leads=int(config.get("actor_max_leads_per_run", 20)) * 2,
            ) if lead_rows and budget_left() else []
        except CostLimitExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - leads are a bonus, never a failure
            logger.warning("lead harvesting failed: %s", exc)
            leads = []
        stats["actor_leads_named"] = len(leads)
        # The article that names an organisation usually links to it: free.
        leads = _resolve_lead_websites(
            leads, source, limit=int(config.get("actor_lead_source_fetches", 10)), stats=stats,
        )
        read = 0
        for lead in leads:
            key = _name_key(lead.name)
            domain = registrable_domain(lead.website)
            if domain and domain == registrable_domain(lead.source_url):
                outcome = ("is the publisher of the article it was named in, not an "
                           "organisation the article is about")
            elif key in existing_names or (domain and domain in existing_domains):
                outcome = "already on the map"
            elif domain and domain in read_domains:
                outcome = "already read in this run"
            elif not lead.website:
                outcome = "named, but no official website is known"
            elif read >= int(config.get("actor_max_leads_per_run", 20)):
                outcome = "not read: the run's lead limit was reached"
            elif not budget_left():
                outcome = f"not read: the run's budget of ${float(ceiling):.2f} was reached"
            else:
                outcome = None
            lead_candidate = _official_candidate(
                None, run_id=run_id, url=lead.website or lead.source_url, name=lead.name,
                reason=f"Lead: named in {lead.source_url} ({lead.why}).",
                source_url=lead.source_url,
            )
            if outcome is not None:
                by_id[lead_candidate.candidate_id] = replace(
                    lead_candidate, triage_verdict="not_read",
                    triage_reason=f"Lead '{lead.name}' {outcome}.",
                )
                continue
            by_id[lead_candidate.candidate_id] = lead_candidate
            read += 1
            read_domains.add(domain)
            analyse(lead_candidate, official_name=lead.name)
        stats["actor_leads_read"] = read
    stats["cost_stage_leads_usd"] = round(cost_meter.spent_usd - stage_start, 6)

    updated = list(by_id.values())
    scored = [candidate for candidate in updated if candidate.rubric is not None]
    if bool(config.get("actor_rerank_enabled", False)):
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
        # Superseded (re-read on its official site) and not-read candidates keep
        # their recorded reason; they are not banded again.
        if candidate.rubric is None or candidate.triage_verdict in {"superseded", "not_read"}:
            final.append(candidate)
            continue
        # The topic the actor was found for travels WITH the record, whichever
        # classification path ran. Attaching it only in _classify_kept left
        # every inline-classified candidate (the default since 2026-10-15)
        # without a topic, and promotion skips the whole topic-scoped Light
        # Pull when the record has none - 1 fact written instead of 20.
        if not (candidate.record_preview or {}).get("topic_id"):
            candidate = replace(candidate, record_preview=_with_found_for_topic(
                candidate.record_preview, actor_context, candidate.url,
                candidate.sector_codes, candidate.rubric))
        band = candidate.score_band or actor_score_band(float(candidate.fit_score or 0.0), config)
        verdict = "accepted" if band == "auto_high" else "rejected" if band == "auto_low" else "review"
        recorded = quality_reasons.get(candidate.candidate_id) or ()
        reason = (
            " ".join(recorded) if recorded
            else f"actor rubric score {float(candidate.fit_score or 0.0):.3f} -> {band}"
        )
        if band == "auto_high" and not (candidate.record_preview or {}).get("name"):
            band = "review"
            verdict = "review"
            reason = "actor rubric auto_high but canonical record is missing required name"
        elif (
            band == "auto_high"
            and actor_context.get("candidate_topics")
            and (candidate.record_preview or {}).get("match_strength") != "strong"
        ):
            # Architecture V2: an actor is created automatically only when its own
            # page evidences the topic it was found for; otherwise a human decides.
            band = "review"
            verdict = "review"
            reason = (
                f"actor rubric score {float(candidate.fit_score or 0.0):.3f} -> auto_high, "
                "but the page does not evidence the topic it was found for"
            )
        final.append(
            replace(
                candidate,
                triage_verdict=verdict,
                triage_reason=reason,
                score_band=band,
            )
        )

    cap = actor_context.get("max_new_actors")
    if cap:
        # One request can never flood the map or the review queue.
        final, held = apply_new_actor_cap(final, int(cap))
        stats["actor_request_cap"] = int(cap)
        stats["actor_request_capped"] = held
        if held:
            attention_reasons.append(
                f"request cap: {held} further candidate(s) held back beyond {int(cap)}"
            )

    if lazy_classification:
        final = _classify_kept(
            final, analyses, rubric_extractor, actor_context, stats,
            can_spend=lambda: ceiling is None
            or cost_meter.spent_usd + float(config.get("actor_est_classify_usd", 0.01))
            <= float(ceiling),
        )

    final_by_id = {candidate.candidate_id: candidate for candidate in final}
    auto_high = [candidate for candidate in final if candidate.score_band == "auto_high"]
    # Decision 2026-10-14: accepted actors are created Verified (labelled as the
    # agent's decision). "parked" restores the earlier human-verifies-all flow.
    verify_accepted = str(config.get("actor_auto_accept_status", "parked")) == "verified"
    # The policy is not enabled anywhere until GHUS confirms it for that
    # environment: the deployment must say so explicitly. Without it an
    # accepted actor is created Parked and a person verifies it, as before 560.
    if verify_accepted and os.environ.get("GHUS_AGENT_AUTO_VERIFY", "") != "confirmed":
        verify_accepted = False
        stats["actor_auto_verify_disabled"] = (
            "GHUS_AGENT_AUTO_VERIFY is not 'confirmed' in this environment; "
            "accepted actors were sent to Review instead")
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
                auto_accept_reasons=(
                    _auto_accept_reasons(candidate, quality_settings, actor_context)
                    if verify_accepted else None
                ),
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


def _auto_accept_reasons(candidate, settings, actor_context) -> str:
    """What the agent checked before verifying, stated on the verification event."""
    scope = actor_context.get("discovery_scope")
    checks = [
        "official website stated and the page is on it",
        f"at least {settings.min_evidence_items} rubric criteria evidenced",
        "operating organisation established",
        "concrete programmes, research or use cases",
        f"a factual description of {settings.min_description_chars}+ characters",
    ]
    if scope is not None and getattr(scope, "focus_terms", ()):
        checks.append("the requested sub-topic is on the page")
    return (
        f"Accepted by the discovery agent: score {float(candidate.fit_score or 0.0):.2f} "
        f"meets the {settings.auto_high:.2f} accept threshold and every quality gate held "
        f"({'; '.join(checks)}). Source: {candidate.url}"
    )


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
    request=None,
) -> EventFetchOutcome:
    """Fetch gated events, score page evidence, then route by score and qualification.

    ``request`` is a Discovery-page request for events (on-request mode); the
    automatic weekly run passes none. Both use the same extraction, gates,
    follow-up and Review routing; a request also excludes what falls outside
    its dates or area and keeps at most its per-run number of new events.
    """
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
    # Already waiting in Review (staged by an earlier or overlapping run): not
    # read or staged again, so two runs cannot create two review profiles.
    waiting_events = pending_review_events(session) if event_candidates is None else []
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
    followup_budget = FollowupBudget.from_config(config)
    read_this_run: list[dict[str, object]] = []

    stage_start = cost_meter.spent_usd
    for candidate in plan.candidates:
        held = held_event_match(candidate.title, canonical_candidates)
        waiting = None if held is not None else held_event_match(candidate.title, waiting_events)
        if (held or waiting) is not None and by_id[candidate.candidate_id].score_band != "duplicate":
            # Already on the map, same edition - or already waiting in Review:
            # not fetched or analysed again.
            where = (f"already on the map as {held.get('name')}" if held is not None
                     else f"already waiting in Review as {waiting.get('name')}")
            by_id[candidate.candidate_id] = replace(
                candidate,
                triage_verdict="duplicate",
                triage_reason=f"{where}; not read again",
                duplicate_of=str((held or {}).get("event_id") or "") or None,
                score_band="duplicate",
            )
            key = "held_event_skips" if held is not None else "pending_review_skips"
            stats[key] = int(stats.get(key, 0) or 0) + 1
            continue
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
            text_cache_path = _text_cache_path(raw_store, "event_analysis", doc,
                                               EVENT_ANALYSIS_VERSION)
            if analysis is None:
                analysis = read_event_analysis_cache(
                    text_cache_path, sector_codes=sector_codes, run_date=current_date)
                if analysis is not None:
                    stats["analyses_from_text_cache"] = int(
                        stats.get("analyses_from_text_cache", 0) or 0) + 1
                    write_event_analysis_cache(cache_path, analysis)
            participant_actors: list[dict[str, object]] = []
            participant_people: list[dict[str, object]] = []
            unchanged = prior_raw is not None and _staged_before(session, prior_raw)
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
                write_event_analysis_cache(text_cache_path, analysis)
                stats["event_pages_analyzed"] = int(
                    stats.get("event_pages_analyzed", 0) or 0
                ) + 1
            # What the page says the event is - name, date, page - against what
            # waits in Review and what this run already read: the same event is
            # staged once. A run keeps the first reading unless a later one is
            # the event's own (or its organiser's) page and the first was not.
            facts = getattr(analysis, "facts", None) or {}
            reading = {**analysis.record, "source_url": doc.url,
                       "official": facts.get("page_kind") in OFFICIAL_EVENT_PAGES}
            twin = next((event for event in waiting_events if same_event(reading, event)), None)
            if twin is None:
                twin = next((event for event in read_this_run if same_event(reading, event)
                             and (event["official"] or not reading["official"])), None)
            if twin is not None:
                by_id[candidate.candidate_id] = replace(
                    candidate,
                    page_fetched=True,
                    triage_verdict="duplicate",
                    triage_reason=(f"the same event as {twin.get('title') or twin.get('name')}, "
                                   "already waiting in Review or read in this run; not staged again"),
                    score_band="duplicate",
                )
                stats["same_event_skips"] = int(stats.get("same_event_skips", 0) or 0) + 1
                continue
            read_this_run.append(reading)
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
                record_preview={**analysis.record,
                                **({"facts": analysis.facts} if analysis.facts else {})},
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

    stats["cost_stage_pages_usd"] = round(cost_meter.spent_usd - stage_start, 6)
    updated = [by_id[candidate.candidate_id] for candidate in candidates]
    updated, event_duplicate_count = _collapse_extracted_event_duplicates(updated)
    stats["event_record_duplicates_collapsed"] = event_duplicate_count
    scored = [
        candidate
        for candidate in updated
        if candidate.rubric is not None and candidate.score_band != "duplicate"
    ]
    stage_start = cost_meter.spent_usd
    reranked, rerank_attention = rerank_top_event_candidates(
        scored,
        reranker=reranker,
        config=config,
    )
    stats["cost_stage_rerank_usd"] = round(cost_meter.spent_usd - stage_start, 6)
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
        elif band != "auto_low" and _event_explicitly_outside_us(record):
            # GHUS maps United States hubs. Measured October 2026: a Jakarta
            # conference (0.78) and an AusIMM one (0.73) were auto-accepted
            # because nothing checked where an event takes place.
            band = "auto_low"
            verdict = "rejected"
            reason = (
                f"event takes place outside the United States ({record.get('country')}); "
                "GHUS maps United States hubs"
            )
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
        if band != "auto_low" and record.get("title"):
            # Separate checks - official source, identity, date, place,
            # relevance, cancellation, completeness - that only lower the band.
            doc_entry = docs.get(candidate.candidate_id)
            read_text = page_text(doc_entry[0].content) if doc_entry else ""
            gate = event_gate(
                record, facts=record.get("facts"), page_url=candidate.url,
                page_text=read_text, rubric=candidate.rubric, run_date=current_date,
                config=config)
            outside = event_outside_request(record, request) if request is not None else None
            if gate.decision == "research" and outside is None and doc_entry is not None:
                # Needs More Research: one bounded read of the official pages.
                followup = _event_followup(
                    record, candidate.url, doc_entry[0], budget=followup_budget,
                    source=source, run_log=run_log, raw_store=raw_store, run_id=run_id,
                    rubric_extractor=rubric_extractor, sector_codes=sector_codes,
                    hub_names=hub_names, run_date=current_date, stats=stats,
                    cost_meter=cost_meter)
                if followup is not None:
                    extra_doc, extra_analysis = followup
                    record = merge_event_reads(
                        record, {**extra_analysis.record,
                                 "facts": extra_analysis.facts}, extra_doc.url)
                    read_text = f"{read_text}\n{page_text(extra_doc.content)}"
                    gate = event_gate(
                        record, facts=record.get("facts"), page_url=candidate.url,
                        page_text=read_text, rubric=candidate.rubric,
                        run_date=current_date, config=config)
                    if gate.decision != "research":
                        stats["followups_resolved"] = int(
                            stats.get("followups_resolved", 0) or 0) + 1
                    outside = (event_outside_request(record, request)
                               if request is not None else None)
            record = {**record, "quality": gate.payload()}
            capped = cap_band(band, gate)
            if capped != band:
                band = capped
                verdict = "rejected" if band == "auto_low" else "review"
                reason = f"{reason}; quality gate -> {band}: {gate.summary}"
            if outside is not None:
                band, verdict = "auto_low", "rejected"
                reason = f"{reason}; outside the request: {outside}"
        final.append(
            replace(
                candidate,
                triage_verdict=verdict,
                triage_reason=reason,
                score_band=band,
                record_preview=record,
            )
        )

    stats["cost_stage_followups_usd"] = round(followup_budget.spent_usd, 6)
    if request is not None:
        # At most the request's number of new events per run, strongest first.
        final, held_back = apply_new_actor_cap(final, request.max_new_actors, noun="events")
        stats["request_cap_held_back"] = held_back

    routable = [
        candidate
        for candidate in final
        if candidate.score_band in {"auto_high", "review"}
    ]
    stage_start = cost_meter.spent_usd
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
            try:
                participant_records = participant_extractor.extract(doc)
            except CostLimitExceeded:
                raise
            except Exception as exc:  # noqa: BLE001 - the event stands without its participants
                # Measured 2026-10-23: one dropped API connection here failed a
                # whole run after every page had been read and paid for.
                logger.warning("participant extraction failed for %s: %s", candidate.url, exc)
                stats["participant_extraction_failures"] = int(
                    stats.get("participant_extraction_failures", 0) or 0) + 1
                participant_records = []
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
                # Every qualified event goes to GHUS Review - a confident one
                # too. Nothing is created on the map until a person verifies
                # it (Architecture V2: a new record is Parked until reviewed,
                # and Review is where that happens). A close match to an event
                # already on the map rides along as its candidate.
                event_review_metadata={
                    "review_kind": "rubric_band",
                    "search_candidate_id": candidate.candidate_id,
                    "rubric_score": candidate.fit_score,
                    "rubric": candidate.rubric,
                    "score_breakdown": candidate.score_breakdown,
                    "rerank_position": candidate.rerank_position,
                    "rerank_reason": candidate.rerank_reason,
                    "qualification_paths": list(candidate.qualification_paths),
                    "quality": (candidate.record_preview or {}).get("quality"),
                    "score_band": candidate.score_band,
                },
            )
        finally:
            domain_store.add_counts(
                domain,
                records_extracted=int(stats["records_extracted"]) - before_extracted,
                records_promoted=int(stats["records_promoted"]) - before_promoted,
            )

    stats["cost_stage_participants_usd"] = round(cost_meter.spent_usd - stage_start, 6)
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


def _followup_read(urls, *, budget, kind, source, run_log, raw_store, run_id, analyse, stats,
                   cost_meter):
    """Fetch the first follow-up page that loads, store it, analyse it. None if none did."""
    before = cost_meter.spent_usd
    try:
        for url in urls:
            try:
                doc = source.fetch(url)
                stats["pages_fetched"] += 1
                stats["followup_pages_fetched"] = int(
                    stats.get("followup_pages_fetched", 0) or 0) + 1
                prior_raw = run_log.find_raw_document(url=doc.url, content_hash=doc.content_hash)
                raw_document_id = run_log.write_raw_document(
                    run_id=run_id, doc=doc,
                    storage_path=_storage_path_for_doc(raw_store, run_id=run_id, doc=doc,
                                                       prior_raw=prior_raw))
                analysis = analyse(doc)
                cost_meter.enforce()
                return doc, raw_document_id, analysis
            except CostLimitExceeded:
                raise
            except Exception as exc:  # noqa: BLE001 - a follow-up never stops the run
                logger.info("%s follow-up %s not read: %s", kind, url, exc)
                stats["followup_failures"] = int(stats.get("followup_failures", 0) or 0) + 1
        return None
    finally:
        budget.spent_usd += cost_meter.spent_usd - before


def _event_followup(record, page_url, doc, *, budget, source, run_log, raw_store, run_id,
                    rubric_extractor, sector_codes, hub_names, run_date, stats, cost_meter):
    urls = event_followup_urls(record, page_url, doc.content)
    if not urls or not budget.take():
        return None
    stats["followups_attempted"] = int(stats.get("followups_attempted", 0) or 0) + 1

    def analyse(page):
        cache_path = (raw_store.base_dir / "event_analysis"
                      / f"{page.content_hash}.{EVENT_ANALYSIS_VERSION}.json")
        text_path = _text_cache_path(raw_store, "event_analysis", page, EVENT_ANALYSIS_VERSION)
        for path in (cache_path, text_path):
            cached = read_event_analysis_cache(path, sector_codes=sector_codes,
                                               run_date=run_date)
            if cached is not None:
                return cached
        if not isinstance(rubric_extractor, EventRubricExtractor):
            raise RuntimeError("follow-up needs the event rubric extractor")
        analysis = rubric_extractor.extract(page, sector_codes=sector_codes,
                                            hub_names=hub_names, run_date=run_date)
        write_event_analysis_cache(cache_path, analysis)
        write_event_analysis_cache(text_path, analysis)
        return analysis

    read = _followup_read(urls, budget=budget, kind="event", source=source, run_log=run_log,
                          raw_store=raw_store, run_id=run_id, analyse=analyse, stats=stats,
                          cost_meter=cost_meter)
    return None if read is None else (read[0], read[2])


def _linkedin_lookup(linkedin_search, record, *, stats, cost_meter, budget):
    """{url, title} of this person's matched public LinkedIn profile, or None."""
    name = str(record.get("name") or "").strip()
    affiliation = str(record.get("affiliation") or "").strip()
    if not name or not affiliation:
        return None
    stats["linkedin_searches"] = int(stats.get("linkedin_searches", 0) or 0) + 1
    before = cost_meter.spent_usd
    try:
        found = linkedin_search(name, affiliation)
        cost_meter.enforce()
    except CostLimitExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 - a missing LinkedIn never stops the run
        logger.info("LinkedIn search for %s failed: %s", name, exc)
        found = None
    finally:
        budget.spent_usd += cost_meter.spent_usd - before
    if found is not None:
        stats["linkedin_found"] = int(stats.get("linkedin_found", 0) or 0) + 1
    return found


def _person_followup(record, page_url, *, page_html="", budget, source, run_log, raw_store,
                     run_id,
                     rubric_extractor, sector_codes, hub_names, held_actor_names, stats,
                     cost_meter):
    urls = person_followup_urls(record, page_url, page_html)
    if not urls or not budget.take():
        return None
    stats["followups_attempted"] = int(stats.get("followups_attempted", 0) or 0) + 1

    def analyse(page):
        cache_path = (raw_store.base_dir / "person_analysis"
                      / f"{page.content_hash}.{PERSON_ANALYSIS_VERSION}.json")
        text_path = _text_cache_path(raw_store, "person_analysis", page, PERSON_ANALYSIS_VERSION)
        for path in (cache_path, text_path):
            cached = read_person_analysis_cache(path, held_actor_names=held_actor_names)
            if cached is not None:
                return cached
        if not isinstance(rubric_extractor, PersonRubricExtractor):
            raise RuntimeError("follow-up needs the person rubric extractor")
        analysis = rubric_extractor.extract(page, sector_codes=sector_codes,
                                            hub_names=hub_names,
                                            held_actor_names=held_actor_names)
        write_person_analysis_cache(cache_path, analysis)
        write_person_analysis_cache(text_path, analysis)
        return analysis

    read = _followup_read(urls, budget=budget, kind="person", source=source, run_log=run_log,
                          raw_store=raw_store, run_id=run_id, analyse=analyse, stats=stats,
                          cost_meter=cost_meter)
    return read


def _staged_before(session, prior_raw) -> bool:
    """The same page, unchanged, already reached staging (and so Review): skip it.

    A page read before but never staged - excluded under older rules, or read
    by a run that failed or stopped at its cost cap - is read again (from the
    analysis cache: no second model call) and decided under today's rules.
    Without a database the old behaviour stands: an unchanged page is skipped.
    """
    if _read_by_failed_run(session, prior_raw):
        return False
    url = str((prior_raw or {}).get("url") or "")
    if session is None or not url:
        return True
    try:
        with session.begin_nested():
            return session.execute(
                text("SELECT 1 FROM staged_record WHERE source_url = :url LIMIT 1"),
                {"url": url}).first() is not None
    except Exception:  # noqa: BLE001 - no staging table: keep the old behaviour
        return True


def _read_by_failed_run(session, prior_raw) -> bool:
    """The page was last read by a run that failed, or stopped at its cost cap.

    Such a page is not "unchanged": nothing from it reached Review, so it is
    read again (from the analysis cache - no second model call). Measured
    2026-10-23: a run that lost its API connection after reading 13 pages left
    them stored, and every later run skipped them. Events and people only; the
    actor pipeline is untouched.
    """
    run_id = str((prior_raw or {}).get("run_id") or "")
    if session is None or not run_id:
        return False
    try:
        with session.begin_nested():
            row = session.execute(
                text("SELECT status, status_reason FROM scrape_run "
                     "WHERE CAST(run_id AS text) = :id"),
                {"id": run_id}).first()
        status, reason = (row[0], row[1]) if row else (None, None)
    except Exception:  # noqa: BLE001 - no run ledger: keep the old behaviour
        return False
    return status == "failed" or str(reason or "").startswith("max_usd_per_run cap hit")


def _text_cache_path(raw_store, folder: str, doc, version: str) -> Path:
    """The analysis cache keyed by what the model reads: the address and the page text.

    The raw-HTML hash changes with every nonce, ad slot or session token; the
    readable text often does not (measured 2026-10-23: 5 of 7 event pages
    re-read with changed HTML had identical text). Same address and same text
    is the same model input, so its analysis is reused - no second call.
    """
    key = hashlib.sha256(
        f"{doc.url}\n{reading_text(doc.content, doc.content_type)}".encode("utf-8")
    ).hexdigest()
    return raw_store.base_dir / folder / f"text-{key}.{version}.json"


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


_US_COUNTRY_NAMES = {"us", "usa", "unitedstates", "unitedstatesofamerica", "america"}


def _event_explicitly_outside_us(record: dict[str, object]) -> bool:
    """True only when the page itself names a country other than the US.

    A missing country is unknown, not foreign: it is never treated as either.
    """
    country = "".join(ch for ch in str(record.get("country") or "").lower() if ch.isalpha())
    return bool(country) and country not in _US_COUNTRY_NAMES


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
    request=None,
    linkedin_search=None,
    own_sites: dict[str, str] | None = None,
) -> PersonFetchOutcome:
    """Fetch person profiles, score page evidence, then resolve identity in code.

    ``request`` is a Discovery-page request for people (on-request mode). The
    same gates, follow-up and Review routing apply as in any other run; a
    request also excludes people at another institution than the one asked
    for and keeps at most its per-run number of new people.
    """
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
    # A complete profile often needs the person's own site or a LinkedIn
    # search; a people run has its own, larger allowance (still bounded).
    followup_budget = FollowupBudget(
        remaining=max(0, int(config.get("person_followup_max_per_run", 12))))
    waiting_people = pending_review_people(session) if person_candidates is None else set()

    stage_start = cost_meter.spent_usd
    for candidate in plan.candidates:
        if str(candidate.url or "").lower().rstrip("/") in waiting_people or (
                candidate.title and person_key(candidate.title) in waiting_people):
            # Already waiting in Review from an earlier or overlapping run.
            by_id[candidate.candidate_id] = replace(
                candidate, triage_verdict="duplicate", score_band="duplicate",
                triage_reason="already waiting in Review; not read again")
            stats["pending_review_skips"] = int(stats.get("pending_review_skips", 0) or 0) + 1
            continue
        candidate_domain = candidate.domain or normalized_domain(candidate.url)
        domain_store.touch(candidate_domain)
        page_fetched = False
        try:
            try:
                doc = source.fetch(candidate.url)
            except Exception as exc:  # noqa: BLE001 - a refused profile has one alternative
                own_site = (own_sites or {}).get(candidate.url)
                if not own_site or not re.search(r"\b(401|403|429)\b", str(exc)):
                    raise
                # The department site refuses automated reading; the person's
                # own lab or group site, linked from the same directory card,
                # is read instead (still an official, self-published source).
                doc = source.fetch(own_site)
                candidate_domain = normalized_domain(doc.url)
                stats["person_own_site_used"] = int(stats.get("person_own_site_used", 0) or 0) + 1
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
            text_cache_path = _text_cache_path(raw_store, "person_analysis", doc,
                                               PERSON_ANALYSIS_VERSION)
            if analysis is None:
                analysis = read_person_analysis_cache(
                    text_cache_path, held_actor_names=held_actor_names)
                if analysis is not None:
                    stats["analyses_from_text_cache"] = int(
                        stats.get("analyses_from_text_cache", 0) or 0) + 1
                    write_person_analysis_cache(cache_path, analysis)
            unchanged = prior_raw is not None and _staged_before(session, prior_raw)
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
                write_person_analysis_cache(text_cache_path, analysis)
                stats["person_pages_analyzed"] = int(
                    stats.get("person_pages_analyzed", 0) or 0
                ) + 1
            score = score_person_rubric(analysis.rubric, config=config)
            by_id[candidate.candidate_id] = replace(
                candidate,
                page_fetched=True,
                fit_score=score.total,
                rubric=analysis.rubric,
                record_preview={**analysis.record,
                                **({"facts": analysis.facts} if analysis.facts else {})},
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

    stats["cost_stage_pages_usd"] = round(cost_meter.spent_usd - stage_start, 6)
    updated = [by_id[candidate.candidate_id] for candidate in candidates]
    scored = [candidate for candidate in updated if candidate.rubric is not None]
    stage_start = cost_meter.spent_usd
    reranked, rerank_attention = rerank_top_person_candidates(
        scored,
        reranker=reranker,
        config=config,
    )
    stats["cost_stage_rerank_usd"] = round(cost_meter.spent_usd - stage_start, 6)
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
        if band != "auto_low" and record.get("name"):
            # Separate checks - identity source, affiliation, relevance,
            # completeness - that can only lower the rubric's band.
            doc_entry = docs.get(candidate.candidate_id)
            page_url = candidate.url
            gate = person_gate(
                record, facts=record.get("facts"), page_url=page_url,
                page_text=page_text(doc_entry[0].content) if doc_entry else "",
                rubric=candidate.rubric, config=config)
            outside = person_outside_request(record, request) if request is not None else None
            if gate.decision == "research" and outside is None:
                # Needs More Research: read the official profile the page names,
                # once. If it is this person's, it becomes the source.
                followup = _person_followup(
                    record, page_url, page_html=doc_entry[0].content if doc_entry else "",
                    budget=followup_budget, source=source,
                    run_log=run_log, raw_store=raw_store, run_id=run_id,
                    rubric_extractor=rubric_extractor, sector_codes=sector_codes,
                    hub_names=hub_names, held_actor_names=held_actor_names,
                    stats=stats, cost_meter=cost_meter)
                if followup is not None:
                    extra_doc, extra_raw_id, extra = followup
                    extra_record = {**extra.record,
                                    **({"facts": extra.facts} if extra.facts else {})}
                    extra_bio = (extra.facts or {}).get("bio")
                    if extra_bio and not (record.get("facts") or {}).get("bio") \
                            and same_person(str(record.get("name")),
                                            str(extra_record.get("name") or "")):
                        # The person's own site holds the bio their faculty page
                        # lacks: the bio joins the profile, with that site as source.
                        facts = dict(record.get("facts") or {})
                        facts["bio"] = extra_bio
                        facts["evidence"] = {
                            **dict(facts.get("evidence") or {}),
                            "bio": dict((extra.facts.get("evidence") or {}).get("bio") or {
                                "quote": extra_bio, "source_url": extra_doc.url})}
                        record = {**record, "facts": facts}
                        gate = person_gate(
                            record, facts=facts, page_url=page_url,
                            page_text=page_text(doc_entry[0].content) if doc_entry else "",
                            rubric=candidate.rubric, config=config)
                        stats["bios_from_own_site"] = int(
                            stats.get("bios_from_own_site", 0) or 0) + 1
                    extra_gate = person_gate(
                        extra_record, facts=extra_record.get("facts"), page_url=extra_doc.url,
                        page_text=page_text(extra_doc.content), rubric=extra.rubric,
                        config=config)
                    if same_person(str(record.get("name")), str(extra_record.get("name") or "")) \
                            and (extra_gate.decision in ("accept", "review")
                                 or (extra_gate.decision == "research"
                                     and len(extra_gate.missing_mandatory)
                                     < len(gate.missing_mandatory))):
                        score = score_person_rubric(extra.rubric, config=config)
                        candidate = replace(candidate, rubric=extra.rubric,
                                            fit_score=score.total,
                                            score_breakdown=score.contributions)
                        band = person_score_band(score.total, config)
                        verdict = "accepted" if band == "auto_high" else (
                            "rejected" if band == "auto_low" else "review")
                        reason = (f"person rubric score {score.total:.3f} -> {band} "
                                  f"(official profile read: {extra_doc.url})")
                        record = {**extra_record,
                                  "followup": {"url": extra_doc.url, "from": page_url}}
                        gate = extra_gate
                        docs[candidate.candidate_id] = (
                            extra_doc, normalized_domain(extra_doc.url), extra_raw_id, False)
                        stats["followups_resolved"] = int(
                            stats.get("followups_resolved", 0) or 0) + 1
                        outside = (person_outside_request(record, request)
                                   if request is not None else None)
            if (gate.decision == "research" and outside is None
                    and linkedin_search is not None
                    and set(gate.missing_mandatory) == {"bio or LinkedIn"}
                    and followup_budget.take()):
                # Complete but for a bio: one LinkedIn-only search for this name
                # and organization. The profile's address is taken from the
                # search result; LinkedIn itself is never opened.
                found = _linkedin_lookup(linkedin_search, record, stats=stats,
                                         cost_meter=cost_meter, budget=followup_budget)
                if found is not None:
                    facts = dict(record.get("facts") or {})
                    facts["linkedin_url"] = found["url"]
                    facts["evidence"] = {**dict(facts.get("evidence") or {}), "linkedin_url": {
                        "quote": found["title"], "source_url": found["url"],
                        "date_read": datetime.now(UTC).isoformat(),
                        "how": "search result title; LinkedIn itself not opened"}}
                    record = {**record, "facts": facts}
                    doc_entry = docs.get(candidate.candidate_id)
                    gate = person_gate(
                        record, facts=facts,
                        page_url=doc_entry[0].url if doc_entry else candidate.url,
                        page_text=page_text(doc_entry[0].content) if doc_entry else "",
                        rubric=candidate.rubric, config=config)
            record = {**record, "quality": gate.payload()}
            capped = cap_band(band, gate)
            if capped != band:
                band = capped
                verdict = "rejected" if band == "auto_low" else "review"
                reason = f"{reason}; quality gate -> {band}: {gate.summary}"
            if outside is not None:
                band, verdict = "auto_low", "rejected"
                reason = f"{reason}; outside the request: {outside}"
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
                record_preview=record,
            )
        )

    stats["cost_stage_followups_usd"] = round(followup_budget.spent_usd, 6)
    if request is not None:
        final, held_back = apply_new_actor_cap(final, request.max_new_actors, noun="people")
        stats["request_cap_held_back"] = held_back

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
                    "quality": (candidate.record_preview or {}).get("quality"),
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
