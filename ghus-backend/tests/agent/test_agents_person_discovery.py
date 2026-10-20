from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path

import pytest

from agents.common.config import load_sources_config
from agents.common.resolve_route import RouteDecision, route_person
from agents.discovery.extractors.person import PERSON_FIELDS, PERSON_TOOL_SCHEMA, PersonExtractor
from agents.discovery.normalize import normalize_person_record
from agents.discovery.person_pages import (
    capture_people_from_actor_pages,
    reverify_person_profiles,
)
from agents.discovery.promote import apply_approved_person_affiliation_change, promote
from agents.discovery.search.models import SearchResult
from agents.discovery.search.person_scoring import (
    RUBRIC_ITEM_NAMES,
    person_score_band,
    person_score_thresholds,
    score_person_rubric,
)
from agents.discovery.search.phase2 import fetch_extract_stage_people
from agents.discovery.search.query_generation import QueryGenerator
from agents.discovery.search.triage import (
    SearchTriageClient,
    _triage_input_schema,
    blocklist_domains_for_entity,
    person_scope_rejection,
)
from agents.discovery.sources.base import FetchedDoc
from agents.discovery.stage import InMemoryStageStore, StagedRecord

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class NeverCalledClient:
    def extract_with_tool(self, **kwargs):
        raise AssertionError("LLM must not be called")


class ToolClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def extract_with_tool(self, **kwargs):
        self.calls.append(kwargs)
        return self.payload


class RawLookup:
    def has_seen_raw_url(self, url: str) -> bool:
        return False


class Transaction:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class Result:
    def __init__(self, *, rowcount=1):
        self.rowcount = rowcount


class Session:
    def __init__(self):
        self.statements: list[str] = []
        self.params: list[dict[str, object]] = []
        self.transactions: list[Transaction] = []

    def begin(self):
        transaction = Transaction()
        self.transactions.append(transaction)
        return transaction

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        self.params.append(params or {})
        return Result()


class RawStore:
    def exists(self, path: str) -> bool:
        return bool(path)

    def write(self, *, run_id: str, doc: FetchedDoc) -> str:
        return f"raw/{run_id}/{doc.content_hash}.html"


class RunLog:
    def __init__(self, prior=None):
        self.prior = prior
        self.writes = 0

    def find_raw_document(self, *, url: str, content_hash: str):
        return self.prior

    def write_raw_document(self, **kwargs):
        self.writes += 1
        return str(uuid.uuid4())


class Source:
    def __init__(self, result):
        self.result = result

    def fetch(self, url: str):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class Http404(RuntimeError):
    def __init__(self):
        super().__init__("404 Not Found")
        self.response = type("Response", (), {"status_code": 404})()


class CountingExtractor:
    prompt_version = "person_v1"

    def __init__(self):
        self.calls = 0

    def extract(self, doc):
        self.calls += 1
        return []


def _staged_person() -> StagedRecord:
    normalized = normalize_person_record(
        {
            "name": "Dr. Amina Example",
            "affiliation": "Example Water Lab",
            "role": "Principal Investigator",
            "public_profile_url": "https://example.edu/amina",
            "research_area": "membrane desalination",
        }
    )
    return StagedRecord(
        run_id=str(uuid.uuid4()),
        entity_type="person",
        natural_key=str(normalized["natural_key"]),
        source_url="https://example.edu/amina",
        payload=normalized,
        normalized_payload=normalized,
        prompt_version="person_v1",
        extracted_at="2026-09-10T00:00:00+00:00",
    )


def test_the_people_flag_is_on_by_sign_off_and_the_extractor_still_refuses_it_off():
    # Supervisor sign-off was recorded on 2026-10-15 (TARGETING_POLICY.md
    # section 6), so the shipped flag is on. The refusal path below is what
    # protects every environment where it is NOT.
    config = load_sources_config(PROJECT_ROOT)
    assert dict(config["open_web_discovery"])["people_enabled"] is True
    policy = (PROJECT_ROOT / "Targeting_Policy.md").read_text(encoding="utf-8")
    assert "Sign-off record." in policy, "enabling people needs the section 6 record"

    extractor = PersonExtractor(NeverCalledClient())
    with pytest.raises(RuntimeError, match="person extraction is disabled"):
        extractor.extract(FetchedDoc.from_content(url="https://example.edu/a", content="A"))


