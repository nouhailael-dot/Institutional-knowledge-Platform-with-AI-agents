from __future__ import annotations

import copy
import csv
import json
import uuid
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from agents.common.config import load_sources_config
from agents.common.cost import CostMeter
from agents.common.raw_storage import RawContentStore
from agents.common.resolve_route import RouteDecision
from agents.common.run_log import InMemoryRunLog
from agents.discovery.event_qualification import qualify_event
from agents.discovery.extractors.event import (
    EVENT_CANONICAL_COLUMN_BY_FIELD,
    EVENT_FIELDS,
    EVENT_TOOL_SCHEMA,
    EventRecordValidationError,
)
from agents.discovery.promote import promote
from agents.discovery.run import _extract_stage_route_promote
from agents.discovery.search.event_scoring import (
    EVENT_RUBRIC_ANCHORS,
    RUBRIC_ITEM_NAMES,
    EventRubricExtractor,
    PreExtractedEventExtractor,
    event_rubric_record_schema,
    event_score_band,
    event_score_thresholds,
    read_analysis_cache,
    rerank_top_event_candidates,
    score_event_rubric,
    validate_event_analysis,
    write_analysis_cache,
)
from agents.discovery.search.models import CandidateRecord, SearchResult
from agents.discovery.search.phase2 import (
    InMemoryDiscoveredDomainStore,
    _collapse_extracted_event_duplicates,
    _qualification_capped_event_band,
    fetch_score_stage_events,
    plan_event_fetches,
)
from agents.discovery.search.report import (
    EVENT_REPORT_FIELDS,
    write_candidate_report,
    write_candidate_spreadsheet,
)
from agents.discovery.search.triage import SearchTriageClient
from agents.discovery.sources.base import FetchedDoc
from agents.discovery.stage import InMemoryStageStore, StagedRecord
from agents.evals import event_rubric_distribution
from src.db.models import Event

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
    assert "compact labels" in prompt["record_length_rule"]
    assert "Do not reproduce speaker names" in client.calls[0]["system"]
    record_schema = client.calls[0]["input_schema"]["properties"]["record"]
    assert "participant_people" not in record_schema["properties"]


def test_event_rubric_accepts_explanatory_evidence_when_item_is_absent():
    payload = _analysis_payload()
    payload["rubric"]["institutional_scale"] = {
        "present": False,
        "evidence": "The page does not publish an institutional programme or exhibition.",
    }

    analysis = validate_event_analysis(
        payload,
        sector_codes=_sector_codes(),
        run_date=RUN_DATE,
    )
    score = score_event_rubric(
        analysis.rubric,
        config=load_sources_config(PROJECT_ROOT)["open_web_discovery"],
    )

    assert analysis.rubric["institutional_scale"]["present"] is False
    assert analysis.rubric["institutional_scale"]["evidence"].startswith("The page does not")
    assert score.contributions["institutional_scale"] == 0.0


def test_event_rubric_retries_once_when_required_top_level_object_is_missing():
    class SequentialToolClient:
        def __init__(self):
            self.responses = [
                {"rubric": _analysis_payload()["rubric"]},
                _analysis_payload(),
            ]
            self.calls: list[dict[str, object]] = []

        def extract_with_tool(self, **kwargs):
            self.calls.append(kwargs)
            return copy.deepcopy(self.responses.pop(0))

    client = SequentialToolClient()
    analysis = EventRubricExtractor(client).extract(
        FetchedDoc.from_content(
            url="https://events.example/summit",
            content="One energy summit",
        ),
        sector_codes=_sector_codes(),
        hub_names=["Texas Water Systems Hub"],
        run_date=RUN_DATE,
    )

    assert analysis.record["title"] == "GHUS Energy Summit"
    assert len(client.calls) == 2
    assert "Retry once with exactly the top-level keys rubric and record" in client.calls[1][
        "user"
    ]


def test_event_record_schema_carries_every_canonical_string_length():
    rubric_schema = event_rubric_record_schema(sector_codes=_sector_codes())
    rubric_properties = rubric_schema["properties"]["record"]["properties"]
    extractor_properties = EVENT_TOOL_SCHEMA["properties"]["events"]["items"]["properties"]
    constrained_fields = {
        field_name: int(Event.__table__.columns[column_name].type.length)
        for field_name, column_name in EVENT_CANONICAL_COLUMN_BY_FIELD.items()
        if getattr(Event.__table__.columns[column_name].type, "length", None) is not None
    }

    assert constrained_fields
    for field_name, max_length in constrained_fields.items():
        assert rubric_properties[field_name]["maxLength"] == max_length
        assert extractor_properties[field_name]["maxLength"] == max_length


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


def test_event_record_longer_than_canonical_column_is_rejected():
    payload = _analysis_payload(
        record={
            **_event_record(),
            "location": "x" * 256,
        }
    )

    with pytest.raises(
        EventRecordValidationError,
        match=r"location.*exceeds canonical max length 255 \(got 256\)",
    ):
        validate_event_analysis(
            payload,
            sector_codes=_sector_codes(),
            run_date=RUN_DATE,
        )


