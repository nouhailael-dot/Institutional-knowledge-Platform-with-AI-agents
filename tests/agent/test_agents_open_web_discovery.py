from __future__ import annotations

import copy
from argparse import Namespace
from datetime import date
from pathlib import Path

import pytest

from agents.common.cost import CostMeter
from agents.common.run_log import InMemoryRunLog
from agents.discovery.search import run as search_run
from agents.discovery.search.models import SearchResult, TriageDecision
from agents.discovery.search.providers import (
    WEB_SEARCH_USD_PER_REQUEST,
    BraveSearchProvider,
    ClaudeWebSearchProvider,
    build_search_provider,
)
from agents.discovery.search.query_generation import (
    QueryBundle,
    QueryGenerator,
    _event_seed_queries,
    load_actor_reference_set,
    normalize_event_geography,
)
from agents.discovery.search.store import InMemorySearchCandidateStore
from agents.discovery.search.triage import SearchTriageClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class StubToolClient:
    def __init__(self, responses: list[dict[str, object]], *, cost_meter=None, cost_usd=0.0):
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []
        self.cost_meter = cost_meter
        self.cost_usd = cost_usd

    def extract_with_tool(self, **kwargs):
        self.calls.append(kwargs)
        if self.cost_meter is not None and self.cost_usd:
            self.cost_meter.add(self.cost_usd, label="stub")
        if not self.responses:
            raise AssertionError("no stub LLM response configured")
        return copy.deepcopy(self.responses.pop(0))


class StaticQueryGenerator:
    def __init__(self, queries: list[str]):
        self.queries = queries

    def generate(self, entity_type, *, session=None, project_root=None):
        return QueryBundle(
            entity_type=entity_type,
            queries=self.queries,
            deterministic_queries=self.queries,
            llm_queries=[],
            reference_count=0,
        )


class StaticSearchProvider:
    name = "stub"

    def __init__(self, results_by_query: dict[str, list[SearchResult]]):
        self.results_by_query = results_by_query
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, *, count: int = 10):
        self.calls.append((query, count))
        return self.results_by_query.get(query, [])


class RecordingTriageClient:
    def __init__(self, score: float = 0.9):
        self.score = score
        self.calls: list[list[SearchResult]] = []

    def triage(self, candidates, *, entity_type, sectors, references):
        self.calls.append(list(candidates))
        return {
            candidate.url: TriageDecision(
                url=candidate.url,
                is_entity_type=True,
                plausible_sector=True,
                fit_score=self.score,
                reason="matches reference set",
            )
            for candidate in candidates
        }


class SequencedTriageClient:
    def __init__(self, responses: list[object]):
        self.responses = list(responses)
        self.calls: list[list[SearchResult]] = []

    def triage(self, candidates, *, entity_type, sectors, references):
        self.calls.append(list(candidates))
        if not self.responses:
            raise AssertionError("no sequenced triage response configured")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class MappingRows:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class CapturingSession:
    def __init__(self, rows):
        self.rows = rows
        self.statements: list[str] = []

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        return MappingRows(self.rows)


class FakeClaudeMessages:
    def __init__(self, responses: list[object]):
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("no fake Claude web-search response configured")
        return copy.deepcopy(self.responses.pop(0))


class FakeClaudeClient:
    def __init__(self, responses: list[object]):
        self.messages = FakeClaudeMessages(responses)


def test_open_web_query_generation_produces_distinct_event_and_actor_queries():
    client = StubToolClient(
        [
            {"queries": ["climate innovation forum 2027", "climate innovation forum 2027"]},
            {"queries": ["water research institute partnerships"]},
        ]
    )
    config = {"people_enabled": False, "forward_window_days": 365}
    actor_session = CapturingSession(
        [
            {
                "actor_id": "3",
                "name": "Clean Lab",
                "actor_type": "research",
                "merged_into_actor_id": None,
                "description": "Water research and field pilots",
                "country": "USA",
            },
        ]
    )

    event_bundle = QueryGenerator(client, config, today=date(2026, 9, 3)).generate(
        "event", session=None, project_root=PROJECT_ROOT
    )
    actor_bundle = QueryGenerator(client, config, today=date(2026, 9, 3)).generate(
        "actor", session=actor_session, project_root=PROJECT_ROOT
    )

    assert event_bundle.queries
    assert actor_bundle.queries
    assert len(event_bundle.queries) == len({query.lower() for query in event_bundle.queries})
    assert len(actor_bundle.queries) == len({query.lower() for query in actor_bundle.queries})


