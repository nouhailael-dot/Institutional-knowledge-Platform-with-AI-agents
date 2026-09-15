"""Shared types for open-web discovery."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class SearchResult:
    """Provider-neutral search result.

    The five fields mirror the Phase 1 contract and are intentionally enough for
    triage without fetching candidate pages.
    """

    url: str
    title: str
    snippet: str
    provider: str
    query: str

    def as_tuple(self) -> tuple[str, str, str, str, str]:
        return (self.url, self.title, self.snippet, self.provider, self.query)


@dataclass(frozen=True)
class TriageDecision:
    url: str
    is_entity_type: bool
    plausible_sector: bool
    fit_score: float | None
    reason: str
    is_own_page: bool | None = None
    is_operating_org: bool | None = None
    actor_type_guess: str | None = None
    hub_matches: tuple[str, ...] = ()
    sector_codes: tuple[str, ...] = ()
    engagement_signals: dict[str, str | None] | None = None
    use_case_fit: dict[str, str | None] | None = None
    condition_evidence: dict[str, str] | None = None
    sector_relevance: float | None = None
    engagement_route: float | None = None
    strategic_ecosystem_value: float | None = None
    distinctiveness: float | None = None
    existing_actor_count: int | None = None
    relevance_signals: dict[str, str | None] | None = None
    is_professional_person_page: bool | None = None
    verdict: str | None = None

    @property
    def accepted(self) -> bool:
        return (
            self.is_entity_type
            and self.plausible_sector
            and self.fit_score is not None
            and self.is_own_page is not False
            and self.is_operating_org is not False
            and self.is_professional_person_page is not False
        )


@dataclass(frozen=True)
class CandidateRecord:
    candidate_id: str
    run_id: str
    entity_type: str
    query: str
    provider: str
    url: str
    title: str | None
    snippet: str | None
    domain: str
    triage_verdict: str
    triage_reason: str | None
    fit_score: float | None
    is_own_page: bool | None = None
    is_operating_org: bool | None = None
    actor_type_guess: str | None = None
    hub_matches: tuple[str, ...] = ()
    sector_codes: tuple[str, ...] = ()
    engagement_signals: dict[str, str | None] | None = None
    use_case_fit: dict[str, str | None] | None = None
    condition_evidence: dict[str, str] | None = None
    sector_relevance: float | None = None
    engagement_route: float | None = None
    strategic_ecosystem_value: float | None = None
    distinctiveness: float | None = None
    existing_actor_count: int | None = None
    relevance_signals: dict[str, str | None] | None = None
    duplicate_of: str | None = None
    gate_fetch: bool | None = None
    page_fetched: bool = False
    rubric: dict[str, object] | None = None
    record_preview: dict[str, object] | None = None
    score_breakdown: dict[str, float] | None = None
    score_band: str | None = None
    rerank_position: int | None = None
    rerank_reason: str | None = None

    @classmethod
    def from_result(
        cls,
        *,
        run_id: str,
        entity_type: str,
        result: SearchResult,
        domain: str,
        triage_verdict: str,
        triage_reason: str | None,
        fit_score: float | None,
        triage_details: TriageDecision | None = None,
        actor_triage: TriageDecision | None = None,
    ) -> CandidateRecord:
        details = triage_details or actor_triage
        return cls(
            candidate_id=str(uuid.uuid4()),
            run_id=run_id,
            entity_type=entity_type,
            query=result.query,
            provider=result.provider,
            url=result.url,
            title=result.title or None,
            snippet=result.snippet or None,
            domain=domain,
            triage_verdict=triage_verdict,
            triage_reason=triage_reason,
            fit_score=fit_score,
            is_own_page=details.is_own_page if details else None,
            is_operating_org=details.is_operating_org if details else None,
            actor_type_guess=details.actor_type_guess if details else None,
            hub_matches=details.hub_matches if details else (),
            sector_codes=details.sector_codes if details else (),
            engagement_signals=details.engagement_signals if details else None,
            use_case_fit=details.use_case_fit if details else None,
            condition_evidence=details.condition_evidence if details else None,
            sector_relevance=details.sector_relevance if details else None,
            engagement_route=details.engagement_route if details else None,
            strategic_ecosystem_value=(
                details.strategic_ecosystem_value if details else None
            ),
            distinctiveness=details.distinctiveness if details else None,
            existing_actor_count=details.existing_actor_count if details else None,
            relevance_signals=details.relevance_signals if details else None,
            gate_fetch=(
                details.is_entity_type
                if entity_type == "actor" and details is not None
                else None
            ),
        )
