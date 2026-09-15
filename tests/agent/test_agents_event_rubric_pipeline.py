from __future__ import annotations

import copy
import csv
import json
import uuid
from datetime import date
from pathlib import Path

import pytest

from agents.common.config import load_sources_config
from agents.common.resolve_route import RouteDecision
from agents.discovery.event_qualification import qualify_event
from agents.discovery.extractors.event import EVENT_FIELDS, EVENT_TOOL_SCHEMA
from agents.discovery.promote import promote
from agents.discovery.run import _extract_stage_route_promote
from agents.discovery.search.event_scoring import (
    EVENT_RUBRIC_ANCHORS,
    RUBRIC_ITEM_NAMES,
    EventPageAnalysis,
    EventRubricExtractor,
    PreExtractedEventExtractor,
    event_rubric_record_schema,
    event_score_band,
    read_analysis_cache,
    score_event_rubric,
    validate_event_analysis,
    write_analysis_cache,
)
from agents.discovery.search.models import CandidateRecord, SearchResult
from agents.discovery.search.report import EVENT_REPORT_FIELDS, write_candidate_spreadsheet
from agents.discovery.search.triage import SearchTriageClient
from agents.discovery.sources.base import FetchedDoc
from agents.discovery.stage import InMemoryStageStore, StagedRecord

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_DATE = date(2026, 9, 15)


class StubToolClient:
    def __init__(self, response):
        self.response = response
        self.calls: list[dict[str, object]] = []

    def extract_with_tool(self, **kwargs):
        self.calls.append(kwargs)
        return copy.deepcopy(self.response)


class EmptyActorCandidates:
    empty = True


class CreatingActorResolver:
    HIGH = 0.96
    LOW = 0.18
    model_name = "test-combiner"

    def _candidates(self, _name):
        return EmptyActorCandidates()


class FakeTransaction:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class FakeSession:
    def __init__(self):
        self.statements: list[tuple[str, dict[str, object]]] = []
        self.transaction = FakeTransaction()

    def begin(self):
        return self.transaction

    def execute(self, statement, params=None):
        self.statements.append((str(statement), dict(params or {})))
        return object()


def test_event_gate_returns_only_fetch_and_reason_without_a_score():
    client = StubToolClient(
        {
            "candidates": [
                {
                    "url": "https://events.example/summit",
                    "fetch": True,
                    "reason": "Plausible page for one summit.",
                }
            ]
        }
    )
    triage = SearchTriageClient(client, {"triage_max_tokens": 500})

    decisions = triage.triage(
        [
            SearchResult(
                url="https://events.example/summit",
                title="Summit homepage",
                snippet="Details coming soon",
                provider="stub",
                query="energy summit",
            )
        ],
        entity_type="event",
        sectors=[],
        references=[],
    )

    decision = decisions["https://events.example/summit"]
    assert decision.is_entity_type is True
    assert decision.fit_score is None
    item_schema = client.calls[0]["input_schema"]["properties"]["candidates"]["items"]
    assert set(item_schema["properties"]) == {"url", "fetch", "reason"}


def test_event_record_schema_reuses_event_tool_schema_field_for_field():
    source_schema = EVENT_TOOL_SCHEMA["properties"]["events"]["items"]
    analysis_schema = event_rubric_record_schema(
        sector_codes=list(source_schema["properties"]["sector_codes"]["items"]["enum"])
    )["properties"]["record"]

    assert set(EVENT_FIELDS) == set(source_schema["properties"])
    assert set(analysis_schema["properties"]) == set(source_schema["properties"])
    assert set(analysis_schema["required"]) == set(source_schema["required"])