def test_open_web_people_query_path_is_disabled_by_default():
    client = StubToolClient([])
    generator = QueryGenerator(client, {"people_enabled": False})

    with pytest.raises(RuntimeError, match="people discovery is disabled"):
        generator.generate("person", session=None, project_root=PROJECT_ROOT)

    assert client.calls == []


def test_actor_query_generation_requires_database_reference_set():
    client = StubToolClient([])
    generator = QueryGenerator(client, {"people_enabled": False})

    with pytest.raises(RuntimeError, match="non-empty non-aggregate database reference set"):
        generator.generate("actor", session=None, project_root=PROJECT_ROOT)

    assert client.calls == []


def test_actor_reference_set_excludes_aggregates_and_merged_actors():
    session = CapturingSession(
        [
            {"actor_id": "1", "name": "Aggregate Hub", "actor_type": "aggregate"},
            {
                "actor_id": "2",
                "name": "Merged Lab",
                "actor_type": "research",
                "merged_into_actor_id": "winner",
            },
            {
                "actor_id": "3",
                "name": "Clean Lab",
                "actor_type": "research",
                "merged_into_actor_id": None,
            },
        ]
    )

    rows = load_actor_reference_set(session, limit=20)

    assert [row["name"] for row in rows] == ["Clean Lab"]
    sql = "\n".join(session.statements)
    assert "merged_into_actor_id IS NULL" in sql
    assert "lower(actor_type) <> 'aggregate'" in sql


def test_event_geography_normalization_removes_street_addresses_and_postcodes():
    assert (
        normalize_event_geography("12 East 41st Street 7th floor, Manhattan, NY, 10017")
        == "New York"
    )
    assert normalize_event_geography("Rome, Italy") == "Rome"
    assert normalize_event_geography("10017") == ""


def test_generated_event_queries_contain_no_street_addresses_or_postcodes():
    client = StubToolClient(
        [
            {
                "queries": [
                    (
                        '"Water" innovation forum 12 East 41st Street 7th floor, '
                        "Manhattan, NY, 10017 2026"
                    )
                ]
            }
        ]
    )
    session = CapturingSession(
        [
            {
                "event_id": "1",
                "location": "12 East 41st Street 7th floor, Manhattan, NY, 10017",
                "code": "WATER",
                "name": "Future of Water Desalination Innovation Summit",
            }
        ]
    )

    bundle = QueryGenerator(
        client,
        {"people_enabled": False, "forward_window_days": 365},
        today=date(2026, 9, 7),
    ).generate("event", session=session, project_root=PROJECT_ROOT)

    query_text = "\n".join(bundle.queries)
    assert "12 East" not in query_text
    assert "7th floor" not in query_text
    assert "10017" not in query_text
    assert "New York" in query_text


def test_event_seed_queries_use_sector_names_and_representative_terms_not_codes():
    queries = _event_seed_queries(
        [
            {
                "code": "AI",
                "name": "Artificial Intelligence",
                "representative_terms": "machine learning governance",
            }
        ],
        ["New York"],
        date(2026, 9, 7),
        {"forward_window_days": 365},
    )

    query_text = "\n".join(queries)
    assert '"Artificial Intelligence" machine learning governance' in query_text
    assert '"AI"' not in query_text
    assert "AI summit" not in query_text


def test_claude_web_search_provider_parses_multi_block_response_by_type():
    response = _claude_search_response(
        [
            {"type": "text", "text": "Ignore this commentary and https://bad.example"},
            {"type": "server_tool_use", "id": "srv_1", "name": "web_search"},
            {
                "type": "web_search_tool_result",
                "tool_use_id": "srv_1",
                "content": [
                    {
                        "type": "web_search_result",
                        "url": "https://one.example/article",
                        "title": "First Result",
                        "page_age": "September 2026",
                    },
                    {"type": "not_a_search_result", "url": "https://ignored.example"},
                    {
                        "type": "web_search_result",
                        "url": "https://two.example/report",
                        "title": "Second Result",
                        "snippet": "Explicit snippet",
                    },
                ],
            },
            {"type": "text", "text": "More model commentary that must not flow downstream"},
        ],
        input_tokens=100,
        output_tokens=50,
        search_requests=1,
    )
    cost_meter = CostMeter(max_usd=5)
    client = FakeClaudeClient([response])
    provider = ClaudeWebSearchProvider(
        model="claude-haiku-4-5",
        cost_meter=cost_meter,
        input_usd_per_million=1.0,
        output_usd_per_million=5.0,
        client=client,
    )

    results = provider.search("climate finance event", count=10)

    assert [result.as_tuple() for result in results] == [
        (
            "https://one.example/article",
            "First Result",
            "September 2026",
            "claude",
            "climate finance event",
        ),
        (
            "https://two.example/report",
            "Second Result",
            "Explicit snippet",
            "claude",
            "climate finance event",
        ),
    ]
    assert "bad.example" not in str(results)
    assert cost_meter.spent_usd == pytest.approx(WEB_SEARCH_USD_PER_REQUEST + 0.00035)
    request_kwargs = client.messages.calls[0]
    assert request_kwargs["tools"][0]["type"] == "web_search_20250305"
    assert request_kwargs["tools"][0]["allowed_callers"] == ["direct"]


