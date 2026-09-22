from __future__ import annotations

import copy
import csv
import json
import uuid
from pathlib import Path

import pandas as pd
import pytest

from agents.common.config import load_sources_config
from agents.common.resolve_route import RouteDecision, route_person
from agents.discovery.extractors.person import PERSON_FIELDS, PERSON_TOOL_SCHEMA
from agents.discovery.normalize import normalize_affiliation_institution, normalize_person_record
from agents.discovery.promote import promote
from agents.discovery.search.models import CandidateRecord
from agents.discovery.search.person_scoring import (
    PERSON_RUBRIC_ANCHORS,
    RUBRIC_ITEM_NAMES,
    PersonRubricExtractor,
    person_rubric_record_schema,
    person_score_band,
    read_analysis_cache,
    rerank_top_person_candidates,
    score_person_rubric,
    validate_person_analysis,
    write_analysis_cache,
)
from agents.discovery.search.report import write_candidate_spreadsheet
from agents.discovery.sources.base import FetchedDoc
from agents.discovery.stage import StagedRecord

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class StubToolClient:
    def __init__(self, response):
        self.response = response
        self.calls: list[dict[str, object]] = []

    def extract_with_tool(self, **kwargs):
        self.calls.append(kwargs)
        return copy.deepcopy(self.response)


class ReverseReranker:
    def rerank_group(self, candidates):
        return [(candidate.url, "relative expertise value") for candidate in reversed(candidates)]


class Transaction:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class Session:
    def __init__(self):
        self.statements: list[tuple[str, dict[str, object]]] = []
        self.transaction = Transaction()

    def begin(self):
        return self.transaction

    def execute(self, statement, params=None):
        self.statements.append((str(statement), dict(params or {})))
        return object()


def test_person_record_schema_is_exactly_five_fields_and_rejects_a_sixth():
    source_schema = PERSON_TOOL_SCHEMA["properties"]["people"]["items"]
    analysis_schema = person_rubric_record_schema()["properties"]["record"]

    assert set(analysis_schema["properties"]) == set(PERSON_FIELDS)
    assert analysis_schema["required"] == PERSON_FIELDS
    assert analysis_schema["additionalProperties"] is False
    assert analysis_schema == source_schema

    payload = _analysis_payload()
    payload["record"]["email"] = "not-permitted@example.org"
    with pytest.raises(RuntimeError, match="outside the five-field policy"):
        validate_person_analysis(payload)


def test_person_rubric_prompt_contains_three_filled_anchors_and_no_identity_task():
    client = StubToolClient(_analysis_payload())
    extractor = PersonRubricExtractor(client)

    extractor.extract(
        FetchedDoc.from_content(
            url="https://example.edu/amina",
            content="A public university research profile.",
        ),
        sector_codes=["WATER", "AI"],
        hub_names=["New York Hub"],
        held_actor_names=["Example Water Lab"],
    )

    prompt = json.loads(client.calls[0]["cached_user"])
    anchors = prompt["calibration_anchors"]
    assert [anchor["name"] for anchor in anchors] == [
        "Rosario Sanchez",
        "Julia Stoyanovich",
        "Phys.org researcher coverage row",
    ]
    assert anchors == list(PERSON_RUBRIC_ANCHORS)
    assert all(set(anchor["rubric"]) == set(RUBRIC_ITEM_NAMES) for anchor in anchors)
    schema_text = json.dumps(client.calls[0]["input_schema"]).casefold()
    for forbidden in ("identity_outcome", "identity_decision", "duplicate", "route"):
        assert forbidden not in schema_text


def test_person_rubric_items_are_never_numeric():
    payload = _analysis_payload()
    payload["rubric"]["actionable_role"]["present"] = 1

    with pytest.raises(TypeError, match="present must be boolean"):
        validate_person_analysis(payload)


def test_missing_person_fields_become_null_and_held_affiliation_is_deterministic():
    analysis = validate_person_analysis(
        _analysis_payload(
            record={
                "name": "Dr. Amina Example",
                "affiliation": "Example Water Lab",
            }
        ),
        held_actor_names=["Example Water Lab"],
    )

    assert set(analysis.record) == set(PERSON_FIELDS)
    assert analysis.record["role"] is None
    assert analysis.record["public_profile_url"] is None
    assert analysis.rubric["hub_or_held_affiliation"]["present"] is True
    assert analysis.rubric["public_profile_url_present"] == {
        "present": False,
        "evidence": None,
    }


