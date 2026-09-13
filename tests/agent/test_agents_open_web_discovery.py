from __future__ import annotations

import copy
import json
from argparse import Namespace
from datetime import date
from pathlib import Path

import pytest

from agents.common.config import load_sources_config
from agents.common.cost import CostMeter
from agents.common.run_log import InMemoryRunLog
from agents.discovery.search import run as search_run
from agents.discovery.search.models import CandidateRecord, SearchResult, TriageDecision
from agents.discovery.search.providers import (
    WEB_SEARCH_USD_PER_REQUEST,
    BraveSearchProvider,
    ClaudeWebSearchProvider,
    build_search_provider,
)
from agents.discovery.search.query_generation import (
    QueryBundle,
    QueryGenerator,
    _actor_grid_queries,
    _actor_type_query_phrase,
    _event_seed_queries,
    _hub_geographies,
    _hub_theme,
    _representative_terms_from_titles,
    load_actor_query_hubs,
    load_actor_reference_set,
    load_actor_types,
    normalize_event_geography,
)
from agents.discovery.search.store import InMemorySearchCandidateStore, SQLSearchCandidateStore
from agents.discovery.search.triage import (
    ACTOR_REJECTION_CONDITION_NAMES,
    ACTOR_USE_CASE_NAMES,
    ENGAGEMENT_ROUTE_SIGNAL_NAMES,
    SearchTriageClient,
    actor_distinctiveness_score,
    actor_engagement_route_score,
    blocklist_domains_for_entity,
    deterministic_rejection,
    load_actor_hub_sector_counts,
    load_actor_triage_reference_examples,
    normalized_domain,
)

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
        actor_fields = {}
        if entity_type == "actor":
            actor_fields = {
                "is_own_page": True,
                "is_operating_org": True,
                "engagement_signals": {
                    name: (
                        "Membership programme provides a route into the organisation"
                        if name == "memberships"
                        else None
                    )
                    for name in ENGAGEMENT_ROUTE_SIGNAL_NAMES
                },
                "use_case_fit": {
                    name: (
                        "Public programme supports this use case"
                        if name in {"learning_expeditions", "corporate_engagement"}
                        else None
                    )
                    for name in ACTOR_USE_CASE_NAMES
                },
                "condition_evidence": {
                    name: "Evidence supports this condition"
                    for name in ACTOR_REJECTION_CONDITION_NAMES
                },
                "sector_relevance": 0.8,
                "engagement_route": 0.8,
                "strategic_ecosystem_value": 0.8,
            }
        return {
            candidate.url: TriageDecision(
                url=candidate.url,
                is_entity_type=True,
                plausible_sector=True,
                fit_score=self.score,
                reason="matches reference set",
                **actor_fields,
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


class ScalarRows:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def __iter__(self):
        return iter(self.rows)


class ScalarSession:
    def __init__(self, rows):
        self.rows = rows
        self.statements: list[str] = []

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        return ScalarRows(self.rows)


class RoutedSession:
    def __init__(self, responses: list[tuple[str, list[dict[str, object]]]]):
        self.responses = responses
        self.statements: list[str] = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        for fragment, rows in self.responses:
            if fragment in sql:
                return MappingRows(rows)
        return MappingRows([])


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
        ]
    )
    config = {"people_enabled": False, "forward_window_days": 365, "max_searches": 6}
    actor_session = _actor_query_session()

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
    assert actor_bundle.llm_queries == []


def test_open_web_people_query_path_is_disabled_by_default():
    client = StubToolClient([])
    generator = QueryGenerator(client, {"people_enabled": False})

    with pytest.raises(RuntimeError, match="people discovery is disabled"):
        generator.generate("person", session=None, project_root=PROJECT_ROOT)

    assert client.calls == []


def test_actor_query_generation_requires_actor_types_and_hubs():
    client = StubToolClient([])
    generator = QueryGenerator(client, {"people_enabled": False})

    with pytest.raises(RuntimeError, match="at least one searchable actor_type"):
        generator.generate("actor", session=None, project_root=PROJECT_ROOT)

    assert client.calls == []


def test_actor_query_generation_uses_hub_grid_not_reference_names_or_descriptions():
    client = StubToolClient([])
    session = _actor_query_session()

    bundle = QueryGenerator(
        client,
        {"people_enabled": False, "max_searches": 8, "actor_query_rotation_seed": 0},
        today=date(2026, 9, 7),
    ).generate("actor", session=session, project_root=PROJECT_ROOT)

    query_text = "\n".join(bundle.queries).lower()
    assert "albemarle" not in query_text
    assert "allen institute" not in query_text
    assert "soil microbiome ecology" not in query_text
    assert "rhizosphere biology" not in query_text
    assert "corporate_rd_lab" not in query_text
    assert "corporate R&D lab water Boulder Colorado" in bundle.queries
    assert "aggregate" not in query_text
    assert client.calls == []
    assert not any("actor_id::text" in sql for sql in session.statements)


def test_actor_types_are_read_from_database_and_converted_to_search_words():
    session = RoutedSession(
        [
            (
                "SELECT DISTINCT actor_type",
                [
                    {"actor_type": "aggregate"},
                    {"actor_type": "other"},
                    {"actor_type": "corporate_rd_lab"},
                    {"actor_type": "university_lab"},
                    {"actor_type": "venture_capital"},
                ],
            )
        ]
    )

    actor_types = load_actor_types(session)

    assert actor_types == ["corporate_rd_lab", "university_lab", "venture_capital"]
    assert _actor_type_query_phrase("corporate_rd_lab") == "corporate R&D lab"
    assert _actor_type_query_phrase("venture_capital") == "venture capital"