def test_event_record_validation_failure_does_not_stop_other_candidates(tmp_path):
    config = copy.deepcopy(load_sources_config(PROJECT_ROOT)["open_web_discovery"])
    config.update({"max_pages_fetched": 2, "max_new_domains": 2})
    invalid = _analysis_payload(
        record={
            **_event_record(),
            "location": "x" * 256,
        }
    )
    low_rubric = {name: _item(False, None) for name in RUBRIC_ITEM_NAMES}
    valid = {"rubric": low_rubric, "record": _event_record()}

    class SequentialToolClient:
        def __init__(self):
            self.responses = [invalid, valid]
            self.calls = 0

        def extract_with_tool(self, **_kwargs):
            response = self.responses[self.calls]
            self.calls += 1
            return copy.deepcopy(response)

    class Source:
        def fetch(self, url):
            return FetchedDoc.from_content(url=url, content=f"Event page for {url}")

    client = SequentialToolClient()
    run_log = InMemoryRunLog()
    run_id = run_log.start_run(
        source_name="open_web_search", entity_type="event", live=False, config={}
    )
    stats = {
        "pages_fetched": 0,
        "skipped_unchanged": 0,
        "records_extracted": 0,
        "records_staged": 0,
        "records_promoted": 0,
        "fetch_failures": 0,
    }
    audit_rows = []

    outcome = fetch_score_stage_events(
        run_id=run_id,
        candidates=[_candidate(0, score=None), _candidate(1, score=None)],
        config=config,
        root=PROJECT_ROOT,
        session=None,
        live=False,
        run_log=run_log,
        cost_meter=CostMeter(max_usd=5),
        stats=stats,
        audit_rows=audit_rows,
        sector_codes=_sector_codes(),
        hub_names=["Boston"],
        source=Source(),
        rubric_extractor=EventRubricExtractor(client),
        raw_store=RawContentStore(tmp_path / "raw"),
        domain_store=InMemoryDiscoveredDomainStore(),
        event_candidates=[],
        run_date=RUN_DATE,
    )

    first, second = outcome.candidates
    assert first.triage_verdict == "analysis_failed"
    assert first.score_band == "analysis_failed"
    assert "location" in (first.triage_reason or "")
    assert second.record_preview["title"] == "GHUS Energy Summit"
    assert second.rubric is not None
    assert client.calls == 2
    assert stats["event_record_validation_failures"] == 1
    assert stats["fetch_failures"] == 0
    assert audit_rows[0]["status"] == "record_validation_failed"
    assert any("record validation failures: 1" in reason for reason in outcome.attention_reasons)


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


def test_empty_event_rubric_is_below_low_and_thresholds_come_from_config():
    config = {
        "event_score_thresholds": {"auto_low": 0.35, "auto_high": 0.75},
        "event_rubric_weights": load_sources_config(PROJECT_ROOT)["open_web_discovery"][
            "event_rubric_weights"
        ],
    }
    rubric = {name: _item(False, None) for name in RUBRIC_ITEM_NAMES}
    score = score_event_rubric(rubric, config=config)

    assert event_score_thresholds(config) == (0.35, 0.75)
    assert score.total == 0.0
    assert event_score_band(score.total, config) == "auto_low"
    assert event_score_band(0.50, config) == "review"
    assert event_score_band(0.80, config) == "auto_high"


def test_past_non_minable_event_caps_a_high_score_at_auto_low():
    rubric = _rubric()
    rubric["date_within_window"] = _item(False, None)
    rubric["named_speakers"] = _item(False, None)
    record = {**_event_record(), "start_date": "2026-04-23"}
    qualification = qualify_event(
        record,
        run_date=RUN_DATE,
        config={"forward_window_months": 12},
        rubric=rubric,
    )

    assert qualification.minable is False
    assert _qualification_capped_event_band(
        "auto_high",
        qualification=qualification,
        record=record,
        run_date=RUN_DATE,
    ) == "auto_low"


def test_event_fetch_plan_analyzes_one_page_per_registrable_domain():
    candidates = [
        replace(_candidate(index, score=score), url=f"https://events.arpa-e.energy.gov/{index}", domain="events.arpa-e.energy.gov")
        for index, score in enumerate((0.8, 0.9, 0.7))
    ]

    plan = plan_event_fetches(
        candidates,
        domain_store=InMemoryDiscoveredDomainStore(),
        config={"max_pages_fetched": 10, "max_new_domains": 10},
    )

    assert len(plan.candidates) == 1
    assert plan.candidates[0].fit_score == 0.9
    assert plan.duplicates_collapsed == 2


def test_extracted_event_duplicate_prefers_the_events_own_domain():
    event_record = {
        **_event_record(),
        "title": "ARPA-E Energy Innovation Summit",
        "start_date": "2027-03-10",
        "website": "https://arpa-e.energy.gov/summit",
    }
    coverage = replace(
        _candidate(0, score=0.95),
        url="https://news.example.org/arpa-e-summit",
        domain="news.example.org",
        rubric=_rubric(),
        record_preview=event_record,
        score_band="auto_high",
    )
    own_site = replace(
        _candidate(1, score=0.75),
        url="https://arpa-e.energy.gov/summit",
        domain="arpa-e.energy.gov",
        rubric=_rubric(),
        record_preview=event_record,
        score_band="auto_high",
    )

    collapsed, count = _collapse_extracted_event_duplicates([coverage, own_site])

    assert count == 1
    assert collapsed[0].duplicate_of == own_site.candidate_id
    assert collapsed[1].duplicate_of is None