def test_person_score_is_identical_when_replayed_from_cache(tmp_path):
    config = load_sources_config(PROJECT_ROOT)["open_web_discovery"]
    analysis = validate_person_analysis(
        _analysis_payload(), held_actor_names=["Example Water Lab"]
    )
    cache_path = tmp_path / "person-analysis.json"
    write_analysis_cache(cache_path, analysis)
    replayed = read_analysis_cache(
        cache_path, held_actor_names=["Example Water Lab"]
    )

    assert replayed is not None
    first = score_person_rubric(analysis.rubric, config=config)
    second = score_person_rubric(replayed.rubric, config=config)
    assert first == second
    assert person_score_band(first.total, config) == "auto_high"
    assert sum(first.contributions.values()) == pytest.approx(first.total)


def test_person_rerank_changes_only_the_configured_top_group():
    candidates = [_candidate(index, score) for index, score in enumerate((0.9, 0.8, 0.7))]
    updated, attention = rerank_top_person_candidates(
        candidates,
        reranker=ReverseReranker(),
        config={"person_rerank_top_n": 2, "person_rerank_group_size": 2},
    )

    assert attention == []
    assert [candidate.rerank_position for candidate in updated] == [2, 1, None]


def test_auto_high_identity_is_deterministic_and_never_model_supplied():
    actor_id = str(uuid.uuid4())
    record = normalize_person_record(_person_record())
    route = route_person(
        record,
        [],
        allow_create=True,
        affiliation_candidates=[
            {"actor_id": actor_id, "affiliation": "Example Water Lab"}
        ],
    )

    assert route.zone == "create"
    assert route.metadata["identity_outcome"] == "create"
    assert route.metadata["clean_identity_key"] is True
    assert route.metadata["affiliation_actor_id"] == actor_id

    conflict = route_person(
        {**record, "affiliation": "Another Institute"},
        [
            {
                "person_id": str(uuid.uuid4()),
                "full_name": record["name"],
                "affiliation": "Example Water Lab",
            }
        ],
        allow_create=True,
        affiliation_candidates=[],
    )
    assert conflict.zone == "review"
    assert conflict.metadata["identity_outcome"] == "different_affiliation"


def test_affiliation_normalizes_to_institution_and_frozen_resolver_matches_actor():
    actor_id = str(uuid.uuid4())

    class Resolver:
        HIGH = 0.9
        LOW = 0.4
        model_name = "frozen-test"

        def _candidates(self, name):
            assert name == "University of Colorado Boulder"
            return pd.DataFrame(
                [{"actor_id": actor_id, "name": name, "description": "", "hubs": ""}]
            )

        def _score(self, _record, candidates):
            return candidates.assign(score=0.97)

    record = normalize_person_record(
        {
            **_person_record(),
            "affiliation": (
                "University of Colorado Boulder, Chemical and Biological Engineering"
            ),
        }
    )
    route = route_person(
        record,
        [],
        allow_create=True,
        actor_resolver=Resolver(),
    )

    assert record["affiliation"] == "University of Colorado Boulder"
    assert record["affiliation_raw"].endswith("Chemical and Biological Engineering")
    assert route.zone == "create"
    assert route.metadata["affiliation_actor_id"] == actor_id


def test_unmatched_institution_creates_stub_actor_and_person_atomically():
    class Resolver:
        HIGH = 0.9
        LOW = 0.4
        model_name = "frozen-test"

        def _candidates(self, _name):
            return pd.DataFrame(columns=["actor_id", "name", "description", "hubs"])

    normalized = normalize_person_record(
        {**_person_record(), "affiliation": "Example Institute of Water"}
    )
    route = route_person(
        normalized,
        [],
        allow_create=True,
        actor_resolver=Resolver(),
    )
    route = RouteDecision(
        zone=route.zone,
        score=0.82,
        metadata={**route.metadata, "score_band": "auto_high"},
    )
    staged = StagedRecord(
        run_id=str(uuid.uuid4()),
        entity_type="person",
        natural_key=str(normalized["natural_key"]),
        source_url="https://example.edu/amina",
        payload=normalized,
        normalized_payload=normalized,
        prompt_version="person_rubric_record_v1",
        extracted_at="2026-09-15T00:00:00+00:00",
    )
    session = Session()

    result = promote(staged, route, session=session, live=True, people_enabled=True)

    sql = [statement for statement, _params in session.statements]
    actor_index = next(index for index, statement in enumerate(sql) if "INSERT INTO actor (" in statement)
    person_index = next(index for index, statement in enumerate(sql) if "INSERT INTO person (" in statement)
    relation_index = next(index for index, statement in enumerate(sql) if "INSERT INTO actor_person" in statement)
    assert result.action == "created"
    assert actor_index < person_index < relation_index
    actor_params = session.statements[actor_index][1]
    assert actor_params["name"] == "Example Institute of Water"
    assert actor_params["verification_status"] == "needs_review"
    profile_params = next(
        params
        for statement, params in session.statements
        if "INSERT INTO person_discovery_profile" in statement
    )
    assert profile_params["needs_actor_enrichment"] is True
    assert session.transaction.committed is True


