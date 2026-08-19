from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from agents.common.resolve_route import RouteDecision, Thresholds, route_event, zone_for_score
from agents.discovery.extractors.event import EventExtractor
from agents.discovery.normalize import event_natural_key, normalize_event_record, parse_date_to_iso
from agents.discovery.promote import promote
from agents.discovery.sources.base import FetchedDoc
from agents.discovery.stage import InMemoryStageStore, StagedRecord, stage_record

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "agents"


class StubToolClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def extract_with_tool(self, **kwargs):
        self.calls += 1
        assert kwargs["tool_name"] == "record_events"
        assert kwargs["temperature"] == 0.0
        return self.payload


class FakeTransaction:
    def __init__(self):
        self.rolled_back = False
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self.rolled_back = True
        else:
            self.committed = True
        return False


class FakeResult:
    def mappings(self):
        return self

    def first(self):
        return None


class FakeSession:
    def __init__(self, *, fail_on_source=False):
        self.fail_on_source = fail_on_source
        self.statements = []
        self.transactions = []

    def begin(self):
        tx = FakeTransaction()
        self.transactions.append(tx)
        return tx

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        if self.fail_on_source and "INSERT INTO source" in sql:
            raise RuntimeError("source insert failed")
        return FakeResult()


def fixture_doc(name="climate_week_events.html"):
    content = (FIXTURE_ROOT / name).read_text(encoding="utf-8")
    return FetchedDoc.from_content(url=f"fixture://{name}", content=content)


def test_normalize_dates_and_natural_key_stability():
    assert parse_date_to_iso("September 22, 2026") == "2026-09-22"
    assert parse_date_to_iso("Sept. 24-26, 2026") == "2026-09-24"
    assert parse_date_to_iso("2026-09-25") == "2026-09-25"
    assert parse_date_to_iso("10/01/2026") == "2026-10-01"
    assert (
        event_natural_key(" Climate  Innovation Summit ", "2026-09-22")
        == event_natural_key("climate-innovation summit", "2026-09-22")
    )


def test_event_extractor_fixture_page_to_expected_records():
    payload = json.loads((FIXTURE_ROOT / "climate_week_events.expected.json").read_text(encoding="utf-8"))
    extractor = EventExtractor(StubToolClient(payload))
    records = extractor.extract(fixture_doc())
    assert [record["title"] for record in records] == [event["title"] for event in payload["events"]]
    assert all(record["source_url"] == "fixture://climate_week_events.html" for record in records)
    assert all(record["prompt_version"] == "event_v1" for record in records)


def test_event_extractor_no_events_returns_empty_list():
    extractor = EventExtractor(StubToolClient({"events": []}))
    assert extractor.extract(fixture_doc("no_events.html")) == []


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.75, "absorb"),
        (0.7499, "review"),
        (0.25, "review"),
        (0.2499, "create"),
    ],
)
def test_routing_boundaries(score, expected):
    thresholds = Thresholds(high=0.75, low=0.25)
    assert zone_for_score(score, thresholds) == expected


def test_dry_run_and_live_routing_decisions_are_identical():
    thresholds = Thresholds(high=0.75, low=0.25)
    record = normalize_event_record({"title": "Climate Innovation Summit", "start_date": "2026-09-22"})
    candidates = [{"event_id": "evt-1", "name": "Climate Innovation Summit", "next_date": "2026-09-22"}]

    dry_decision = route_event(record, candidates, thresholds=thresholds)
    live_decision = route_event(record, candidates, thresholds=thresholds)

    assert dry_decision == live_decision
    assert dry_decision.zone == "absorb"
    assert dry_decision.score == 1.0


def test_staging_same_run_twice_is_idempotent():
    store = InMemoryStageStore()
    run_id = str(uuid.uuid4())
    record = normalize_event_record(
        {
            "title": "Climate Innovation Summit",
            "start_date": "2026-09-22",
            "source_url": "fixture://events",
            "extracted_at": "2026-08-10T00:00:00+00:00",
            "sector_codes": ["ENERGY"],
        }
    )
    first = stage_record(store, run_id=run_id, raw_document_id=None, entity_type="event", record=record, prompt_version="event_v1")
    second = stage_record(store, run_id=run_id, raw_document_id=None, entity_type="event", record=record, prompt_version="event_v1")

    assert store.row_count() == 1
    assert first.staged_record_id == second.staged_record_id


def test_promote_provenance_failure_prevents_entity_insert():
    staged = StagedRecord(
        run_id=str(uuid.uuid4()),
        raw_document_id=None,
        entity_type="event",
        natural_key="climate-innovation-summit|2026-09-22",
        source_url="fixture://events",
        payload={},
        normalized_payload={"name": "Climate Innovation Summit", "next_date": "2026-09-22"},
        prompt_version="event_v1",
        extracted_at="2026-08-10T00:00:00+00:00",
    )
    session = FakeSession(fail_on_source=True)

    with pytest.raises(RuntimeError, match="source insert failed"):
        promote(staged, RouteDecision(zone="create", score=0.0), session=session, live=True)

    assert session.transactions[-1].rolled_back
    assert not any("INSERT INTO event" in sql for sql in session.statements)
