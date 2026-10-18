"""Actor discovery runs only for what a person asked for.

"For three months keep me updated on actors in energy in the Northeast,
especially battery storage" must search for exactly that, judge candidates
against exactly that, and add no more than the request allows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from agents.collection.subscriptions import Subscription
from agents.discovery.search.actor_quality import (
    ACCEPT,
    REJECT,
    REVIEW,
    QualityConfig,
    Scope,
    assess_actor,
    mentions_focus,
)
from agents.discovery.search.discovery_request import (
    DiscoveryRequest,
    DiscoveryRequestError,
    apply_new_actor_cap,
    request_actor_queries,
)
from agents.discovery.search.phase2 import _with_found_for_topic

SECTORS = [{"code": "ENERGY", "name": "Energy Transition"}, {"code": "AGRI", "name": "Agriculture"}]


def _subscription(**overrides) -> Subscription:
    base = {
        "subscription_id": "req-1",
        "start_date": date(2026, 10, 1),
        "end_date": date(2026, 12, 31),
        "cadence": "weekly",
        "requested_via": "discovery_page",
        "title": "Energy actors in the Northeast",
        "sector_codes": ("ENERGY",),
        "region_code": "northeast",
        "focus_terms": ("battery storage",),
        "max_new_actors_per_run": 5,
    }
    return Subscription(**{**base, **overrides})


# ----------------------------------------------------------- the request itself

def test_a_region_request_searches_its_states():
    request = DiscoveryRequest.from_subscription(_subscription())
    assert set(request.states) == {"CT", "ME", "MA", "NH", "NY", "RI", "VT"}
    assert "New York" in request.geographies()
    assert request.max_new_actors == 5


def test_a_state_and_city_request_searches_that_place():
    request = DiscoveryRequest.from_subscription(
        _subscription(region_code=None, state_code="Texas", city="Houston"))
    assert request.states == ("TX",)
    assert request.geographies() == ["Houston Texas"]


def test_a_request_by_topic_searches_that_topics_sector():
    request = DiscoveryRequest.from_subscription(
        _subscription(sector_codes=(), topic_ids=("t-agri",)),
        topic_codes={"t-agri": "AGRI"},
    )
    assert request.sector_codes == ("AGRI",)


@pytest.mark.parametrize("overrides", [
    {"region_code": "atlantis"},
    {"region_code": None, "state_code": "Narnia"},
])
def test_an_unknown_place_is_refused_rather_than_guessed(overrides):
    with pytest.raises(DiscoveryRequestError):
        DiscoveryRequest.from_subscription(_subscription(**overrides))


def test_an_unknown_topic_is_refused():
    with pytest.raises(DiscoveryRequestError, match="unknown topic"):
        DiscoveryRequest.from_subscription(_subscription(sector_codes=(), topic_ids=("t-x",)))


# -------------------------------------------------------------------- queries

def test_queries_are_about_the_request_and_nothing_else():
    request = DiscoveryRequest.from_subscription(_subscription())
    queries, metadata = request_actor_queries(request, SECTORS, max_queries=20)
    assert 0 < len(queries) <= 20
    assert all("battery storage" in q for q in queries)
    assert not any("agricultur" in q.lower() for q in queries)
    states = ("Connecticut", "Maine", "Massachusetts", "New Hampshire", "New York",
              "Rhode Island", "Vermont")
    assert all(any(state in q for state in states) for q in queries)
    assert metadata["selected_hubs"] == []          # no hub grid at all
    assert metadata["discovery_request"]["title"] == "Energy actors in the Northeast"
    assert metadata["use_case_queries"]


def test_without_sub_topic_terms_the_topic_name_is_searched():
    request = DiscoveryRequest.from_subscription(_subscription(focus_terms=()))
    queries, _ = request_actor_queries(request, SECTORS, max_queries=8)
    assert all("energy transition" in q for q in queries)


def test_a_cap_trims_depth_not_whole_states():
    request = DiscoveryRequest.from_subscription(_subscription())
    queries, _ = request_actor_queries(request, SECTORS, max_queries=12)
    states_reached = {s for s in request.geographies() if any(s in q for q in queries)}
    assert len(states_reached) == len(request.geographies())


def test_the_query_generator_uses_the_request_instead_of_the_hub_grid(tmp_path):
    from pathlib import Path

    from agents.discovery.search.query_generation import QueryGenerator

    request = DiscoveryRequest.from_subscription(_subscription())
    root = Path(__file__).resolve().parents[2]
    bundle = QueryGenerator(None, {"request_query_limit": 10}).generate(
        "actor", session=None, project_root=root, request=request)
    assert bundle.metadata["discovery_request"]["subscription_id"] == "req-1"
    assert all("battery storage" in q for q in bundle.queries)


# ---------------------------------------------------------------- the judging

RUBRIC = {
    name: {"present": True, "evidence": "Runs grid-scale battery storage pilots with utilities."}
    for name in ("own_organisational_page", "real_operating_entity", "use_cases",
                 "research_development_or_programmes", "partnerships_or_tech_transfer",
                 "sector_coverage")
}
RECORD = {
    "name": "Northeast Storage Lab", "website": "https://nestorage.org",
    "description": "Northeast Storage Lab is a research centre in Boston. It tests grid-scale "
                   "battery systems with regional utilities.",
    "state": "Massachusetts",
}


def _verdict(record=RECORD, rubric=RUBRIC, sectors=("ENERGY",)):
    request = DiscoveryRequest.from_subscription(_subscription())
    return assess_actor(score=0.92, page_url="https://nestorage.org/about", record=record,
                        rubric=rubric, config=QualityConfig(),
                        scope=request.quality_scope(), record_sector_codes=sectors)


def test_a_strong_on_request_actor_is_accepted():
    assert _verdict().band == ACCEPT


def test_a_state_written_as_a_name_is_still_checked_against_the_region():
    verdict = _verdict(record={**RECORD, "state": "California"})
    assert verdict.band == REJECT
    assert "outside_requested_region" in verdict.gates_failed


def test_a_region_alone_bounds_the_area():
    scope = Scope(sector_codes=("ENERGY",), region_code="northeast")
    assert "NY" in scope.allowed_states and "TX" not in scope.allowed_states


def test_an_actor_that_never_touches_the_sub_topic_is_held_not_accepted():
    off_focus = {k: {**v, "evidence": "Runs offshore wind training programmes."}
                 for k, v in RUBRIC.items()}
    record = {**RECORD, "description": "Northeast Wind Lab is a research centre in Boston. "
                                       "It trains offshore wind technicians."}
    verdict = _verdict(record=record, rubric=off_focus)
    assert verdict.band == REVIEW
    assert "focus_unconfirmed" in verdict.gates_failed


def test_focus_matching_uses_word_stems():
    assert mentions_focus(("battery storage",), {"description": "Batteries and storage."}, {})
    assert not mentions_focus(("battery storage",), {"description": "Battery recycling."}, {})


# ----------------------------------------------------- the topic and the reason

def test_why_it_matched_names_the_request():
    context = {"candidate_topics": {"https://nestorage.org/about": {
        "topic_id": "t-energy", "code": "ENERGY",
        "request_title": "Energy actors in the Northeast"}}}
    record = _with_found_for_topic(dict(RECORD), context, "https://nestorage.org/about",
                                   ("ENERGY",), RUBRIC)
    assert record["topic_id"] == "t-energy"
    assert record["match_strength"] == "strong"
    assert "discovery request 'Energy actors in the Northeast'" in record["match_reason"]
    assert record["match_reason"].startswith("Runs grid-scale battery storage")


# ------------------------------------------------------------------- the cap

@dataclass(frozen=True)
class _Candidate:
    candidate_id: str
    url: str
    score_band: str | None
    fit_score: float | None
    triage_verdict: str = "review"
    triage_reason: str | None = None


def test_one_run_adds_no_more_than_the_request_allows():
    candidates = [
        _Candidate("a", "u/a", "review", 0.80),
        _Candidate("b", "u/b", "auto_high", 0.90),
        _Candidate("c", "u/c", "review", 0.60),
        _Candidate("d", "u/d", "auto_low", 0.20, "rejected"),
        _Candidate("e", "u/e", "review", 0.70),
    ]
    result, held = apply_new_actor_cap(candidates, 2)
    assert held == 2
    bands = {c.candidate_id: c.score_band for c in result}
    assert bands == {"a": "review", "b": "auto_high", "c": None, "d": "auto_low", "e": None}
    capped = next(c for c in result if c.candidate_id == "c")
    assert capped.triage_verdict == "capped" and "at most 2" in capped.triage_reason
    assert [c.candidate_id for c in result] == ["a", "b", "c", "d", "e"]  # order kept


# ------------------------------------------- the real pipeline, run for a request

def test_a_requested_run_searches_only_what_was_asked(monkeypatch, tmp_path):
    """run_search_triage with a request: the hub grid is never consulted."""

    from argparse import Namespace
    from pathlib import Path

    from agents.common.run_log import InMemoryRunLog
    from agents.discovery.search import run as search_run
    from agents.discovery.search.query_generation import QueryGenerator
    from agents.discovery.search.store import InMemorySearchCandidateStore
    from tests.agent.test_agents_open_web_discovery import (
        RecordingTriageClient,
        StaticSearchProvider,
        _install_open_web_config,
    )

    _install_open_web_config(monkeypatch, request_query_limit=8, fetch_enabled=False)
    root = Path(__file__).resolve().parents[2]
    request = DiscoveryRequest.from_subscription(_subscription())
    provider = StaticSearchProvider({})
    args = Namespace(entity="actor", live=False, offline=True, discovery_request=request,
                     report_out=str(tmp_path / "r.md"),
                     rejection_report_out=str(tmp_path / "rej.md"),
                     audit_out=str(tmp_path / "a.csv"))
    result = search_run.run_search_triage(
        args, root=root, run_log=InMemoryRunLog(), store=InMemorySearchCandidateStore(),
        search_provider=provider, query_generator=QueryGenerator(None, {"request_query_limit": 8}),
        triage_client=RecordingTriageClient(),
    )
    searched = [query for query, _ in provider.calls]
    assert searched and len(searched) <= 8
    assert all("battery storage" in q for q in searched)
    assert result["stats"]["discovery_request_title"] == "Energy actors in the Northeast"


def test_a_request_cannot_scope_event_discovery(monkeypatch, tmp_path):
    from argparse import Namespace
    from pathlib import Path

    from agents.common.run_log import InMemoryRunLog
    from agents.discovery.search import run as search_run
    from agents.discovery.search.store import InMemorySearchCandidateStore
    from tests.agent.test_agents_open_web_discovery import (
        StaticSearchProvider,
        _install_open_web_config,
    )

    _install_open_web_config(monkeypatch)
    args = Namespace(entity="event", live=False, offline=True,
                     discovery_request=DiscoveryRequest.from_subscription(_subscription()),
                     report_out=str(tmp_path / "r.md"), rejection_report_out=None,
                     audit_out=str(tmp_path / "a.csv"))
    with pytest.raises(ValueError, match="actor discovery only"):
        search_run.run_search_triage(
            args, root=Path(__file__).resolve().parents[2], run_log=InMemoryRunLog(),
            store=InMemorySearchCandidateStore(), search_provider=StaticSearchProvider({}),
            query_generator=object(), triage_client=object(),
        )


# --------------------------------------------- events stay scheduled, US only

@pytest.mark.parametrize(("country", "outside"), [
    ("Indonesia", True), ("Australia", True), ("Canada", True),
    ("USA", False), ("United States", False), ("U.S.A.", False), ("US", False),
    ("", False), (None, False),
])
def test_an_event_is_out_of_scope_only_when_its_page_names_another_country(country, outside):
    from agents.discovery.search.phase2 import _event_explicitly_outside_us

    assert _event_explicitly_outside_us({"country": country}) is outside


# --------------------------------- accepted actors are verified, and labelled so

class _RecordingSession:
    def __init__(self):
        self.statements = []

    def execute(self, statement, params=None):
        self.statements.append((str(statement), dict(params or {})))


def test_an_agent_verification_is_labelled_and_states_its_reasons(monkeypatch):
    from agents.enrichment import decisions

    session = _RecordingSession()
    monkeypatch.setattr(decisions, "execute_canonical_write",
                        lambda s, stmt, params: s.execute(stmt, params))
    decisions.record_agent_auto_verification(
        session, actor_id="a-1", topic_id="t-1", reason="Accepted: score 0.92 ...")
    sql, params = session.statements[0]
    assert "'agent_auto_accept'" in sql and "'verified'" in sql
    assert params["decided_by"] == "discovery-agent"
    with pytest.raises(ValueError, match="reasons"):
        decisions.record_agent_auto_verification(session, actor_id="a", topic_id=None, reason=" ")


def test_promote_verifies_only_what_the_agent_accepted():
    """The verify-item path stays for everything not explicitly accepted."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "agents/discovery/promote.py").read_text(
        encoding="utf-8")
    branch = source[source.index("auto_accept = str("):source.index('_mapping_step(route, trace, "verify_actor")')]
    assert "record_agent_auto_verification" in branch
    assert "_insert_verify_actor_review" in branch