def test_actor_query_grid_samples_thinnest_hubs_and_excludes_mining_hubs():
    session = _actor_query_session()

    hubs = load_actor_query_hubs(session)
    queries, metadata = _actor_grid_queries(
        ["corporate_rd_lab", "university_lab"],
        hubs,
        max_queries=4,
        rotation_seed=0,
    )

    assert [hub["name"] for hub in hubs] == [
        "Colorado Water Hub (Boulder- Denver- Front Range)",
        "Houston Specialty Chemicals Hub",
    ]
    assert all("Mining Hubs" not in str(hub) for hub in hubs)
    assert queries == [
        "corporate R&D lab water Boulder Colorado",
        "university lab specialty chemicals Houston",
        "university lab water Boulder Colorado",
        "corporate R&D lab specialty chemicals Houston",
    ]
    assert metadata["query_grid_size"] == 8
    assert metadata["selected_hubs"] == [
        {
            "name": "Colorado Water Hub (Boulder- Denver- Front Range)",
            "actor_count": 1,
            "theme": "water",
            "geographies": ["Boulder Colorado"],
            "actor_types": ["corporate R&D lab", "university lab"],
            "actor_type_groups": [
                "company / industrial operator",
                "research organization",
            ],
            "query_count": 2,
        },
        {
            "name": "Houston Specialty Chemicals Hub",
            "actor_count": 12,
            "theme": "specialty chemicals",
            "geographies": ["Houston"],
            "actor_types": ["university lab", "corporate R&D lab"],
            "actor_type_groups": [
                "research organization",
                "company / industrial operator",
            ],
            "query_count": 2,
        },
    ]


def test_actor_query_grid_round_robins_forty_queries_across_forty_hubs():
    actor_types = _actor_types_from_evidence_report()
    hubs = _round_robin_hubs(48)

    queries, metadata = _actor_grid_queries(
        actor_types,
        hubs,
        max_queries=40,
        rotation_seed=0,
    )

    query_hubs = [item["hub_name"] for item in metadata["query_plan"]]
    expected_first_forty = [
        f"Hub {index:02d} Water Hub (City {index:02d})"
        for index in range(40)
    ]
    assert len(queries) == 40
    assert len(set(query_hubs)) == 40
    assert metadata["distinct_hubs_covered"] == 40
    assert query_hubs == expected_first_forty
    assert all("Mining Hubs" not in query for query in queries)
    assert all(not query.lower().startswith("other ") for query in queries)
    assert all(
        not query.lower().startswith(
            (
                "intergovernmental organization ",
                "multilateral development bank ",
                "un agency ",
                "un committee ",
                "un programme ",
                "un secretariat ",
            )
        )
        for query in queries
    )


def test_actor_hub_geography_never_uses_full_or_institutional_label():
    rows = [
        {
            "hub_id": "materials",
            "name": "Illinois Midwest Advanced Materials and Catalysis Hub",
            "actor_count": 1,
            "theme": "specialty chemicals",
        },
        {
            "hub_id": "health",
            "name": "Midwest Clinical & Translational Health Hub (Great Lakes Medical Corridor)",
            "actor_count": 2,
            "theme": "health",
        },
        {
            "hub_id": "water",
            "name": "California Water Hub (UC Davis - Berkeley - Stanford)",
            "actor_count": 3,
            "theme": "water",
            "primary_city": "UC Davis",
            "state": "California",
        },
    ]
    hubs = [
        {**row, "geographies": _hub_geographies(str(row["name"]), row=row)}
        for row in rows
    ]

    queries, metadata = _actor_grid_queries(
        ["company", "un_agency", "other"],
        hubs,
        max_queries=3,
        rotation_seed=0,
    )

    assert queries == [
        "company specialty chemicals Illinois Midwest",
        "company health Great Lakes Medical Corridor",
        "company water California",
    ]
    for item in metadata["query_plan"]:
        assert item["hub_name"] not in item["query"]
        assert len(item["geography"]) < len(item["hub_name"])

    assert _hub_geographies("New York City AI Hub (Columbia - NYC - Cornell Tech)") == [
        "New York City"
    ]
    assert _hub_geographies("California Clean Energy Hub") == ["California"]
    assert _hub_geographies("Boston- Cambridge Academic Medical Hub") == [
        "Boston Cambridge"
    ]


@pytest.mark.parametrize(
    ("hub_name", "theme"),
    [
        ("Illinois Midwest Ag Corridor (Urbana-Champaign + Chicago)", "agriculture"),
        ("Texas A&M / College Station - Texas Ag Corridor", "agriculture"),
        ("Missouri - St. Louis Plant Science & Ag-Biotech Hub", "agriculture"),
        (
            "Baltimore-Washington NIC Corridor (Baltimore - Bethesda - Washington D.C. - Rockville)",
            "health",
        ),
    ],
)
def test_actor_query_theme_parser_covers_all_real_hub_labels(hub_name, theme):
    assert _hub_theme(hub_name) == theme


def test_actor_query_grid_finishes_first_hub_pass_before_second_queries():
    actor_types = _actor_types_from_evidence_report()
    hubs = _round_robin_hubs(48)

    _queries, metadata = _actor_grid_queries(
        actor_types,
        hubs,
        max_queries=52,
        rotation_seed=0,
    )

    query_hubs = [item["hub_name"] for item in metadata["query_plan"]]
    expected_first_pass = [
        f"Hub {index:02d} Water Hub (City {index:02d})"
        for index in range(48)
    ]
    assert query_hubs[:48] == expected_first_pass
    assert len(set(query_hubs[:48])) == 48
    assert query_hubs[48:52] == expected_first_pass[:4]