def test_claude_web_search_provider_empty_result_set_returns_empty_list():
    provider = ClaudeWebSearchProvider(
        model="claude-haiku-4-5",
        cost_meter=CostMeter(max_usd=5),
        client=FakeClaudeClient([_claude_search_response([{"type": "text", "text": "No results"}])]),
    )

    assert provider.search("no matches expected") == []


def test_search_triage_client_accepts_wrapped_candidate_list():
    candidate = _result("https://fresh.example/page", "q")
    client = StubToolClient(
        [
            {
                "candidates": {
                    "items": [
                        {
                            "url": candidate.url,
                            "is_entity_type": True,
                            "plausible_sector": True,
                            "fit_score": 0.8,
                            "reason": "specific event page",
                        }
                    ]
                }
            }
        ]
    )

    decisions = SearchTriageClient(client, {}).triage(
        [candidate],
        entity_type="event",
        sectors=[],
        references=[],
    )

    assert decisions[candidate.url].fit_score == 0.8


def test_deterministic_rejections_happen_before_llm_triage(monkeypatch, tmp_path):
    _install_open_web_config(monkeypatch)
    store = InMemorySearchCandidateStore(seen_raw_urls={"https://seen.example/page"})
    provider = StaticSearchProvider(
        {
            "q": [
                _result("https://blocked.example/page", "q"),
                _result("https://known.example/events/one", "q"),
                _result("https://valid.example/privacy/policy", "q"),
                _result("https://seen.example/page", "q"),
            ]
        }
    )
    triage = RecordingTriageClient()

    result = search_run.run_search_triage(
        _args(tmp_path),
        root=PROJECT_ROOT,
        run_log=InMemoryRunLog(),
        store=store,
        search_provider=provider,
        query_generator=StaticQueryGenerator(["q"]),
        triage_client=triage,
    )

    assert result["status"] == "succeeded"
    assert len(store.candidates) == 4
    assert {row.triage_verdict for row in store.candidates} == {"rejected"}
    assert result["stats"]["deterministic_rejected"] == 4
    assert triage.calls == []


def test_every_search_result_gets_candidate_row(monkeypatch, tmp_path):
    _install_open_web_config(monkeypatch)
    store = InMemorySearchCandidateStore()
    provider = StaticSearchProvider(
        {
            "q": [
                _result("https://blocked.example/page", "q"),
                _result("https://fresh.example/profile", "q"),
            ]
        }
    )

    result = search_run.run_search_triage(
        _args(tmp_path, entity="actor"),
        root=PROJECT_ROOT,
        run_log=InMemoryRunLog(),
        store=store,
        search_provider=provider,
        query_generator=StaticQueryGenerator(["q"]),
        triage_client=RecordingTriageClient(score=0.91),
    )

    assert result["status"] == "succeeded"
    assert len(store.candidates) == 2
    assert [row.triage_verdict for row in store.candidates] == ["rejected", "accepted"]
    assert result["stats"]["accepted"] == 1
    assert result["stats"]["rejected"] == 1


def test_max_searches_cap_closes_attention(monkeypatch, tmp_path):
    _install_open_web_config(monkeypatch, max_searches=1)
    provider = StaticSearchProvider({"q1": [], "q2": []})

    result = search_run.run_search_triage(
        _args(tmp_path),
        root=PROJECT_ROOT,
        run_log=InMemoryRunLog(),
        store=InMemorySearchCandidateStore(),
        search_provider=provider,
        query_generator=StaticQueryGenerator(["q1", "q2"]),
        triage_client=RecordingTriageClient(),
    )

    assert result["status"] == "attention"
    assert "max_searches" in result["status_reason"]
    assert provider.calls == [("q1", 10)]