def test_event_rubric_prompt_contains_three_filled_calibration_anchors():
    client = StubToolClient(_analysis_payload())
    extractor = EventRubricExtractor(client)

    extractor.extract(
        FetchedDoc.from_content(
            url="https://events.example/summit",
            content="One energy summit",
        ),
        sector_codes=_sector_codes(),
        hub_names=["Texas Water Systems Hub"],
        run_date=RUN_DATE,
    )

    prompt = json.loads(client.calls[0]["cached_user"])
    anchors = prompt["calibration_anchors"]
    assert [anchor["name"] for anchor in anchors] == [
        "ARPA-E Energy Innovation Summit",
        "UNGA side event with named speakers",
        "Climate Week library workshop",
    ]
    assert [anchor["strength"] for anchor in anchors] == ["strong", "middling", "weak"]
    assert anchors == list(EVENT_RUBRIC_ANCHORS)
    assert all(set(anchor["rubric"]) == set(RUBRIC_ITEM_NAMES) for anchor in anchors)


def test_event_rubric_items_reject_numeric_presence_values():
    payload = _analysis_payload()
    payload["rubric"]["institutional_scale"]["present"] = 1

    with pytest.raises(TypeError, match="present must be boolean"):
        validate_event_analysis(
            payload,
            sector_codes=_sector_codes(),
            run_date=RUN_DATE,
        )


def test_event_record_missing_fields_are_null_and_cross_needs_two_named_sectors():
    payload = _analysis_payload(record={"title": "Sparse Summit", "sector_codes": []})
    analysis = validate_event_analysis(
        payload,
        sector_codes=_sector_codes(),
        run_date=RUN_DATE,
    )

    assert set(analysis.record) == set(EVENT_FIELDS)
    assert analysis.record["title"] == "Sparse Summit"
    assert all(
        analysis.record[field] is None
        for field in EVENT_FIELDS
        if field not in {"title", "sector_codes"}
    )

    invalid = _analysis_payload(record={"title": "Vague event", "sector_codes": ["CROSS"]})
    with pytest.raises(RuntimeError, match="CROSS requires two or more"):
        validate_event_analysis(
            invalid,
            sector_codes=_sector_codes(),
            run_date=RUN_DATE,
        )


def test_event_score_is_identical_when_replayed_from_cached_analysis(tmp_path):
    config = load_sources_config(PROJECT_ROOT)["open_web_discovery"]
    analysis = validate_event_analysis(
        _analysis_payload(),
        sector_codes=_sector_codes(),
        run_date=RUN_DATE,
    )
    cache_path = tmp_path / "event-analysis.json"
    write_analysis_cache(cache_path, analysis)
    replayed = read_analysis_cache(
        cache_path,
        sector_codes=_sector_codes(),
        run_date=RUN_DATE,
    )

    assert replayed is not None
    first = score_event_rubric(analysis.rubric, config=config)
    second = score_event_rubric(replayed.rubric, config=config)
    assert first == second
    assert sum(first.contributions.values()) == pytest.approx(first.total)
    assert event_score_band(first.total, config) == "auto_high"


def test_rubric_qualification_uses_exact_attendable_and_minable_formulas():
    record = _event_record()
    rubric = _rubric()
    decision = qualify_event(
        {
            **record,
            "participant_actors": [
                {"name": f"Sponsor {index}", "participant_role": "sponsor"}
                for index in range(1, 4)
            ],
        },
        run_date=RUN_DATE,
        config={"forward_window_months": 12},
        rubric=rubric,
    )

    assert decision.attendable is True
    assert decision.minable is True
    assert decision.paths == ("attendable", "minable")

    no_scale = copy.deepcopy(rubric)
    no_scale["institutional_scale"] = _item(False, None)
    no_speakers = copy.deepcopy(no_scale)
    no_speakers["named_speakers"] = _item(False, None)
    one_sponsor = qualify_event(
        {
            **record,
            "participant_actors": [
                {"name": "Only Sponsor", "participant_role": "sponsor"}
            ],
        },
        run_date=RUN_DATE,
        config={"forward_window_months": 12},
        rubric=no_speakers,
    )
    assert one_sponsor.attendable is False
    assert one_sponsor.minable is False


