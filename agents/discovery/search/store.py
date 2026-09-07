"""Persistence for open-web search candidates."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import text

from agents.discovery.search.models import CandidateRecord


class InMemorySearchCandidateStore:
    def __init__(self, *, seen_raw_urls: Iterable[str] | None = None):
        self.candidates: list[CandidateRecord] = []
        self.seen_raw_urls = set(seen_raw_urls or [])

    def has_seen_raw_url(self, url: str) -> bool:
        return url in self.seen_raw_urls

    def write_candidates(self, candidates: Iterable[CandidateRecord]) -> int:
        rows = list(candidates)
        self.candidates.extend(rows)
        return len(rows)


class SQLSearchCandidateStore:
    def __init__(self, session):
        self.session = session

    def has_seen_raw_url(self, url: str) -> bool:
        row = self.session.execute(
            text("SELECT 1 FROM raw_document WHERE url = :url LIMIT 1"),
            {"url": url},
        ).first()
        return row is not None

    def write_candidates(self, candidates: Iterable[CandidateRecord]) -> int:
        rows = [candidate.__dict__ for candidate in candidates]
        if not rows:
            return 0
        self.session.execute(
            text(
                "INSERT INTO search_candidate (candidate_id, run_id, entity_type, query, "
                "provider, url, title, snippet, domain, triage_verdict, triage_reason, fit_score) "
                "VALUES (CAST(:candidate_id AS uuid), CAST(:run_id AS uuid), :entity_type, "
                ":query, :provider, :url, :title, :snippet, :domain, :triage_verdict, "
                ":triage_reason, :fit_score)"
            ),
            rows,
        )
        self.session.commit()
        return len(rows)