def test_max_candidates_triaged_cap_records_overflow_rows(monkeypatch, tmp_path):
    _install_open_web_config(monkeypatch, max_candidates_triaged=2)
    store = InMemorySearchCandidateStore()
    provider = StaticSearchProvider(
        {
            "q": [
                _result("https://one.example/page", "q"),
                _result("https://two.example/page", "q"),
                _result("https://three.example/page", "q"),
            ]
        }
    )
    triage = RecordingTriageClient(score=0.95)

    result = search_run.run_search_triage(
        _args(tmp_path),
        root=PROJECT_ROOT,
        run_log=InMemoryRunLog(),
        store=store,
        search_provider=provider,
        query_generator=StaticQueryGenerator(["q"]),
        triage_client=triage,
    )

    assert result["status"] == "attention"
    assert "max_candidates_triaged" in result["status_reason"]
    assert len(triage.calls) == 1
    assert [row.url for row in triage.calls[0]] == [
        "https://one.example/page",
        "https://two.example/page",
    ]
    assert len(store.candidates) == 3
    capped_rows = [
        row
        for row in store.candidates
        if row.triage_reason == "max_candidates_triaged cap hit before LLM triage"
    ]
    assert [row.url for row in capped_rows] == ["https://three.example/page"]


def test_every_candidate_sent_to_triage_gets_explicit_verdict(monkeypatch, tmp_path):
    _install_open_web_config(monkeypatch)
    store = InMemorySearchCandidateStore()
    provider = StaticSearchProvider(
        {
            "q": [
                _result("https://one.example/page", "q"),
                _result("https://two.example/page", "q"),
                _result("https://three.example/page", "q"),
            ]
        }
    )

    result = search_run.run_search_triage(
        _args(tmp_path),
        root=PROJECT_ROOT,
        session=CapturingSession([]),
        run_log=InMemoryRunLog(),
        store=store,
        search_provider=provider,
        query_generator=StaticQueryGenerator(["q"]),
        triage_client=RecordingTriageClient(score=0.75),
    )

    assert result["status"] == "succeeded"
    assert len(store.candidates) == 3
    assert {row.triage_verdict for row in store.candidates} == {"accepted"}
    assert all(row.triage_reason for row in store.candidates)


def test_incomplete_triage_retries_missing_candidates_once_then_marks_incomplete(
    monkeypatch,
    tmp_path,
):
    _install_open_web_config(monkeypatch)
    store = InMemorySearchCandidateStore()
    first = _result("https://one.example/page", "q")
    second = _result("https://two.example/page", "q")
    provider = StaticSearchProvider({"q": [first, second]})
    triage = SequencedTriageClient(
        [
            {
                first.url: TriageDecision(
                    url=first.url,
                    is_entity_type=True,
                    plausible_sector=True,
                    fit_score=0.8,
                    reason="specific event",
                )
            },
            {},
        ]
    )

    result = search_run.run_search_triage(
        _args(tmp_path),
        root=PROJECT_ROOT,
        session=CapturingSession([]),
        run_log=InMemoryRunLog(),
        store=store,
        search_provider=provider,
        query_generator=StaticQueryGenerator(["q"]),
        triage_client=triage,
    )

    assert [len(call) for call in triage.calls] == [2, 1]
    assert result["status"] == "attention"
    assert result["stats"]["triage_incomplete"] == 1
    assert {row.url: row.triage_verdict for row in store.candidates} == {
        first.url: "accepted",
        second.url: "triage_incomplete",
    }
    assert store.candidates[1].triage_reason == (
        "triage incomplete: candidate omitted after one retry"
    )


def test_malformed_triage_response_does_not_kill_run(monkeypatch, tmp_path):
    _install_open_web_config(monkeypatch)
    store = InMemorySearchCandidateStore()
    provider = StaticSearchProvider({"q": [_result("https://one.example/page", "q")]})
    triage = SequencedTriageClient(
        [
            TypeError("LLM triage returned non-list candidates"),
            TypeError("LLM triage returned non-list candidates"),
        ]
    )

    result = search_run.run_search_triage(
        _args(tmp_path),
        root=PROJECT_ROOT,
        session=CapturingSession([]),
        run_log=InMemoryRunLog(),
        store=store,
        search_provider=provider,
        query_generator=StaticQueryGenerator(["q"]),
        triage_client=triage,
    )

    assert result["status"] == "attention"
    assert result["stats"]["triage_incomplete"] == 1
    assert len(store.candidates) == 1
    assert store.candidates[0].triage_verdict == "triage_incomplete"
    assert store.candidates[0].triage_reason == (
        "triage incomplete: batch failed after one retry"
    )


