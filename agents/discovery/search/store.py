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
            # The event pipeline marks a collapsed duplicate page with the band
            # "duplicate", which ck_search_candidate_score_band does not allow;
            # one such row used to make the whole batch fail to save (seen on
            # the 2026-10-14 live run). A duplicate is recorded by its verdict
            # and duplicate_of link, with no band - it is neither queued nor
            # created.
            if row.get("score_band") == "duplicate":
                row["score_band"] = None
                row["triage_verdict"] = "duplicate"
            rows.append(row)
        if not rows:
            return 0
        self.session.execute(
            text(
                "INSERT INTO search_candidate (candidate_id, run_id, entity_type, query, "
                "provider, url, title, snippet, domain, triage_verdict, triage_reason, fit_score, "
                "duplicate_of, gate_fetch, page_fetched, rubric, record_preview, "
                "score_breakdown, score_band, qualification_paths, "
                "identity_outcome, existing_actor_count, distinctiveness, "
                "rerank_position, rerank_reason) "
                "VALUES (CAST(:candidate_id AS uuid), CAST(:run_id AS uuid), :entity_type, "
                ":query, :provider, :url, :title, :snippet, :domain, :triage_verdict, "
                ":triage_reason, :fit_score, CAST(:duplicate_of AS uuid), :gate_fetch, "
                ":page_fetched, "
                "CAST(:rubric AS jsonb), CAST(:record_preview AS jsonb), "
                "CAST(:score_breakdown AS jsonb), :score_band, "
                "CAST(:qualification_paths AS jsonb), :identity_outcome, "
                ":existing_actor_count, "
                ":distinctiveness, :rerank_position, :rerank_reason)"
            ),
            rows,
        )
        self.session.commit()
        return len(rows)


def attach_light_pull(session, candidate_id: str, *, evidence: dict, read: dict) -> None:
    """Keep a candidate's pre-review Light Pull with it, for Review and admission.

    Stored inside ``record_preview`` (``light_pull_evidence`` per box,
    ``light_pull_read`` for the pages read and the cost), which admission
    already passes to promotion: the canonical facts are written there, by
    the approved writer, only when a person verifies the actor.
    """
    session.execute(
        text(
            "UPDATE search_candidate SET record_preview = "
            "COALESCE(record_preview, '{}'::jsonb) || jsonb_build_object("
            "'light_pull_evidence', CAST(:evidence AS jsonb), "
            "'light_pull_read', CAST(:read AS jsonb)) "
            "WHERE candidate_id = CAST(:candidate_id AS uuid)"
        ),
        {"candidate_id": candidate_id, "evidence": json.dumps(evidence, sort_keys=True),
         "read": json.dumps(read, sort_keys=True)},
    )