def test_department_or_role_text_never_becomes_an_actor_stub():
    assert normalize_affiliation_institution("Department of Chemistry") is None
    record = normalize_person_record(
        {**_person_record(), "affiliation": "Department of Chemistry"}
    )
    route = route_person(record, [], allow_create=True, affiliation_candidates=[])

    assert route.zone == "review"
    assert route.metadata["identity_outcome"] == "missing_affiliation"


def test_person_review_persists_rubric_rerank_and_identity_evidence():
    session = Session()
    staged = _staged_person()
    route = RouteDecision(
        zone="review",
        score=0.55,
        metadata={
            "review_kind": "rubric_band",
            "rubric": _rubric(),
            "score_breakdown": {"sector_intersection": 0.20},
            "rerank_position": 4,
            "rerank_reason": "Relevant, but institutional evidence needs review.",
            "identity_outcome": "not_evaluated",
        },
    )

    result = promote(
        staged,
        route,
        session=session,
        live=False,
        people_enabled=True,
    )

    sql, params = session.statements[1]
    assert result.action == "would_review"
    assert "INSERT INTO person_review_queue" in sql
    assert json.loads(str(params["rubric"]))["sector_intersection"]["present"] is True
    assert params["identity_outcome"] == "not_evaluated"
    assert session.transaction.rolled_back is True


def test_person_create_requires_enabled_switch_and_all_authorization_guards():
    staged = _staged_person()
    route = _create_route()

    with pytest.raises(RuntimeError, match="person promotion is disabled"):
        promote(staged, route, session=Session(), live=False)

    invalid_metadata = (
        {**route.metadata, "score_band": "review"},
        {**route.metadata, "identity_outcome": "unknown_affiliation"},
        {**route.metadata, "clean_identity_key": False},
        {key: value for key, value in route.metadata.items() if key != "affiliation_actor_id"},
    )
    for metadata in invalid_metadata:
        with pytest.raises(RuntimeError, match="person create guard failed"):
            promote(
                staged,
                RouteDecision(zone="create", score=route.score, metadata=metadata),
                session=Session(),
                live=False,
                people_enabled=True,
            )


def test_person_create_dry_run_executes_full_transaction_then_rolls_back():
    session = Session()

    result = promote(
        _staged_person(),
        _create_route(),
        session=session,
        live=False,
        people_enabled=True,
    )

    sql = [statement for statement, _ in session.statements]
    assert result.action == "would_create"
    assert result.dry_run is True
    assert any("INSERT INTO source" in statement for statement in sql)
    assert any("INSERT INTO person " in statement for statement in sql)
    assert any("INSERT INTO actor_person" in statement for statement in sql)
    assert any("INSERT INTO person_discovery_profile" in statement for statement in sql)
    assert any("INSERT INTO index_dirty" in statement for statement in sql)
    assert session.transaction.rolled_back is True
    assert session.transaction.committed is False

    person_params = next(
        params for statement, params in session.statements if "INSERT INTO person (" in statement
    )
    assert person_params["full_name"] == "Dr. Amina Example"
    assert person_params["title"] == "Principal Investigator"
    assert person_params["verification_status"] == "needs_review"
    assert "email" not in person_params
    assert "bio" not in person_params
    assert "orcid" not in person_params
    assert "linkedin_url" not in person_params

    profile_params = next(
        params
        for statement, params in session.statements
        if "INSERT INTO person_discovery_profile" in statement
    )
    assert profile_params["public_profile_url"] == "https://example.edu/amina"
    assert profile_params["research_area"] == "Membrane desalination and water treatment"
    assert profile_params["source_url"] == "https://example.edu/amina"
    assert profile_params["source_id"] == person_params["source_id"]