def test_all_person_acquisition_entry_points_refuse_disabled_flag():
    result = SearchResult(
        url="https://example.edu/a",
        title="Researcher",
        snippet="Water research",
        provider="test",
        query="water researcher",
    )
    with pytest.raises(RuntimeError, match="relevance triage is disabled"):
        SearchTriageClient(NeverCalledClient(), {"people_enabled": False}).triage(
            [result],
            entity_type="person",
            sectors=[{"code": "WATER", "name": "Water"}],
            references=[],
        )
    with pytest.raises(RuntimeError, match="person fetch is disabled"):
        fetch_extract_stage_people(
            run_id=str(uuid.uuid4()),
            candidates=[],
            config={"people_enabled": False},
            root=PROJECT_ROOT,
            session=None,
            live=False,
            run_log=None,
            cost_meter=None,
            stats={},
            audit_rows=[],
        )
    with pytest.raises(RuntimeError, match="person discovery is disabled"):
        capture_people_from_actor_pages(people_enabled=False)
    with pytest.raises(RuntimeError, match="person discovery is disabled"):
        reverify_person_profiles(
            run_id=str(uuid.uuid4()),
            config={},
            root=PROJECT_ROOT,
            session=None,
            live=False,
            run_log=None,
            stats={},
            audit_rows=[],
            people_enabled=False,
        )


def test_person_extraction_schema_is_exactly_the_five_permitted_fields():
    item = PERSON_TOOL_SCHEMA["properties"]["people"]["items"]
    assert set(item["properties"]) == set(PERSON_FIELDS)
    assert item["required"] == PERSON_FIELDS
    assert item["additionalProperties"] is False


def test_expertise_queries_are_deterministic_topic_queries_and_rotate_without_person_names():
    base = {
        "people_enabled": True,
        "max_searches": 40,
        "query_excluded_sectors": ["CROSS", "DIASPORA"],
    }
    first = QueryGenerator(NeverCalledClient(), base, today=date(2026, 9, 7)).generate(
        "person", session=None, project_root=PROJECT_ROOT
    )
    second = QueryGenerator(
        NeverCalledClient(),
        {**base, "person_query_rotation_seed": 2},
        today=date(2026, 9, 7),
    ).generate("person", session=None, project_root=PROJECT_ROOT)

    assert len(first.queries) == 40
    assert first.llm_queries == []
    assert all("research" in query or "principal investigator" in query for query in first.queries)
    assert "amina" not in "\n".join(first.queries).lower()
    assert first.queries != second.queries
    assert first.metadata["sector_codes_covered"] == [
        "AGRI",
        "AI",
        "CHEM",
        "ENERGY",
        "HEALTH",
        "MINING",
        "SUSTAIN",
        "WATER",
    ]


def test_news_directory_and_noninstitutional_person_pages_reject_before_llm():
    config = {"person_allowed_domains": ["aminaresearch.com"]}
    assert "techcrunch.com" in blocklist_domains_for_entity("person", config)
    result = SearchResult(
        url="https://profiles.example.com/amina",
        title="Amina Example",
        snippet="Researcher",
        provider="test",
        query="water researcher",
    )
    rejection = person_scope_rejection(
        result,
        held_actor_domains=["held-lab.com"],
        config=config,
    )
    assert rejection is not None
    assert rejection.reason == "not an institutional or approved self-published professional page"
    assert (
        person_scope_rejection(
            SearchResult(
                url="https://water.example.edu/amina",
                title="Amina Example",
                snippet="Researcher",
                provider="test",
                query="water researcher",
            ),
            held_actor_domains=[],
            config=config,
        )
        is None
    )


def test_person_gate_returns_only_fetch_and_reason():
    url = "https://water.example.edu/amina"
    client = ToolClient(
        {
            "candidates": [
                {
                    "url": url,
                    "fetch": True,
                    "reason": "Plausible institution-published professional profile.",
                }
            ]
        }
    )
    decisions = SearchTriageClient(client, {"people_enabled": True}).triage(
        [SearchResult(url=url, title="Amina", snippet="PI", provider="test", query="water")],
        entity_type="person",
        sectors=[{"code": "WATER", "name": "Water"}],
        references=[],
    )

    decision = decisions[url]
    assert decision.is_entity_type is True
    assert decision.fit_score is None
    schema_text = json.dumps(_triage_input_schema("person")).lower()
    assert set(
        _triage_input_schema("person")["properties"]["candidates"]["items"][
            "properties"
        ]
    ) == {"url", "fetch", "reason"}
    for forbidden in ("identity_decision", "natural_key", "route", "duplicate", "score"):
        assert forbidden not in schema_text


def test_person_score_thresholds_replace_the_pointwise_floor():
    config = load_sources_config(PROJECT_ROOT)["open_web_discovery"]
    empty = {
        name: {"present": False, "evidence": None} for name in RUBRIC_ITEM_NAMES
    }
    score = score_person_rubric(empty, config=config)
    assert person_score_thresholds(config) == (0.30, 0.70)
    assert score.total == 0.0
    assert person_score_band(score.total, config) == "auto_low"


