from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event as sqla_event, text
from sqlalchemy.orm import sessionmaker

from agents.common.resolve_route import RouteDecision, Thresholds, route_event, zone_for_score
from agents.discovery.extractors.event import EventExtractor
from agents.discovery.normalize import event_natural_key, normalize_event_record, parse_date_to_iso
from agents.discovery.promote import promote
from agents.discovery.relevance import classify_sector_matches
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

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self.rolled_back = True
        else:
            self.committed = True
        return False


class FakeResult:
    def __init__(self, row=None):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row


class FakeSession:
    def __init__(self, *, fail_on_source=False, fail_on_index_dirty=False, event_row=None):
        self.fail_on_source = fail_on_source
        self.fail_on_index_dirty = fail_on_index_dirty
        self.event_row = event_row
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
        if self.fail_on_index_dirty and "INSERT INTO index_dirty" in sql:
            raise RuntimeError("index_dirty insert failed")
        if sql.strip().startswith("SELECT event_type"):
            return FakeResult(self.event_row)
        return FakeResult()


def fixture_doc(name="climate_week_events.html"):
    content = (FIXTURE_ROOT / name).read_text(encoding="utf-8")
    return FetchedDoc.from_content(url=f"fixture://{name}", content=content)


def _staged_event(normalized_payload=None):
    payload = {"name": "Climate Innovation Summit", "next_date": "2026-09-22"}
    if normalized_payload:
        payload.update(normalized_payload)
    return StagedRecord(
        run_id=str(uuid.uuid4()),
        raw_document_id=None,
        entity_type="event",
        natural_key="climate-innovation-summit|2026-09-22",
        source_url="fixture://events",
        payload={},
        normalized_payload=payload,
        prompt_version="event_v1",
        extracted_at="2026-08-10T00:00:00+00:00",
    )


def _empty_event_row():
    return {
        "event_type": None,
        "description": None,
        "location": None,
        "website": None,
        "thematic_focus": None,
        "expected_attendance": None,
        "access_type": None,
        "recurring_pattern": None,
        "next_date": None,
        "sponsoring_orgs": None,
        "source_id": None,
    }


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


def test_out_of_sector_stage_status_and_empty_sector_guard():
    classified = classify_sector_matches(
        [
            normalize_event_record(
                {
                    "title": "New Sector Summit",
                    "start_date": "2026-09-23",
                    "source_url": "fixture://events",
                    "extracted_at": "2026-08-10T00:00:00+00:00",
                    "sector_codes": ["NOT_SEEDED"],
                }
            )
        ],
        valid_sector_codes={"ENERGY"},
    )
    store = InMemoryStageStore()
    staged = stage_record(
        store,
        run_id=str(uuid.uuid4()),
        raw_document_id=None,
        entity_type="event",
        record=classified[0],
        prompt_version="event_v1",
    )

    assert classified[0]["sector_match"] == "out_of_sector"
    assert staged.sector_match == "out_of_sector"
    assert staged.status == "out_of_sector"

    with pytest.raises(RuntimeError, match="sector code set is empty"):
        classify_sector_matches(classified, valid_sector_codes=set())


def test_promote_refuses_out_of_sector_staged_records():
    staged = _staged_event()
    staged.sector_match = "out_of_sector"
    staged.status = "out_of_sector"

    with pytest.raises(RuntimeError, match="out_of_sector staged records must not be promoted"):
        promote(staged, RouteDecision(zone="create", score=0.0), session=FakeSession(), live=True)


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


def test_promote_dry_run_and_live_execute_same_statements_with_commit_boundary_only():
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
    route = RouteDecision(zone="create", score=0.0)
    dry_session = FakeSession()
    live_session = FakeSession()

    dry_result = promote(staged, route, session=dry_session, live=False)
    live_result = promote(staged, route, session=live_session, live=True)

    assert dry_session.statements == live_session.statements
    assert dry_session.transactions[-1].rolled_back
    assert not dry_session.transactions[-1].committed
    assert live_session.transactions[-1].committed
    assert not live_session.transactions[-1].rolled_back
    assert dry_result.action == "would_create"
    assert dry_result.dry_run is True
    assert live_result.action == "created"
    assert live_result.dry_run is False


def test_promote_absorb_marks_index_dirty_before_commit():
    event_id = str(uuid.uuid4())
    session = FakeSession(event_row=_empty_event_row())
    result = promote(
        _staged_event({"description": "Updated climate event profile", "next_date": None}),
        RouteDecision(zone="absorb", score=1.0, target_entity_id=event_id),
        session=session,
        live=True,
    )

    assert result.action == "absorbed"
    assert result.fields_absorbed == ["description"]
    update_index = next(index for index, sql in enumerate(session.statements) if "UPDATE event" in sql)
    dirty_index = next(index for index, sql in enumerate(session.statements) if "INSERT INTO index_dirty" in sql)
    assert update_index < dirty_index
    assert session.transactions[-1].committed
    assert not session.transactions[-1].rolled_back


def test_promote_index_dirty_failure_rolls_back_canonical_create():
    session = FakeSession(fail_on_index_dirty=True)

    with pytest.raises(RuntimeError, match="index_dirty insert failed"):
        promote(_staged_event(), RouteDecision(zone="create", score=0.0), session=session, live=True)

    event_index = next(index for index, sql in enumerate(session.statements) if "INSERT INTO event" in sql)
    dirty_index = next(index for index, sql in enumerate(session.statements) if "INSERT INTO index_dirty" in sql)
    assert event_index < dirty_index
    assert session.transactions[-1].rolled_back
    assert not session.transactions[-1].committed


def test_promote_dry_run_and_live_emit_same_sql_with_engine_listener():
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
    route = RouteDecision(zone="create", score=0.0)

    dry_sql, dry_result, dry_count = _captured_promote_sql(staged, route, live=False)
    live_sql, live_result, live_count = _captured_promote_sql(staged, route, live=True)

    assert dry_sql == live_sql
    assert dry_count == 0
    assert live_count == 1
    assert dry_result.action == "would_create"
    assert live_result.action == "created"


def _captured_promote_sql(staged: StagedRecord, route: RouteDecision, *, live: bool):
    engine = create_engine("sqlite:///:memory:", future=True)
    _create_sqlite_promotion_schema(engine)
    statements: list[str] = []

    @sqla_event.listens_for(engine, "before_cursor_execute")
    def capture_statement(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith(("INSERT INTO source", "INSERT INTO event", "UPDATE event", "INSERT INTO index_dirty")):
            statements.append(statement)

    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    session = SessionLocal()
    try:
        result = promote(staged, route, session=session, live=live)
        event_count = session.execute(text("SELECT count(*) FROM event")).scalar_one()
        return statements, result, event_count
    finally:
        session.close()


def _create_sqlite_promotion_schema(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE source ("
                "source_id TEXT PRIMARY KEY, source_type TEXT, url TEXT, retrieved_at TEXT, "
                "description TEXT, trust_tier TEXT)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE event ("
                "event_id TEXT PRIMARY KEY, name TEXT, source_id TEXT, event_type TEXT, "
                "description TEXT, location TEXT, website TEXT, thematic_focus TEXT, "
                "expected_attendance TEXT, access_type TEXT, recurring_pattern TEXT, "
                "next_date TEXT, sponsoring_orgs TEXT)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE index_dirty ("
                "entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, "
                "marked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "PRIMARY KEY (entity_type, entity_id))"
            )
        )