def test_max_usd_cap_closes_attention_before_search(monkeypatch, tmp_path):
    _install_open_web_config(monkeypatch, max_usd_per_run=0.01)
    cost_meter = CostMeter(max_usd=0.01)
    client = StubToolClient(
        [{"queries": ["expensive query"]}],
        cost_meter=cost_meter,
        cost_usd=0.02,
    )
    provider = StaticSearchProvider({"expensive query": [_result("https://fresh.example", "q")]})

    result = search_run.run_search_triage(
        _args(tmp_path),
        root=PROJECT_ROOT,
        run_log=InMemoryRunLog(),
        store=InMemorySearchCandidateStore(),
        search_provider=provider,
        llm_client=client,
        cost_meter=cost_meter,
    )

    assert result["status"] == "attention"
    assert "max_usd_per_run" in result["status_reason"]
    assert provider.calls == []


def test_offline_mode_requires_injected_search_provider(monkeypatch, tmp_path):
    _install_open_web_config(monkeypatch)

    with pytest.raises(RuntimeError, match="offline open-web search requires"):
        search_run.run_search_triage(
            _args(tmp_path),
            root=PROJECT_ROOT,
            run_log=InMemoryRunLog(),
            store=InMemorySearchCandidateStore(),
            query_generator=StaticQueryGenerator(["q"]),
            triage_client=RecordingTriageClient(),
        )


def test_claude_search_cost_accumulates_and_ceiling_aborts_run(monkeypatch, tmp_path):
    _install_open_web_config(monkeypatch, provider="claude", max_usd_per_run=0.005)
    store = InMemorySearchCandidateStore()
    client = FakeClaudeClient(
        [
            _claude_search_response(
                [
                    {
                        "type": "web_search_tool_result",
                        "content": [
                            {
                                "type": "web_search_result",
                                "url": "https://fresh.example/page",
                                "title": "Fresh",
                            }
                        ],
                    }
                ],
                search_requests=1,
            )
        ]
    )

    result = search_run.run_search_triage(
        _args(tmp_path, offline=False),
        root=PROJECT_ROOT,
        session=CapturingSession([]),
        run_log=InMemoryRunLog(),
        store=store,
        query_generator=StaticQueryGenerator(["q1", "q2"]),
        triage_client=RecordingTriageClient(),
        search_client=client,
    )

    assert result["status"] == "attention"
    assert "max_usd_per_run" in result["status_reason"]
    assert result["stats"]["cost_usd"] == pytest.approx(WEB_SEARCH_USD_PER_REQUEST)
    assert client.messages.calls
    assert store.candidates == []


def test_search_provider_selected_from_config_and_brave_still_builds(monkeypatch):
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    cost_meter = CostMeter(max_usd=5)

    claude = build_search_provider(
        {"provider": "claude", "search_model": "claude-haiku-4-5"},
        cost_meter=cost_meter,
        client=FakeClaudeClient([]),
    )
    brave = build_search_provider({"provider": "brave"}, cost_meter=cost_meter)

    assert isinstance(claude, ClaudeWebSearchProvider)
    assert claude.model == "claude-haiku-4-5"
    assert isinstance(brave, BraveSearchProvider)


def test_open_web_uses_split_models_for_search_and_triage():
    config = {
        "provider": "claude",
        "search_model": "claude-haiku-4-5",
        "search_llm_pricing": {"input_usd_per_million": 1.0, "output_usd_per_million": 5.0},
        "triage_model": "claude-sonnet-5",
        "triage_llm_pricing": {"input_usd_per_million": 2.0, "output_usd_per_million": 10.0},
    }
    cost_meter = CostMeter(max_usd=5)

    provider = build_search_provider(config, cost_meter=cost_meter, client=FakeClaudeClient([]))
    triage_client = search_run._build_llm_client(config, cost_meter)

    assert isinstance(provider, ClaudeWebSearchProvider)
    assert provider.model == "claude-haiku-4-5"
    assert provider.input_usd_per_million == 1.0
    assert provider.output_usd_per_million == 5.0
    assert triage_client.model == "claude-sonnet-5"
    assert triage_client.input_usd_per_million == 2.0
    assert triage_client.output_usd_per_million == 10.0