def test_past_minable_event_stages_participants_but_not_event():
    sector_code = _sector_codes()[0]
    record = _event_record(start_date="2026-04-10", sector_codes=[sector_code])
    participants = [
        {
            "name": f"Sponsor {index}",
            "participant_role": "sponsor",
            "actor_type": "company",
            "website": None,
        }
        for index in range(1, 4)
    ]
    rubric = _rubric(date_within_window=False, named_speakers=False)
    stage_store = InMemoryStageStore()
    stats = _stats()
    audit_rows: list[dict[str, object]] = []

    _extract_stage_route_promote(
        doc=FetchedDoc.from_content(
            url="https://events.example/past-summit", content="Past summit"
        ),
        raw_document_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        source_name="open_web_search",
        entity_type="event",
        extractor=PreExtractedEventExtractor(record, participant_actors=participants),
        stage_store=stage_store,
        session=None,
        live=False,
        candidates=[],
        root=PROJECT_ROOT,
        stats=stats,
        audit_rows=audit_rows,
        qualification_config={"enabled": True, "participant_extraction_enabled": True},
        people_enabled=False,
        run_date=RUN_DATE,
        actor_resolver=CreatingActorResolver(),
        event_rubric=rubric,
    )

    assert [row.entity_type for row in stage_store.rows.values()].count("event") == 0
    assert [row.entity_type for row in stage_store.rows.values()].count("actor") == 3
    assert any(row["status"] == "mined_not_stored" for row in audit_rows)


def test_upcoming_attendable_event_stages_one_event():
    stage_store = InMemoryStageStore()
    stats = _stats()

    _extract_stage_route_promote(
        doc=FetchedDoc.from_content(
            url="https://events.example/upcoming-summit", content="Upcoming summit"
        ),
        raw_document_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        source_name="open_web_search",
        entity_type="event",
        extractor=PreExtractedEventExtractor(_event_record()),
        stage_store=stage_store,
        session=None,
        live=False,
        candidates=[],
        root=PROJECT_ROOT,
        stats=stats,
        audit_rows=[],
        qualification_config={"enabled": True, "participant_extraction_enabled": True},
        people_enabled=False,
        run_date=RUN_DATE,
        event_rubric=_rubric(named_speakers=False),
    )

    assert [row.entity_type for row in stage_store.rows.values()] == ["event"]


def test_rubric_review_route_writes_rubric_and_rerank_evidence():
    session = FakeSession()
    staged = StagedRecord(
        run_id=str(uuid.uuid4()),
        entity_type="event",
        natural_key="review summit|2027-03-10",
        source_url="https://events.example/review",
        payload={},
        normalized_payload={"name": "Review Summit", "start_date": "2027-03-10"},
        prompt_version="event_rubric_record_v1",
        extracted_at="2026-09-15T00:00:00+00:00",
    )
    route = RouteDecision(
        zone="review",
        score=0.55,
        metadata={
            "review_kind": "rubric_band",
            "search_candidate_id": str(uuid.uuid4()),
            "staged_title": "Review Summit",
            "shared_start_date": "2027-03-10",
            "rubric": _rubric(),
            "score_breakdown": {"single_discrete_event": 0.15},
            "qualification_paths": ["attendable"],
            "rerank_position": 7,
            "rerank_reason": "Useful, but evidence needs review.",
        },
    )

    result = promote(staged, route, session=session, live=False)

    sql, params = session.statements[0]
    assert result.action == "would_review"
    assert "INSERT INTO event_review_queue" in sql
    assert "rubric" in sql
    assert json.loads(str(params["rubric"]))["single_discrete_event"]["present"] is True
    assert params["rerank_reason"] == "Useful, but evidence needs review."
    assert session.transaction.rolled_back is True


