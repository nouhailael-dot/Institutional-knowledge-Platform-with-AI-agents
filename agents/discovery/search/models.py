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
    partner_signals: dict[str, str | None] | None = None
    partner_findability: float | None = None
    distinctiveness: float | None = None
    existing_actor_count: int | None = None
    verdict: str | None = None

    @property
    def accepted(self) -> bool:
        return (
            self.is_entity_type
            and self.plausible_sector
            and self.fit_score is not None
            and self.is_own_page is not False
            and self.is_operating_org is not False
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
    actor_type_guess: str | None = None
    hub_matches: tuple[str, ...] = ()
    sector_codes: tuple[str, ...] = ()
    partner_signals: dict[str, str | None] | None = None
    partner_findability: float | None = None
    distinctiveness: float | None = None
    existing_actor_count: int | None = None

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
        actor_triage: TriageDecision | None = None,
    ) -> CandidateRecord:
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
            actor_type_guess=actor_triage.actor_type_guess if actor_triage else None,
            hub_matches=actor_triage.hub_matches if actor_triage else (),
            sector_codes=actor_triage.sector_codes if actor_triage else (),
            partner_signals=actor_triage.partner_signals if actor_triage else None,
            partner_findability=actor_triage.partner_findability if actor_triage else None,
            distinctiveness=actor_triage.distinctiveness if actor_triage else None,
            existing_actor_count=actor_triage.existing_actor_count if actor_triage else None,
        )