def test_missing_brave_key_does_not_fail_claude_configured_run(monkeypatch, tmp_path):
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    _install_open_web_config(monkeypatch, provider="claude")
    store = InMemorySearchCandidateStore()
    client = FakeClaudeClient(
        [
            _claude_search_response(
                [
                    {
                        "type": "web_search_tool_result",
                        "content": [
                            {
                                "type": "web_search_result",
                                "url": "https://fresh.example/profile",
                                "title": "Fresh Result",
                            }
                        ],
                    }
                ],
                search_requests=1,
            )
        ]
    )

    result = search_run.run_search_triage(
        _args(tmp_path, offline=False),
        root=PROJECT_ROOT,
        session=CapturingSession([]),
        run_log=InMemoryRunLog(),
        store=store,
        query_generator=StaticQueryGenerator(["q"]),
        triage_client=RecordingTriageClient(),
        search_client=client,
    )

    assert result["status"] == "succeeded"
    assert [row.url for row in store.candidates] == ["https://fresh.example/profile"]
    assert store.candidates[0].triage_verdict == "accepted"


def test_free_form_claude_search_text_never_reaches_triage(monkeypatch, tmp_path):
    _install_open_web_config(monkeypatch, provider="claude")
    client = FakeClaudeClient(
        [
            _claude_search_response(
                [
                    {
                        "type": "text",
                        "text": "MODEL COMMENTARY: https://commentary.example must be ignored",
                    },
                    {
                        "type": "web_search_tool_result",
                        "content": [
                            {
                                "type": "web_search_result",
                                "url": "https://fresh.example/page",
                                "title": "Fresh",
                                "page_age": "2026",
                            }
                        ],
                    },
                ],
                search_requests=1,
            )
        ]
    )
    triage = RecordingTriageClient()

    search_run.run_search_triage(
        _args(tmp_path, offline=False),
        root=PROJECT_ROOT,
        session=CapturingSession([]),
        run_log=InMemoryRunLog(),
        store=InMemorySearchCandidateStore(),
        query_generator=StaticQueryGenerator(["q"]),
        triage_client=triage,
        search_client=client,
    )

    assert len(triage.calls) == 1
    assert [result.url for result in triage.calls[0]] == ["https://fresh.example/page"]
    assert "commentary.example" not in str(triage.calls[0])


def test_open_web_candidate_sql_migration_exists():
    sql = (PROJECT_ROOT / "agents" / "sql" / "110_open_web_search_candidates.sql").read_text(
        encoding="utf-8"
    )

    assert "CREATE TABLE IF NOT EXISTS search_candidate" in sql
    assert "triage_verdict text NOT NULL" in sql


def _args(tmp_path: Path, *, entity: str = "event", offline: bool = True) -> Namespace:
    return Namespace(
        entity=entity,
        live=False,
        offline=offline,
        report_out=str(tmp_path / f"open-web-{entity}.md"),
    )


def _result(url: str, query: str) -> SearchResult:
    return SearchResult(
        url=url,
        title=f"Title for {url}",
        snippet="Snippet",
        provider="stub",
        query=query,
    )


def _install_open_web_config(monkeypatch, **overrides) -> None:
    open_web = {
        "provider": "claude",
        "results_per_query": 10,
        "triage_batch_size": 20,
        "max_searches": 40,
        "max_candidates_triaged": 200,
        "max_usd_per_run": 5.00,
        "forward_window_days": 365,
        "people_enabled": False,
        "accept_floor": {"event": 0.60, "actor": 0.70, "person": 0.95},
        "blocklist_domains": ["blocked.example"],
        "non_content_path_fragments": ["/privacy"],
        "search_model": "claude-haiku-4-5",
        "search_llm_pricing": {"input_usd_per_million": 1.0, "output_usd_per_million": 5.0},
        "triage_model": "claude-sonnet-5",
        "triage_llm_pricing": {"input_usd_per_million": 2.0, "output_usd_per_million": 10.0},
    }
    open_web.update(overrides)
    config = {
        "open_web_discovery": open_web,
        "sources": {"known": {"listing_url": "https://known.example/events"}},
    }
    monkeypatch.setattr(search_run, "load_sources_config", lambda root=None: config)


def _claude_search_response(
    content: list[dict[str, object]],
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    search_requests: int = 0,
) -> object:
    return type(
        "FakeClaudeResponse",
        (),
        {
            "content": content,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "server_tool_use": {"web_search_requests": search_requests},
            },
        },
    )()
