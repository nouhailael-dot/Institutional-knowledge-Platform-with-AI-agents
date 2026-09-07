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

    @property
    def accepted(self) -> bool:
        return self.is_entity_type and self.plausible_sector and self.fit_score is not None


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
        )