def test_migration_560_only_lets_the_agent_verify_with_reasons():
    from pathlib import Path

    sql = (Path(__file__).resolve().parents[2]
           / "agents/sql/560_v2_agent_auto_verification.sql").read_text(encoding="utf-8")
    block = sql[sql.index("decision_origin = 'agent_auto_accept'"):]
    assert "decision = 'verified'" in block[:300]
    assert "NULLIF(btrim(reason), '') IS NOT NULL" in block[:400]


def test_a_requested_run_carries_the_database_actor_types_to_page_scoring(monkeypatch):
    """Found by the first live run: without them the rubric stage refuses to start."""
    from pathlib import Path

    from agents.discovery.search import query_generation

    monkeypatch.setattr(query_generation, "load_actor_types",
                        lambda session: ["university", "company"])
    request = DiscoveryRequest.from_subscription(_subscription())
    bundle = query_generation.QueryGenerator(None, {"request_query_limit": 8}).generate(
        "actor", session=object(), project_root=Path(__file__).resolve().parents[2],
        request=request)
    assert bundle.metadata["actor_type_enum"] == ["university", "company"]


def test_a_duplicate_event_page_no_longer_stops_the_batch_saving():
    from dataclasses import replace

    from agents.discovery.search.models import CandidateRecord, SearchResult
    from agents.discovery.search.store import SQLSearchCandidateStore

    class Session:
        def __init__(self):
            self.rows = None

        def execute(self, statement, rows):
            self.rows = rows

        def commit(self):
            pass

    result = SearchResult(url="https://x.example/e", title="t", snippet="s",
                          provider="stub", query="q")
    duplicate = replace(
        CandidateRecord.from_result(run_id="00000000-0000-4000-8000-000000000001",
                                    entity_type="event", result=result, domain="x.example",
                                    triage_verdict="accepted", triage_reason="r", fit_score=0.8),
        score_band="duplicate", duplicate_of="00000000-0000-4000-8000-000000000002")
    session = Session()
    assert SQLSearchCandidateStore(session).write_candidates([duplicate]) == 1
    row = session.rows[0]
    assert row["score_band"] is None and row["triage_verdict"] == "duplicate"
    assert row["duplicate_of"] == "00000000-0000-4000-8000-000000000002"