def test_event_rerank_changes_only_the_configured_top_group():
    class ReverseReranker:
        def rerank_group(self, candidates):
            return [(candidate.url, "relative event value") for candidate in reversed(candidates)]

    candidates = [
        _candidate(index, score=score)
        for index, score in enumerate((0.9, 0.8, 0.7))
    ]
    updated, attention = rerank_top_event_candidates(
        candidates,
        reranker=ReverseReranker(),
        config={"event_rerank_top_n": 2, "event_rerank_group_size": 2},
    )

    assert attention == []
    assert [candidate.rerank_position for candidate in updated] == [2, 1, None]


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
    participant_rows = [row for row in stage_store.rows.values() if row.entity_type == "actor"]
    assert all(row.route["zone"] == "review" for row in participant_rows)
    assert all(
        row.route["metadata"]["review_kind"] == "classification"
        and row.route["metadata"]["issue"] == "category_doubt"
        for row in participant_rows
    )
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


def test_event_previews_keep_fetched_analysis_failures_visible(tmp_path):
    succeeded = CandidateRecord(
        candidate_id=str(uuid.uuid4()),
        run_id="run-1",
        entity_type="event",
        query="energy summit",
        provider="stub",
        url="https://events.example/summit",
        title="Energy Summit",
        snippet="Summit",
        domain="events.example",
        triage_verdict="accepted",
        triage_reason="event rubric score 0.820 -> auto_high",
        fit_score=0.82,
        page_fetched=True,
        rubric=_rubric(),
        record_preview=_event_record(),
        score_band="auto_high",
    )
    failed = CandidateRecord(
        candidate_id=str(uuid.uuid4()),
        run_id="run-1",
        entity_type="event",
        query="water forum",
        provider="stub",
        url="https://events.example/failed",
        title="Failed Event Page",
        snippet="Forum",
        domain="events.example",
        triage_verdict="analysis_failed",
        triage_reason="event record validation failed: location is too long",
        fit_score=None,
        page_fetched=True,
        rubric=None,
        record_preview=None,
        score_band="analysis_failed",
    )
    csv_path = tmp_path / "event-records.csv"
    report_path = tmp_path / "event-report.md"

    write_candidate_spreadsheet(csv_path, [succeeded, failed])
    write_candidate_report(
        report_path,
        run_id="run-1",
        status="attention",
        status_reason="one analysis failure",
        stats={},
        queries={"event": []},
        candidates=[succeeded, failed],
    )

    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    failed_row = next(row for row in rows if row["url"].endswith("/failed"))
    assert failed_row["triage_verdict"] == "analysis_failed"
    assert "location is too long" in failed_row["triage_reason"]
    assert failed_row["name"] == ""
    report = report_path.read_text(encoding="utf-8")
    assert report.count("https://events.example/failed") == 2
    assert "event record validation failed" in report


def test_incomplete_event_replay_returns_nonzero(monkeypatch):
    failed = CandidateRecord(
        candidate_id=str(uuid.uuid4()),
        run_id="run-1",
        entity_type="event",
        query="stored-page replay",
        provider="stored",
        url="https://events.example/failed",
        title=None,
        snippet=None,
        domain="events.example",
        triage_verdict="analysis_failed",
        triage_reason="event rubric analysis failed",
        fit_score=None,
        page_fetched=True,
        score_band="analysis_failed",
    )
    summary = {
        "run_id": "run-1",
        "run_date": RUN_DATE.isoformat(),
        "model": "stub",
        "prompt_version": "event-test",
        "pages": 1,
        "cache_hits": 0,
        "analysis_failures": 1,
        "cost_usd": 0.0,
        "bands": {"analysis_failed": 1},
        "qualifications": {},
        "rerank_attention": [],
        "candidates": [failed],
    }
    monkeypatch.setattr(
        event_rubric_distribution,
        "evaluate_stored_run",
        lambda **_kwargs: summary,
    )

    exit_code = event_rubric_distribution.main(
        ["--run-id", "run-1", "--run-date", RUN_DATE.isoformat()]
    )

    assert exit_code == 1
    assert "Status: incomplete" in event_rubric_distribution.to_markdown(summary)


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
        "absorbed": 0,
        "queued_for_review": 0,
        "created": 0,
    }


def _candidate(index: int, *, score: float | None) -> CandidateRecord:
    return CandidateRecord(
        candidate_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        entity_type="event",
        query="event query",
        provider="stub",
        url=f"https://events-{index}.example/summit",
        title=f"Event {index}",
        snippet="One event",
        domain=f"events-{index}.example",
        triage_verdict="accepted",
        triage_reason="fetch",
        fit_score=score,
    )