def test_person_create_live_capability_commits_only_on_fake_session():
    session = Session()

    result = promote(
        _staged_person(),
        _create_route(),
        session=session,
        live=True,
        people_enabled=True,
    )

    assert result.action == "created"
    assert result.dry_run is False
    assert result.entity_id
    assert session.transaction.committed is True
    assert session.transaction.rolled_back is False


def test_person_spreadsheet_contains_only_permitted_record_and_review_fields(tmp_path):
    candidate = _candidate(1, 0.82)
    candidate = CandidateRecord(
        **{
            **candidate.__dict__,
            "page_fetched": True,
            "rubric": _rubric(),
            "record_preview": _person_record(),
            "score_band": "auto_high",
            "identity_outcome": "create",
            "rerank_position": 2,
            "rerank_reason": "Strong expertise and actionable role.",
        }
    )
    path = tmp_path / "people.csv"

    write_candidate_spreadsheet(path, [candidate])

    with path.open(encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert set(PERSON_FIELDS).issubset(row)
    assert row["name"] == "Dr. Amina Example"
    assert row["identity_outcome"] == "create"
    assert "email" not in row
    assert row["rubric_evidence"]


def test_person_rubric_migration_is_emitted_but_not_run():
    sql = (PROJECT_ROOT / "agents" / "sql" / "160_person_rubric_review.sql").read_text(
        encoding="utf-8"
    )
    for column in (
        "identity_outcome",
        "review_kind",
        "rubric",
        "score_breakdown",
        "rerank_position",
        "rerank_reason",
        "person_discovery_profile",
        "source_url",
        "fetched_at",
    ):
        assert column in sql

    affiliation_sql = (
        PROJECT_ROOT / "agents" / "sql" / "170_person_affiliation_resolution.sql"
    ).read_text(encoding="utf-8")
    assert "affiliation_raw" in affiliation_sql
    assert "needs_actor_enrichment" in affiliation_sql


def _analysis_payload(record: dict[str, object] | None = None) -> dict[str, object]:
    return {"rubric": _rubric(), "record": record or _person_record()}


def _person_record() -> dict[str, object]:
    return {
        "name": "Dr. Amina Example",
        "affiliation": "Example Water Lab",
        "role": "Principal Investigator",
        "public_profile_url": "https://example.edu/amina",
        "research_area": "Membrane desalination and water treatment",
    }


def _rubric() -> dict[str, object]:
    return {
        "institution_or_self_published": _item(
            True, "The university publishes this professional profile."
        ),
        "research_area_stated": _item(
            True, "Membrane desalination is stated as a research area."
        ),
        "sector_intersection": _item(True, "The work intersects WATER."),
        "hub_or_held_affiliation": _item(True, "The affiliation is a held actor."),
        "actionable_role": _item(True, "Principal Investigator is stated."),
        "active_work_evidence": _item(True, "A named membrane project is listed."),
        "public_profile_url_present": _item(True, "A public profile URL is present."),
    }


def _item(present: bool, evidence: str | None) -> dict[str, object]:
    return {"present": present, "evidence": evidence}


def _candidate(index: int, score: float) -> CandidateRecord:
    return CandidateRecord(
        candidate_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        entity_type="person",
        query="membrane desalination researcher university",
        provider="stub",
        url=f"https://example-{index}.edu/profile",
        title=f"Researcher {index}",
        snippet="University profile",
        domain=f"example-{index}.edu",
        triage_verdict="accepted",
        triage_reason="fetch",
        fit_score=score,
    )


def _staged_person() -> StagedRecord:
    normalized = normalize_person_record(_person_record())
    return StagedRecord(
        run_id=str(uuid.uuid4()),
        entity_type="person",
        natural_key=str(normalized["natural_key"]),
        source_url="https://example.edu/amina",
        payload=normalized,
        normalized_payload=normalized,
        prompt_version="person_rubric_record_v1",
        extracted_at="2026-09-15T00:00:00+00:00",
    )


def _create_route() -> RouteDecision:
    return RouteDecision(
        zone="create",
        score=0.82,
        metadata={
            "score_band": "auto_high",
            "identity_outcome": "create",
            "clean_identity_key": True,
            "affiliation_actor_id": str(uuid.uuid4()),
        },
    )