def test_actor_type_subset_is_small_and_rotates_across_runs():
    actor_types = _actor_types_from_evidence_report()
    hubs = _round_robin_hubs(48)

    _queries_a, metadata_a = _actor_grid_queries(
        actor_types,
        hubs,
        max_queries=96,
        rotation_seed=0,
    )
    _queries_b, metadata_b = _actor_grid_queries(
        actor_types,
        hubs,
        max_queries=96,
        rotation_seed=1,
    )

    full_type_count = len(
        {_actor_type_query_phrase(actor_type) for actor_type in actor_types}
    )
    actor_type_counts = [
        len(hub["actor_types"]) for hub in metadata_a["selected_hubs"]
    ]
    assert max(actor_type_counts) <= 3
    assert max(actor_type_counts) < full_type_count
    assert metadata_a["selected_hubs"][0]["actor_types"] != metadata_b["selected_hubs"][0]["actor_types"]
    assert metadata_a["actor_type_rotation_groups"]


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
    assert '"Artificial Intelligence" machine learning' in query_text
    assert "governance" not in query_text
    assert '"AI"' not in query_text
    assert "AI summit" not in query_text


def test_representative_terms_filter_noise_and_cap_to_two_terms():
    water_terms = _representative_terms_from_titles(
        [
            "Water AWWA and Salinity Summit",
            "Water Technology Innovation Forum",
            "Water Desalination Forum",
        ],
        sector_name="Water",
    )
    healthcare_terms = _representative_terms_from_titles(
        ["Healthcare Health Expo ADLM"],
        sector_name="Healthcare",
    )
    chemicals_terms = _representative_terms_from_titles(
        ["Chemical America Specialty Chemicals Exhibition"],
        sector_name="Specialty Chemicals",
    )

    assert water_terms == ["salinity", "technology"]
    assert len(water_terms) <= 2
    assert {"water", "awwa", "and"}.isdisjoint(water_terms)
    assert healthcare_terms == []
    assert chemicals_terms == []


def test_open_web_triage_token_budget_matches_configured_batch_size():
    config = load_sources_config(PROJECT_ROOT)["open_web_discovery"]
    batch_size = int(config["triage_batch_size"])
    actor_batch_size = int(config["actor_triage_batch_size"])
    max_tokens = int(config["triage_max_tokens"])

    assert batch_size == 8
    assert actor_batch_size == 4
    assert max_tokens >= 8000
    assert max_tokens >= batch_size * 1000
    evidence_chars_per_actor = (
        len(ENGAGEMENT_ROUTE_SIGNAL_NAMES)
        + len(ACTOR_USE_CASE_NAMES)
        + len(ACTOR_REJECTION_CONDITION_NAMES)
    ) * 240
    estimated_structure_chars_per_actor = 300 + 1200
    estimated_actor_tokens = (
        actor_batch_size
        * (evidence_chars_per_actor + estimated_structure_chars_per_actor)
        // 4
    )
    assert estimated_actor_tokens == 6060
    assert estimated_actor_tokens < max_tokens
    assert config["actor_sector_relevance_floor"] == pytest.approx(0.35)
    assert config["actor_engagement_route_floor"] == pytest.approx(0.20)
    assert config["actor_strategic_ecosystem_value_floor"] == pytest.approx(0.35)
    assert config["actor_fit_weights"] == {
        "sector_relevance": 0.30,
        "engagement_route": 0.35,
        "strategic_ecosystem_value": 0.25,
        "distinctiveness": 0.10,
    }


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

    decisions = SearchTriageClient(client, {"triage_max_tokens": 8000}).triage(
        [candidate],
        entity_type="event",
        sectors=[],
        references=[],
    )

    assert decisions[candidate.url].fit_score == 0.8
    assert client.calls[0]["max_tokens"] == 8000