def test_preview_identity_routes_create_skip_and_conflicts_deterministically():
    held = {
        "person_id": str(uuid.uuid4()),
        "actor_id": str(uuid.uuid4()),
        "full_name": "Dr. Amina Example",
        "affiliation": "Example Water Lab",
        "role": "Principal Investigator",
        "linkedin_url": "https://example.edu/amina",
    }
    same = normalize_person_record(
        {
            "name": "Dr Amina Example",
            "affiliation": "Example Water Lab",
            "role": "Principal Investigator",
            "public_profile_url": "https://example.edu/amina",
        }
    )
    different_affiliation = {**same, "affiliation": "New Water Institute"}
    different_affiliation["natural_key"] = normalize_person_record(different_affiliation)[
        "natural_key"
    ]

    assert route_person(same, [held], preview_create=True).zone == "skip"
    assert route_person(different_affiliation, [held], preview_create=True).zone == "review"
    assert route_person({**same, "role": "Director"}, [held], preview_create=True).zone == "review"
    assert route_person({**same, "name": "New Person"}, [held], preview_create=True).zone == "create"
    assert route_person({**same, "name": "New Person"}, [held]).zone == "review"


def test_person_create_preview_does_not_bypass_authorization_or_enable_live():
    staged = _staged_person()
    route = RouteDecision(zone="create", score=0.0)

    with pytest.raises(RuntimeError, match="person create guard failed"):
        promote(
            staged,
            route,
            person_create_preview=True,
            people_enabled=True,
        )
    authorized = RouteDecision(
        zone="create",
        score=0.8,
        metadata={
            "score_band": "auto_high",
            "identity_outcome": "create",
            "clean_identity_key": True,
            "affiliation_actor_id": str(uuid.uuid4()),
        },
    )
    with pytest.raises(RuntimeError, match="cannot be used with live writes"):
        promote(
            staged,
            authorized,
            session=Session(),
            live=True,
            person_create_preview=True,
            people_enabled=True,
        )


def test_approved_affiliation_change_updates_current_relation_and_logs_history():
    session = Session()
    change_id = apply_approved_person_affiliation_change(
        session,
        person_id=str(uuid.uuid4()),
        previous_actor_id=str(uuid.uuid4()),
        new_actor_id=str(uuid.uuid4()),
        previous_affiliation="Old Institute",
        new_affiliation="New Institute",
        role="Principal Investigator",
        source_url="https://new.example.edu/profile",
        changed_at="2026-09-10T00:00:00+00:00",
        live=True,
    )

    assert change_id
    assert any("UPDATE actor_person" in sql for sql in session.statements)
    assert any("INSERT INTO person_change_log" in sql for sql in session.statements)
    assert session.transactions[-1].committed

    migration = (PROJECT_ROOT / "agents" / "sql" / "130_person_change_log.sql").read_text(
        encoding="utf-8"
    )
    for column in (
        "person_id",
        "field_name",
        "previous_value",
        "new_value",
        "source_url",
        "changed_at",
    ):
        assert column in migration


def test_unchanged_profile_skips_extraction():
    doc = FetchedDoc.from_content(url="https://example.edu/amina", content="unchanged")
    extractor = CountingExtractor()
    stats: dict[str, object] = {}
    audit_rows: list[dict[str, object]] = []
    reverify_person_profiles(
        run_id=str(uuid.uuid4()),
        config={"raw_storage_dir": "agents/raw_documents"},
        root=PROJECT_ROOT,
        session=None,
        live=False,
        run_log=RunLog(prior={"storage_path": "raw/existing.html"}),
        stats=stats,
        audit_rows=audit_rows,
        people_enabled=True,
        profiles=[
            {
                "person_id": str(uuid.uuid4()),
                "name": "Dr. Amina Example",
                "public_profile_url": doc.url,
            }
        ],
        source=Source(doc),
        extractor=extractor,
        raw_store=RawStore(),
        stage_store=InMemoryStageStore(),
        person_candidates=[],
    )

    assert stats["skipped_unchanged"] == 1
    assert extractor.calls == 0
    assert audit_rows[0]["status"] == "skipped_unchanged"


def test_profile_404_flags_review_without_delete_or_extraction():
    person_id = str(uuid.uuid4())
    stage_store = InMemoryStageStore()
    stats: dict[str, object] = {}
    audit_rows: list[dict[str, object]] = []
    reverify_person_profiles(
        run_id=str(uuid.uuid4()),
        config={"raw_storage_dir": "agents/raw_documents"},
        root=PROJECT_ROOT,
        session=None,
        live=False,
        run_log=RunLog(),
        stats=stats,
        audit_rows=audit_rows,
        people_enabled=True,
        profiles=[
            {
                "person_id": person_id,
                "name": "Dr. Amina Example",
                "affiliation": "Example Water Lab",
                "role": "Principal Investigator",
                "public_profile_url": "https://example.edu/amina",
            }
        ],
        source=Source(Http404()),
        raw_store=RawStore(),
        stage_store=stage_store,
        person_candidates=[],
    )

    staged = next(iter(stage_store.rows.values()))
    assert staged.status == "routed_review"
    assert staged.target_entity_id == person_id
    assert stats["profiles_404_review"] == 1
    assert audit_rows[0]["zone"] == "review"
    assert "404" in str(audit_rows[0]["error"])