def test_event_spreadsheet_contains_record_score_qualification_and_evidence(tmp_path):
    candidate = CandidateRecord(
        candidate_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        entity_type="event",
        query="energy summit",
        provider="stub",
        url="https://events.example/summit",
        title="Energy Summit",
        snippet="Summit",
        domain="events.example",
        triage_verdict="accepted",
        triage_reason="high rubric score",
        fit_score=0.82,
        page_fetched=True,
        rubric=_rubric(),
        record_preview=_event_record(),
        score_band="auto_high",
        qualification_paths=("attendable", "minable"),
        rerank_position=2,
        rerank_reason="Strong institutional event.",
    )
    path = tmp_path / "event-records.csv"

    write_candidate_spreadsheet(path, [candidate])

    with path.open(encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert set(EVENT_REPORT_FIELDS).issubset(row)
    assert row["name"] == "GHUS Energy Summit"
    assert row["city"] == "Boston"
    assert row["qualification_paths"] == "attendable; minable"
    assert row["band"] == "auto_high"
    assert row["rubric_evidence"]


def test_event_migration_persists_qualification_and_review_evidence():
    sql = (PROJECT_ROOT / "agents" / "sql" / "150_event_rubric_review.sql").read_text(
        encoding="utf-8"
    )

    for column in (
        "qualification_paths",
        "review_kind",
        "search_candidate_id",
        "rubric",
        "score_breakdown",
        "rerank_position",
        "rerank_reason",
    ):
        assert column in sql
    assert "DROP NOT NULL" in sql


def _analysis_payload(record: dict[str, object] | None = None) -> dict[str, object]:
    return {"rubric": _rubric(), "record": record or _event_record()}


def _event_record(
    *,
    start_date: str = "2027-03-10",
    sector_codes: list[str] | None = None,
) -> dict[str, object]:
    record = {field: None for field in EVENT_FIELDS}
    record.update(
        {
            "title": "GHUS Energy Summit",
            "start_date": start_date,
            "end_date": "2027-03-11",
            "description": "A multi-track energy research and innovation summit.",
            "location": "Boston Convention Center",
            "city": "Boston",
            "state": "Massachusetts",
            "country": "USA",
            "website": "https://events.example/summit",
            "event_type": "Summit",
            "access_type": "Public registration",
            "sponsoring_orgs": "Example Energy Institute",
            "sector_codes": sector_codes or ["ENERGY"],
        }
    )
    return record


def _rubric(
    *,
    date_within_window: bool = True,
    named_speakers: bool = True,
) -> dict[str, object]:
    return {
        "single_discrete_event": _item(True, "One dedicated summit page."),
        "date_within_window": _item(
            date_within_window,
            "The start date is within twelve months." if date_within_window else None,
        ),
        "open_external_registration": _item(True, "External registration is open."),
        "institutional_scale": _item(True, "A multi-track summit programme is named."),
        "named_speakers": _item(
            named_speakers,
            "Four named speakers are published." if named_speakers else None,
        ),
        "named_sponsors_exhibitors_conveners": _item(
            True, "A named sponsoring institute is published."
        ),
        "specific_ghus_topic": _item(True, "Energy-storage research is explicit."),
        "hub_geography": _item(True, "Boston is a supplied GHUS hub geography."),
        "recurring_prior_editions": _item(True, "The 2026 edition is linked."),
        "sector_coverage": _item(True, "The evidence supports ENERGY."),
    }


def _item(present: bool, evidence: str | None) -> dict[str, object]:
    return {"present": present, "evidence": evidence}


def _sector_codes() -> list[str]:
    return list(
        EVENT_TOOL_SCHEMA["properties"]["events"]["items"]["properties"][
            "sector_codes"
        ]["items"]["enum"]
    )


def _stats() -> dict[str, int]:
    return {
        "records_extracted": 0,
        "records_staged": 0,
        "records_promoted": 0,
        "records_in_sector": 0,
        "records_out_of_sector": 0,
        "records_relevant": 0,
    }
