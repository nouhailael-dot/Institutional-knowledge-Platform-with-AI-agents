"""Persistence for open-web search candidates."""

from __future__ import annotations

import json
from collections.abc import Iterable

from sqlalchemy import text

from agents.discovery.search.models import CandidateRecord


class InMemorySearchCandidateStore:
    def __init__(self, *, seen_raw_urls: Iterable[str] | None = None):
        self.candidates: list[CandidateRecord] = []
        self.seen_raw_urls = set(seen_raw_urls or [])

    def has_seen_raw_url(self, url: str) -> bool:
        return url in self.seen_raw_urls

    def load_seen_raw_urls(self) -> set[str]:
        return set(self.seen_raw_urls)

    def write_candidates(self, candidates: Iterable[CandidateRecord]) -> int:
        rows = list(candidates)
        self.candidates.extend(rows)
        return len(rows)


class SQLSearchCandidateStore:
    def __init__(self, session):
        self.session = session
        self._seen_raw_urls: set[str] | None = None

    def load_seen_raw_urls(self) -> set[str]:
        if self._seen_raw_urls is None:
            urls = self.session.execute(
                text("SELECT DISTINCT url FROM raw_document WHERE url IS NOT NULL")
            ).scalars()
            self._seen_raw_urls = {str(url) for url in urls if url}
        return set(self._seen_raw_urls)

    def has_seen_raw_url(self, url: str) -> bool:
        return url in self.load_seen_raw_urls()

    def write_candidates(self, candidates: Iterable[CandidateRecord]) -> int:
        rows = []
        for candidate in candidates:
            row = candidate.__dict__.copy()
            for field in ("rubric", "record_preview", "score_breakdown"):
                row[field] = json.dumps(row[field], sort_keys=True) if row[field] is not None else None
            row["qualification_paths"] = json.dumps(list(candidate.qualification_paths))
            rows.append(row)
        if not rows:
            return 0
        self.session.execute(
            text(
                "INSERT INTO search_candidate (candidate_id, run_id, entity_type, query, "
                "provider, url, title, snippet, domain, triage_verdict, triage_reason, fit_score, "
                "duplicate_of, gate_fetch, page_fetched, rubric, record_preview, "
                "score_breakdown, score_band, qualification_paths, "
                "existing_actor_count, distinctiveness, rerank_position, rerank_reason) "
                "VALUES (CAST(:candidate_id AS uuid), CAST(:run_id AS uuid), :entity_type, "
                ":query, :provider, :url, :title, :snippet, :domain, :triage_verdict, "
                ":triage_reason, :fit_score, CAST(:duplicate_of AS uuid), :gate_fetch, "
                ":page_fetched, "
                "CAST(:rubric AS jsonb), CAST(:record_preview AS jsonb), "
                "CAST(:score_breakdown AS jsonb), :score_band, "
                "CAST(:qualification_paths AS jsonb), :existing_actor_count, "
                ":distinctiveness, :rerank_position, :rerank_reason)"
            ),
            rows,
        )
        self.session.commit()
        return len(rows)