def test_search_triage_client_accepts_url_keyed_candidate_mapping():
    candidate = _result("https://fresh.example/page", "q")
    client = StubToolClient(
        [
            {
                "candidates": {
                    candidate.url: {
                        "is_entity_type": True,
                        "plausible_sector": True,
                        "fit_score": 0.82,
                        "reason": "specific event page",
                    }
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

    assert decisions[candidate.url].fit_score == 0.82


def test_search_triage_client_actor_prompt_requires_organisation_own_page():
    candidate = _result("https://fresh.example/about", "q")
    client = StubToolClient(
        [
            {
                "candidates": [
                    {
                        "url": candidate.url,
                        "is_entity_type": False,
                        "plausible_sector": False,
                        "fit_score": None,
                        "reason": "not the organisation's own page",
                    }
                ]
            }
        ]
    )

    SearchTriageClient(client, {}).triage(
        [candidate],
        entity_type="actor",
        sectors=[],
        references=[
            {
                "actor_id": "internal-id",
                "name": "Reference Lab",
                "actor_type": "university_lab",
                "sectors": ["water"],
                "description": "must not leave the application",
                "website": "https://reference.example",
            }
        ],
    )

    # Stable rules now travel in the cached prefix block; only candidates vary.
    cached_payload = json.loads(client.calls[0]["cached_user"])
    assert "not published by the organisation itself" in cached_payload["actor_quality_rule"]
    assert "not the organisation's own page" in cached_payload["actor_quality_rule"]
    assert "news or press page on own domain" in cached_payload["actor_quality_rule"]
    assert cached_payload["reference_examples"] == [
        {
            "name": "Reference Lab",
            "actor_type": "university_lab",
            "sectors": ["WATER"],
        }
    ]
    schema = client.calls[0]["input_schema"]["properties"]["candidates"]["items"]
    assert {
        "is_own_page",
        "is_operating_org",
        "actor_type_guess",
        "hub_matches",
        "sector_codes",
        "engagement_signals",
        "use_case_fit",
        "condition_evidence",
        "sector_relevance",
        "strategic_ecosystem_value",
        "reason",
    }.issubset(schema["properties"])
    assert "complementarity" not in json.dumps(schema).lower()
    signal_schema = schema["properties"]["engagement_signals"]
    assert set(signal_schema["properties"]) == set(ENGAGEMENT_ROUTE_SIGNAL_NAMES)
    use_case_schema = schema["properties"]["use_case_fit"]
    assert set(use_case_schema["properties"]) == set(ACTOR_USE_CASE_NAMES)
    assert all(
        field_schema["type"] == ["string", "null"]
        and field_schema["minLength"] == 1
        for field_schema in use_case_schema["properties"].values()
    )
    assert "engagement_route" not in schema["properties"]
    condition_schema = schema["properties"]["condition_evidence"]
    assert set(condition_schema["properties"]) == set(ACTOR_REJECTION_CONDITION_NAMES)
    assert cached_payload["actor_use_cases"] == [
        "research collaboration",
        "learning expeditions",
        "executive education",
        "mentorship",
        "student and faculty mobility",
        "open innovation",
        "corporate engagement",
        "opportunity development",
    ]
    assert "complementarity" not in json.dumps(cached_payload).lower()
    assert "memberships" in cached_payload["engagement_route_rule"]
    assert "hosted visits" in cached_payload["engagement_route_rule"]
    assert "alone" in cached_payload["engagement_route_rule"]


def test_search_triage_client_replaces_url_shaped_reasons():
    candidate = _result("https://fresh.example/about", "q")
    client = StubToolClient(
        [
            {
                "candidates": [
                    {
                        "url": candidate.url,
                        "is_own_page": True,
                        "is_operating_org": True,
                        "actor_type_guess": "research_organization",
                        "hub_matches": ["Colorado Water Hub"],
                        "sector_codes": ["WATER"],
                        "engagement_signals": {
                            name: (
                                "Industry partnerships programme"
                                if name == "partnerships_and_research"
                                else None
                            )
                            for name in ENGAGEMENT_ROUTE_SIGNAL_NAMES
                        },
                        "use_case_fit": {
                            name: (
                                "Hosts industry visits"
                                if name in {"learning_expeditions", "corporate_engagement"}
                                else None
                            )
                            for name in ACTOR_USE_CASE_NAMES
                        },
                        "condition_evidence": {
                            "sector_relevance": "Matches the water sector",
                            "engagement_route": "Industry partnerships programme",
                            "strategic_ecosystem_value": "Runs a regional platform",
                        },
                        "sector_relevance": 0.8,
                        "strategic_ecosystem_value": 0.7,
                        "reason": "https://fresh.example/about",
                    }
                ]
            }
        ]
    )

    decisions = SearchTriageClient(client, {}).triage(
        [candidate],
        entity_type="actor",
        sectors=[],
        references=[],
    )

    assert decisions[candidate.url].reason == "LLM returned URL instead of reasoning"
    assert not decisions[candidate.url].reason.startswith("http")
    assert decisions[candidate.url].engagement_route == pytest.approx(0.25)


def test_actor_engagement_route_is_derived_from_use_case_evidence():
    one = _result("https://one-use.example/about", "q")
    three = _result("https://three-uses.example/about", "q")
    one_item = _actor_triage_item(
        one.url,
        sector_relevance=0.8,
        strategic_ecosystem_value=0.7,
        use_case_names=("learning_expeditions",),
    )
    one_item["use_case_fit"]["mentorship"] = False
    one_item["use_case_fit"]["open_innovation"] = "   "
    client = StubToolClient(
        [
            {
                "candidates": [
                    one_item,
                    _actor_triage_item(
                        three.url,
                        sector_relevance=0.8,
                        strategic_ecosystem_value=0.7,
                        use_case_names=(
                            "research_collaboration",
                            "student_and_faculty_mobility",
                            "open_innovation",
                        ),
                    ),
                ]
            }
        ]
    )

    decisions = SearchTriageClient(client, {}).triage(
        [one, three],
        entity_type="actor",
        sectors=[],
        references=[],
    )

    one_fit = decisions[one.url].use_case_fit
    three_fit = decisions[three.url].use_case_fit
    assert one_fit is not None
    assert three_fit is not None
    assert all(value is None or (isinstance(value, str) and value.strip()) for value in one_fit.values())
    assert decisions[one.url].engagement_route == pytest.approx(1 / 8)
    assert decisions[three.url].engagement_route == pytest.approx(3 / 8)
    assert decisions[three.url].engagement_route > decisions[one.url].engagement_route
    assert actor_engagement_route_score(three_fit) == pytest.approx(3 / 8)


def test_actor_rejects_only_when_all_three_conditions_fail(monkeypatch, tmp_path):
    _install_open_web_config(monkeypatch)
    relevant_without_route = _result("https://relevant.example/about", "q")
    fails_all = _result("https://irrelevant.example/about", "q")
    client = StubToolClient(
        [
            {
                "candidates": [
                    _actor_triage_item(
                        relevant_without_route.url,
                        sector_relevance=0.9,
                        strategic_ecosystem_value=0.6,
                    ),
                    _actor_triage_item(
                        fails_all.url,
                        sector_relevance=0.1,
                        strategic_ecosystem_value=0.1,
                        use_case_names=("mentorship",),
                    ),
                ]
            }
        ]
    )
    triage = SearchTriageClient(
        client,
        {
            "triage_max_tokens": 8000,
            "actor_sector_relevance_floor": 0.35,
            "actor_engagement_route_floor": 0.2,
            "actor_strategic_ecosystem_value_floor": 0.35,
            "actor_fit_weights": {
                "sector_relevance": 0.3,
                "engagement_route": 0.35,
                "strategic_ecosystem_value": 0.25,
                "distinctiveness": 0.1,
            },
        },
    )
    provider = StaticSearchProvider({"q": [relevant_without_route, fails_all]})
    args = _args(tmp_path, entity="actor")
    args.audit_out = str(tmp_path / "audit.csv")

    result = search_run.run_search_triage(
        args,
        root=PROJECT_ROOT,
        run_log=InMemoryRunLog(),
        store=InMemorySearchCandidateStore(),
        search_provider=provider,
        query_generator=StaticQueryGenerator(["q"]),
        triage_client=triage,
    )

    rows = {row.url: row for row in result["candidates"]}
    assert rows[relevant_without_route.url].triage_verdict == "accepted"
    assert all(
        value is None
        for value in rows[relevant_without_route.url].engagement_signals.values()
    )
    assert rows[relevant_without_route.url].fit_score == pytest.approx(0.42)
    assert rows[fails_all.url].triage_verdict == "rejected"
    assert rows[fails_all.url].triage_reason == (
        "low sector relevance; no engagement route; no strategic ecosystem value"
    )
    assert result["stats"]["actor_three_condition_rejected"] == 1
    assert result["stats"]["actor_legacy_single_floor_would_reject"] == 2
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "#### Actor evidence" in report
    assert "Duplicate Of" in report
    assert "Engagement route" in report
    assert "Use-case evidence counts:" in report
    assert "mentorship: 1" in report
    assert "research collaboration: 0" in report
    rejection_report = Path(result["rejection_report_path"]).read_text(encoding="utf-8")
    assert "Rejected candidates: **1**" in rejection_report
    assert "## low sector relevance; no engagement route; no strategic ecosystem value (1)" in rejection_report
    assert relevant_without_route.url not in rejection_report


def test_actor_distinctiveness_uses_database_count_and_configured_weights():
    candidate = _result("https://open.example/partners", "water research Boulder")
    client = StubToolClient(
        [
            {
                "candidates": [
                    _actor_triage_item(
                        candidate.url,
                        sector_relevance=0.8,
                        strategic_ecosystem_value=0.6,
                        engagement_evidence="Sponsored research partnerships are open",
                        use_case_names=(
                            "research_collaboration",
                            "student_and_faculty_mobility",
                            "open_innovation",
                            "corporate_engagement",
                        ),
                        hub_matches=["Colorado Water Hub"],
                        sector_codes=["WATER"],
                    )
                ]
            }
        ]
    )
    triage = SearchTriageClient(
        client,
        {
            "actor_fit_weights": {
                "sector_relevance": 0.2,
                "engagement_route": 0.3,
                "strategic_ecosystem_value": 0.1,
                "distinctiveness": 0.4,
            },
        },
    )

    decisions = triage.triage(
        [candidate],
        entity_type="actor",
        sectors=[{"code": "WATER", "name": "Water"}],
        references=[],
        actor_context={
            "coverage_counts": {("Colorado Water Hub", "WATER"): 4},
            "candidate_hubs": {candidate.url: ("Colorado Water Hub",)},
        },
    )

    decision = decisions[candidate.url]
    assert decision.existing_actor_count == 4
    assert decision.distinctiveness == pytest.approx(actor_distinctiveness_score(4))
    assert decision.distinctiveness == pytest.approx(0.2)
    assert decision.fit_score == pytest.approx(0.45)
    context = json.loads(client.calls[0]["user"])["candidates"][0]["coverage_context"]
    assert context == {
        "likely_hubs": [
            {
                "hub_name": "Colorado Water Hub",
                "sector_counts": [
                    {"sector_code": "WATER", "existing_actor_count": 4}
                ],
            }
        ]
    }
    assert "actor" not in json.dumps(context).lower().replace("existing_actor_count", "")


def test_actor_hub_sector_counts_are_loaded_without_actor_details():
    session = CapturingSession(
        [
            {"hub_name": "Colorado Water Hub", "sector_code": "water", "actor_count": 4},
            {"hub_name": "Utah Mining Hub", "sector_code": "MINING", "actor_count": 1},
        ]
    )

    counts = load_actor_hub_sector_counts(session)

    assert counts == {
        ("Colorado Water Hub", "WATER"): 4,
        ("Utah Mining Hub", "MINING"): 1,
    }
    sql = "\n".join(session.statements)
    assert "count(DISTINCT CASE" in sql
    assert "lower(actor.actor_type) <> 'aggregate'" in sql
    assert "actor.name" not in sql
    assert "actor.description" not in sql


def test_actor_triage_references_load_only_public_calibration_fields():
    session = CapturingSession(
        [
            {
                "name": "Reference Lab",
                "actor_type": "university_lab",
                "sectors": ["WATER", "AI"],
                "actor_id": "must-not-pass-through",
                "description": "must-not-pass-through",
                "website": "https://must-not-pass-through.example",
            }
        ]
    )

    references = load_actor_triage_reference_examples(session)

    assert references == [
        {
            "name": "Reference Lab",
            "actor_type": "university_lab",
            "sectors": ["WATER", "AI"],
        }
    ]
    sql = "\n".join(session.statements)
    assert "actor.name" in sql
    assert "actor.actor_type" in sql
    assert "sector.code" in sql
    assert "description" not in sql
    assert "website" not in sql


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


def test_run_loads_seen_urls_once_without_per_candidate_queries(monkeypatch, tmp_path):
    _install_open_web_config(monkeypatch)

    class CountingStore(InMemorySearchCandidateStore):
        def __init__(self):
            super().__init__(seen_raw_urls={"https://seen.example/one"})
            self.load_calls = 0
            self.lookup_calls = 0

        def load_seen_raw_urls(self):
            self.load_calls += 1
            return super().load_seen_raw_urls()

        def has_seen_raw_url(self, url):
            self.lookup_calls += 1
            return super().has_seen_raw_url(url)

    store = CountingStore()
    provider = StaticSearchProvider(
        {
            "q": [
                _result("https://seen.example/one", "q"),
                _result("https://seen.example/two", "q"),
            ]
        }
    )

    search_run.run_search_triage(
        _args(tmp_path),
        root=PROJECT_ROOT,
        session=CapturingSession([]),
        run_log=InMemoryRunLog(),
        store=store,
        search_provider=provider,
        query_generator=StaticQueryGenerator(["q"]),
        triage_client=RecordingTriageClient(),
    )

    assert store.load_calls == 1
    assert store.lookup_calls == 0


def test_sql_store_caches_bulk_seen_url_snapshot():
    session = ScalarSession(
        ["https://seen.example/one", "https://seen.example/two", None]
    )
    store = SQLSearchCandidateStore(session)

    assert store.load_seen_raw_urls() == {
        "https://seen.example/one",
        "https://seen.example/two",
    }
    assert store.has_seen_raw_url("https://seen.example/one") is True
    assert store.has_seen_raw_url("https://fresh.example/page") is False
    assert len(session.statements) == 1
    assert "SELECT DISTINCT url FROM raw_document" in session.statements[0]


def test_existing_actor_domain_is_rejected_before_llm_triage(monkeypatch, tmp_path):
    _install_open_web_config(monkeypatch)
    store = InMemorySearchCandidateStore()
    provider = StaticSearchProvider(
        {"q": [_result("https://www.albemarle.com/us/en/news/lithium", "q")]}
    )
    triage = RecordingTriageClient()

    result = search_run.run_search_triage(
        _args(tmp_path, entity="actor"),
        root=PROJECT_ROOT,
        session=RoutedSession(
            [
                (
                    "SELECT website FROM actor",
                    [{"website": "https://albemarle.com/us/en"}],
                )
            ]
        ),
        run_log=InMemoryRunLog(),
        store=store,
        search_provider=provider,
        query_generator=StaticQueryGenerator(["q"]),
        triage_client=triage,
    )

    assert result["status"] == "succeeded"
    assert result["stats"]["actor_existing_domain_blocklist_count"] == 1
    assert result["stats"]["deterministic_rejected"] == 1
    assert store.candidates[0].triage_reason == "actor already in database"
    assert triage.calls == []


def test_actor_news_domain_is_rejected_before_llm_triage(monkeypatch, tmp_path):
    _install_open_web_config(monkeypatch)
    store = InMemorySearchCandidateStore()
    provider = StaticSearchProvider(
        {"q": [_result("https://techcrunch.com/2026/01/01/funding-news", "q")]}
    )
    triage = RecordingTriageClient()

    result = search_run.run_search_triage(
        _args(tmp_path, entity="actor"),
        root=PROJECT_ROOT,
        session=RoutedSession([("SELECT website FROM actor", [])]),
        run_log=InMemoryRunLog(),
        store=store,
        search_provider=provider,
        query_generator=StaticQueryGenerator(["q"]),
        triage_client=triage,
    )

    assert result["status"] == "succeeded"
    assert result["stats"]["deterministic_rejected"] == 1
    assert store.candidates[0].triage_reason == "blocked domain: techcrunch.com"
    assert triage.calls == []


@pytest.mark.parametrize(
    "url",
    [
        "https://newsroom.example.org/product-launch",
        "https://example.org/news/product-launch",
    ],
)
def test_actor_own_domain_news_pages_are_rejected_deterministically(url):
    rejected = deterministic_rejection(
        _result(url, "q"),
        raw_lookup=InMemorySearchCandidateStore(),
        blocklist_domains=[],
        known_source_domains=[],
        entity_type="actor",
    )

    assert rejected is not None
    assert rejected.reason == "news or press page on own domain"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.org/about",
        "https://example.org/labs/energy-programme",
    ],
)
def test_actor_own_domain_organisation_pages_pass_deterministic_news_gate(url):
    rejected = deterministic_rejection(
        _result(url, "q"),
        raw_lookup=InMemorySearchCandidateStore(),
        blocklist_domains=[],
        known_source_domains=[],
        entity_type="actor",
    )

    assert rejected is None


def test_mines_newsroom_is_actor_blocklisted():
    assert "minesnewsroom.com" in blocklist_domains_for_entity("actor", {})


def test_conference_aggregators_are_rejected_deterministically():
    domains = [
        "allconferencealert.com",
        "conferenceindex.org",
        "10times.com",
        "exponents.com",
    ]

    for domain in domains:
        rejected = deterministic_rejection(
            _result(f"https://www.{domain}/events", "q"),
            raw_lookup=InMemorySearchCandidateStore(),
            blocklist_domains=domains,
            known_source_domains=[],
        )

        assert rejected is not None
        assert rejected.reason == f"blocked domain: {domain}"


def test_duplicate_urls_collapse_before_triage_and_keep_all_queries(monkeypatch, tmp_path):
    _install_open_web_config(monkeypatch, max_candidates_triaged=10)
    store = InMemorySearchCandidateStore()
    provider = StaticSearchProvider(
        {
            "q1": [_result("https://Dup.Example/event/?utm_source=x#top", "q1")],
            "q2": [_result("https://dup.example/event/", "q2")],
        }
    )
    triage = RecordingTriageClient(score=0.95)

    result = search_run.run_search_triage(
        _args(tmp_path),
        root=PROJECT_ROOT,
        run_log=InMemoryRunLog(),
        store=store,
        search_provider=provider,
        query_generator=StaticQueryGenerator(["q1", "q2"]),
        triage_client=triage,
    )

    assert result["status"] == "succeeded"
    assert result["stats"]["search_results"] == 2
    assert result["stats"]["search_results_unique"] == 1
    assert result["stats"]["search_results_deduplicated"] == 1
    assert [len(call) for call in triage.calls] == [1]
    assert triage.calls[0][0].url == "https://dup.example/event"
    assert len(store.candidates) == 1
    assert store.candidates[0].url == "https://dup.example/event"
    assert store.candidates[0].query == "q1 | q2"


def test_four_accepted_urls_on_one_domain_collapse_to_one():
    candidates = [
        _accepted_actor_candidate("https://ccst.us/about", score=0.4),
        _accepted_actor_candidate("https://ccst.us/programmes", score=0.8),
        _accepted_actor_candidate("https://www.ccst.us/reports/one", score=0.6),
        _accepted_actor_candidate("https://labs.ccst.us/research", score=0.7),
    ]

    collapsed = search_run._collapse_accepted_actor_domains(candidates)

    assert collapsed == 3
    survivor = candidates[1]
    assert survivor.triage_verdict == "accepted"
    duplicates = [candidate for candidate in candidates if candidate is not survivor]
    assert all(candidate.triage_verdict == "duplicate" for candidate in duplicates)
    assert all(candidate.duplicate_of == survivor.candidate_id for candidate in duplicates)


def test_institutional_subdomains_collapse_together():
    candidates = [
        _accepted_actor_candidate("https://epic.uchicago.edu/lab", score=0.8),
        _accepted_actor_candidate("https://urbanlabs.uchicago.edu/lab", score=0.7),
    ]

    collapsed = search_run._collapse_accepted_actor_domains(candidates)

    assert collapsed == 1
    assert candidates[0].triage_verdict == "accepted"
    assert candidates[1].triage_verdict == "duplicate"
    assert candidates[1].duplicate_of == candidates[0].candidate_id


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


def test_incomplete_triage_splits_batch_once_then_marks_remaining_incomplete(
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

    assert [len(call) for call in triage.calls] == [2, 1, 1]
    assert result["status"] == "attention"
    assert result["stats"]["triage_incomplete"] == 1
    assert {row.url: row.triage_verdict for row in store.candidates} == {
        first.url: "accepted",
        second.url: "triage_incomplete",
    }
    assert store.candidates[1].triage_reason == (
        "triage incomplete: candidate omitted after split retry"
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
        "triage incomplete: batch failed after split retry"
    )


def test_api_credit_error_aborts_without_split_retry(monkeypatch, tmp_path):
    _install_open_web_config(monkeypatch, triage_batch_size=2)
    provider = StaticSearchProvider(
        {
            "q": [
                _result("https://one.example/page", "q"),
                _result("https://two.example/page", "q"),
                _result("https://three.example/page", "q"),
            ]
        }
    )
    triage = SequencedTriageClient(
        [RuntimeError("invalid_request_error: API credit balance is too low")]
    )
    run_log = InMemoryRunLog()

    with pytest.raises(search_run.ApiCreditExhaustedError, match="API credit exhausted"):
        search_run.run_search_triage(
            _args(tmp_path),
            root=PROJECT_ROOT,
            session=CapturingSession([]),
            run_log=run_log,
            store=InMemorySearchCandidateStore(),
            search_provider=provider,
            query_generator=StaticQueryGenerator(["q"]),
            triage_client=triage,
        )

    assert [len(call) for call in triage.calls] == [2]
    failed_run = next(iter(run_log.runs.values()))
    assert failed_run.status == "failed"
    assert failed_run.status_reason == "API credit exhausted"


def test_failed_run_rolls_back_before_failure_write(monkeypatch, tmp_path):
    _install_open_web_config(monkeypatch)
    events: list[str] = []

    class RollbackSession:
        def rollback(self):
            events.append("rollback")

    class RollbackAwareRunLog(InMemoryRunLog):
        def fail_run(self, run_id, **kwargs):
            events.append("fail_run")
            return super().fail_run(run_id, **kwargs)

    class DroppedConnectionProvider:
        name = "dropped-connection"

        def search(self, query, *, count=10):
            raise ConnectionError("database connection dropped")

    run_log = RollbackAwareRunLog()
    with pytest.raises(ConnectionError, match="database connection dropped"):
        search_run.run_search_triage(
            _args(tmp_path),
            root=PROJECT_ROOT,
            session=RollbackSession(),
            run_log=run_log,
            store=InMemorySearchCandidateStore(),
            search_provider=DroppedConnectionProvider(),
            query_generator=StaticQueryGenerator(["q"]),
            triage_client=RecordingTriageClient(),
        )

    assert events == ["rollback", "fail_run"]


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
    assert "duplicate_of uuid" in sql


def _args(tmp_path: Path, *, entity: str = "event", offline: bool = True) -> Namespace:
    return Namespace(
        entity=entity,
        live=False,
        offline=offline,
        report_out=str(tmp_path / f"open-web-{entity}.md"),
        rejection_report_out=str(tmp_path / f"open-web-{entity}-rejections.md"),
        audit_out=str(tmp_path / "audit.csv"),
    )


def _result(url: str, query: str) -> SearchResult:
    return SearchResult(
        url=url,
        title=f"Title for {url}",
        snippet="Snippet",
        provider="stub",
        query=query,
    )


def _accepted_actor_candidate(url: str, *, score: float) -> CandidateRecord:
    return CandidateRecord.from_result(
        run_id="actor-run",
        entity_type="actor",
        result=_result(url, "q"),
        domain=normalized_domain(url),
        triage_verdict="accepted",
        triage_reason="accepted actor page",
        fit_score=score,
    )


def _install_open_web_config(monkeypatch, **overrides) -> None:
    open_web = {
        "provider": "claude",
        "results_per_query": 10,
        "triage_batch_size": 8,
        "triage_max_tokens": 8000,
        "max_searches": 40,
        "max_candidates_triaged": 200,
        "max_usd_per_run": 5.00,
        "forward_window_days": 365,
        "people_enabled": False,
        "accept_floor": {"event": 0.60, "actor": 0.70, "person": 0.95},
        "actor_sector_relevance_floor": 0.35,
        "actor_engagement_route_floor": 0.20,
        "actor_strategic_ecosystem_value_floor": 0.35,
        "actor_fit_weights": {
            "sector_relevance": 0.30,
            "engagement_route": 0.35,
            "strategic_ecosystem_value": 0.25,
            "distinctiveness": 0.10,
        },
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


def _actor_triage_item(
    url: str,
    *,
    sector_relevance: float,
    strategic_ecosystem_value: float,
    engagement_evidence: str | None = None,
    use_case_names: tuple[str, ...] = (),
    hub_matches: list[str] | None = None,
    sector_codes: list[str] | None = None,
) -> dict[str, object]:
    return {
        "url": url,
        "is_own_page": True,
        "is_operating_org": True,
        "actor_type_guess": "research_organization",
        "hub_matches": hub_matches or ["Colorado Water Hub"],
        "sector_codes": sector_codes or ["WATER"],
        "engagement_signals": {
            name: engagement_evidence if name == "partnerships_and_research" else None
            for name in ENGAGEMENT_ROUTE_SIGNAL_NAMES
        },
        "use_case_fit": {
            name: "Candidate evidence supports this use case"
            if name in use_case_names
            else None
            for name in ACTOR_USE_CASE_NAMES
        },
        "condition_evidence": {
            "sector_relevance": "Sector relevance assessed from the result",
            "engagement_route": engagement_evidence or "No engagement route found",
            "strategic_ecosystem_value": "Strategic ecosystem value assessed from the result",
        },
        "sector_relevance": sector_relevance,
        "strategic_ecosystem_value": strategic_ecosystem_value,
        "reason": "Actor conditions assessed",
    }


def _actor_query_session() -> RoutedSession:
    return RoutedSession(
        [
            (
                "SELECT DISTINCT actor_type",
                [
                    {"actor_type": "corporate_rd_lab"},
                    {"actor_type": "university_lab"},
                    {"actor_type": "aggregate"},
                ],
            ),
            (
                "FROM hub h",
                [
                    {
                        "hub_id": "thin-water",
                        "name": "Colorado Water Hub (Boulder- Denver- Front Range)",
                        "primary_city": "Boulder",
                        "state": "Colorado",
                        "country": "USA",
                        "region": "Front Range",
                        "actor_count": 1,
                    },
                    {
                        "hub_id": "category",
                        "name": "Mining Hubs",
                        "primary_city": None,
                        "state": None,
                        "country": "USA",
                        "region": None,
                        "actor_count": 0,
                    },
                    {
                        "hub_id": "chem-houston",
                        "name": "Houston Specialty Chemicals Hub",
                        "primary_city": "Houston",
                        "state": "Texas",
                        "country": "USA",
                        "region": None,
                        "actor_count": 12,
                    },
                ],
            ),
            (
                "SELECT actor_id::text AS actor_id",
                [
                    {
                        "actor_id": "1",
                        "name": "Albemarle",
                        "actor_type": "corporate_rd_lab",
                        "merged_into_actor_id": None,
                        "description": "Soil microbiome ecology and rhizosphere biology; nitrogen and field pilots",
                        "country": "USA",
                    },
                    {
                        "actor_id": "2",
                        "name": "Allen Institute for AI",
                        "actor_type": "university_lab",
                        "merged_into_actor_id": None,
                        "description": "Large-scale language models; AI infrastructure",
                        "country": "USA",
                    },
                ],
            ),
        ]
    )


def _actor_types_from_evidence_report() -> list[str]:
    return [
        "accelerator",
        "company",
        "consortium",
        "corporate_rd_lab",
        "federal_agency",
        "federal_research_system",
        "government_agency",
        "industrial_partner",
        "industry_association",
        "intergovernmental_organization",
        "national_research_center",
        "national_research_lab",
        "nonprofit",
        "other",
        "project_developer",
        "research_organization",
        "startup",
        "state_agency",
        "un_agency",
        "un_committee",
        "un_programme",
        "un_secretariat",
        "university",
        "university_lab",
        "venture_capital",
    ]


def _round_robin_hubs(count: int) -> list[dict[str, object]]:
    return [
        {
            "hub_id": f"hub-{index:02d}",
            "name": f"Hub {index:02d} Water Hub (City {index:02d})",
            "actor_count": index,
            "theme": "water",
            "geographies": [f"City {index:02d}"],
        }
        for index in reversed(range(count))
    ]


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
