from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy import event as sqla_event
from sqlalchemy.orm import sessionmaker

from agents.common.resolve_route import (
    RouteDecision,
    Thresholds,
    route_actor,
    route_event,
    route_person,
    zone_for_score,
)
from agents.discovery.extractors.actor import ACTOR_FIELDS, ActorExtractor
from agents.discovery.extractors.event import (
    EventExtractor,
    displayed_event_total,
    hubdb_listing_rows,
)
from agents.discovery.extractors.person import PERSON_FIELDS, PersonExtractor
from agents.discovery.extractors.unga_guide import UngaGuideExtractor
from agents.discovery.extractors.unga_programme import UngaProgrammeExtractor
from agents.discovery.normalize import (
    event_natural_key,
    normalize_actor_record,
    normalize_event_record,
    normalize_person_record,
    parse_date_to_iso,
)
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
        assert "temperature" not in kwargs
        return self.payload


class BatchCountingToolClient:
    def __init__(self):
        self.calls = 0
        self.event_card_counts: list[int] = []
        self.payload_sizes: list[int] = []

    def extract_with_tool(self, **kwargs):
        self.calls += 1
        user_payload = kwargs["user"]
        self.event_card_counts.append(user_payload.count("event-card"))
        self.payload_sizes.append(len(user_payload.encode("utf-8")))
        return {"events": []}


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
    def __init__(self, row=None, *, rowcount=1):
        self.row = row
        self.rowcount = rowcount

    def mappings(self):
        return self

    def first(self):
        return self.row


class FakeSession:
    def __init__(
        self,
        *,
        fail_on_source=False,
        fail_on_index_dirty=False,
        event_row=None,
        actor_row=None,
        update_rowcount=1,
    ):
        self.fail_on_source = fail_on_source
        self.fail_on_index_dirty = fail_on_index_dirty
        self.event_row = event_row
        self.actor_row = actor_row
        self.update_rowcount = update_rowcount
        self.statements = []
        self.params = []
        self.transactions = []

    def begin(self):
        tx = FakeTransaction()
        self.transactions.append(tx)
        return tx

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        self.params.append(params or {})
        if self.fail_on_source and "INSERT INTO source" in sql:
            raise RuntimeError("source insert failed")
        if self.fail_on_index_dirty and "INSERT INTO index_dirty" in sql:
            raise RuntimeError("index_dirty insert failed")
        if sql.strip().startswith("SELECT event_type"):
            return FakeResult(self.event_row)
        if sql.strip().startswith("SELECT") and " FROM actor WHERE actor_id" in sql:
            return FakeResult(self.actor_row)
        if sql.strip().startswith("UPDATE actor"):
            return FakeResult(rowcount=self.update_rowcount)
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


def _staged_person(normalized_payload=None):
    payload = {
        "name": "Dr. Amina Example",
        "affiliation": "Example Climate Lab",
        "role": "Research Director",
        "public_profile_url": "https://example.org/amina",
        "research_area": "climate analytics",
    }
    if normalized_payload:
        payload.update(normalized_payload)
    normalized = normalize_person_record(payload)
    return StagedRecord(
        run_id=str(uuid.uuid4()),
        raw_document_id=None,
        entity_type="person",
        natural_key=str(normalized["natural_key"]),
        source_url="fixture://people",
        payload={},
        normalized_payload=normalized,
        prompt_version="person_v1",
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
    assert event_natural_key(" Climate  Innovation Summit ", "2026-09-22") == event_natural_key(
        "climate-innovation summit", "2026-09-22"
    )


def test_event_extractor_fixture_page_to_expected_records():
    payload = json.loads(
        (FIXTURE_ROOT / "climate_week_events.expected.json").read_text(encoding="utf-8")
    )
    extractor = EventExtractor(StubToolClient(payload))
    records = extractor.extract(fixture_doc())
    assert [record["title"] for record in records] == [
        event["title"] for event in payload["events"]
    ]
    assert all(record["source_url"] == "fixture://climate_week_events.html" for record in records)
    assert all(record["prompt_version"] == "event_v1" for record in records)


def test_event_extractor_no_events_returns_empty_list():
    extractor = EventExtractor(StubToolClient({"events": []}))
    assert extractor.extract(fixture_doc("no_events.html")) == []


def test_climate_week_event_search_fixture_has_hubdb_rows():
    content = (FIXTURE_ROOT / "climate_week_event_search.html").read_text(encoding="utf-8")
    rows, found_listing = hubdb_listing_rows(content)

    assert found_listing is True
    assert len(rows) > 100
    assert displayed_event_total(content) == 428
    assert all("event-card" in row for row in rows[:3])


def test_climate_week_hubdb_listing_is_extracted_in_row_batches():
    content = """
    <html><body>
      <div class="hubdb-listing">
        <article class="event-card"><h2>One</h2></article>
        <article class="event-card"><h2>Two</h2></article>
        <article class="event-card"><h2>Three</h2></article>
      </div>
    </body></html>
    """
    client = BatchCountingToolClient()
    extractor = EventExtractor(client, row_batch_size=2)
    doc = FetchedDoc.from_content(
        url="fixture://climate_week/event-search",
        content=content,
        meta={"extractor_mode": "hubdb_listing"},
    )

    assert extractor.extract(doc) == []
    assert client.calls == 2
    assert client.event_card_counts == [2, 1]
    assert max(client.payload_sizes) < len(content.encode("utf-8")) + 300


def test_climate_week_missing_hubdb_listing_warns(caplog):
    client = BatchCountingToolClient()
    extractor = EventExtractor(client, row_batch_size=2)
    doc = FetchedDoc.from_content(
        url="fixture://climate_week/event-search",
        content="<html><body>No listing here</body></html>",
        meta={"extractor_mode": "hubdb_listing"},
    )

    caplog.set_level(logging.WARNING)
    assert extractor.extract(doc) == []

    assert client.calls == 0
    assert "hubdb-listing container not found" in caplog.text
    assert "page_size_bytes=" in caplog.text


def test_climate_week_displayed_total_mismatch_sets_attention_reason():
    content = """
    <!-- event listing: total=5 fetched=3 pages_needed=2 max_pages=10 -->
    <div class="hubdb-listing">
      <article class="event-card"><h2>One</h2></article>
      <article class="event-card"><h2>Two</h2></article>
      <article class="event-card"><h2>Three</h2></article>
    </div>
    """
    extractor = EventExtractor(BatchCountingToolClient(), row_batch_size=10)
    doc = FetchedDoc.from_content(
        url="fixture://climate_week/event-search",
        content=content,
        meta={"extractor_mode": "hubdb_listing"},
    )

    assert extractor.extract(doc) == []
    assert extractor.attention_reasons
    assert "displays total=5 but parser found 3 rows" in extractor.attention_reasons[0]


def test_unga_guide_fixture_extracts_jsonld_events_without_llm():
    client = StubToolClient({"events": []})
    extractor = UngaGuideExtractor(client)
    doc = fixture_doc("unga_guide_home.html")

    records = extractor.extract(doc)

    assert client.calls == 0
    assert len(records) == 12
    assert records[0]["title"] == "UN Blockchain Week Conference 2026"
    assert records[0]["website"] == "https://unblockchainweek.com"
    assert set(records[0]["sector_codes"]) == {"AI", "SUSTAIN", "CROSS"}
    assert records[1]["sponsoring_orgs"] == "C3 Summit"


def test_unga_guide_unmapped_categories_do_not_default_to_cross():
    client = StubToolClient({"events": []})
    extractor = UngaGuideExtractor(client)
    content = """
    <article class="post-1 unga_event type-unga_event status-publish hentry
        unga_event_category-economic-development unga_event_category-government
        unga_event_category-human-rights unga_event_category-art-culture">
      <header><time datetime="2026-09-20"><span class="date">Sun, Sep 20</span></time></header>
      <div class="body">
        <h2 class="unga-event__title"><a href="https://ungaguide.com/events/unmapped/">Unmapped Convening</a></h2>
        <p class="unga-event__organizer">Example Organizer</p>
      </div>
    </article>
    """

    records = extractor.extract(
        FetchedDoc.from_content(url="fixture://unga-guide-unmapped", content=content)
    )
    classified = classify_sector_matches(
        [normalize_event_record(records[0])],
        valid_sector_codes={"AGRI", "AI", "ENERGY", "HEALTH", "SUSTAIN", "WATER"},
    )

    assert records[0]["sector_codes"] == []
    assert classified[0]["sector_match"] == "out_of_sector"


def test_unga_programme_fixture_extracts_provisional_schedule_without_llm():
    extractor = UngaProgrammeExtractor()
    doc = fixture_doc("unga_programme_meetings.html")

    records = extractor.extract(doc)

    assert len(records) == 9
    assert records[0]["title"] == "Opening of the 81st session"
    assert records[0]["start_date"] == "8 September 2026"
    climate = next(
        record
        for record in records
        if record["title"] == "High-level meeting on climate action and the just transition"
    )
    sea_level = next(record for record in records if "sea level rise" in str(record["title"]))
    pandemic = next(record for record in records if "pandemic prevention" in str(record["title"]))
    assert records[0]["sector_codes"] == []
    assert climate["sector_codes"] == ["SUSTAIN"]
    assert sea_level["sector_codes"] == ["SUSTAIN"]
    assert pandemic["sector_codes"] == ["HEALTH"]
    assert records[2]["start_date"] == "22 September 2026"
    assert records[2]["end_date"] == "28 September 2026"


def test_unga_programme_unmatched_schedule_row_routes_to_out_of_sector():
    extractor = UngaProgrammeExtractor()
    doc = fixture_doc("unga_programme_meetings.html")
    records = extractor.extract(doc)
    opening = records[0]

    classified = classify_sector_matches(
        [normalize_event_record(opening)],
        valid_sector_codes={"AGRI", "AI", "ENERGY", "HEALTH", "SUSTAIN", "WATER"},
    )

    assert opening["sector_codes"] == []
    assert classified[0]["sector_match"] == "out_of_sector"


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
    record = normalize_event_record(
        {"title": "Climate Innovation Summit", "start_date": "2026-09-22"}
    )
    candidates = [
        {"event_id": "evt-1", "name": "Climate Innovation Summit", "next_date": "2026-09-22"}
    ]

    dry_decision = route_event(record, candidates, thresholds=thresholds)
    live_decision = route_event(record, candidates, thresholds=thresholds)

    assert dry_decision == live_decision
    assert dry_decision.zone == "absorb"
    assert dry_decision.score == 1.0


def test_same_date_near_miss_event_title_routes_to_review():
    candidate_id = str(uuid.uuid4())
    record = normalize_event_record(
        {"title": "AI & Climate Summit 2026", "start_date": "2026-09-22"}
    )
    candidates = [
        {"event_id": candidate_id, "name": "AI and Climate Summit 2026", "next_date": "2026-09-22"}
    ]

    decision = route_event(record, candidates, thresholds=Thresholds(high=0.75, low=0.25))

    assert decision.zone == "review"
    assert decision.target_entity_id == candidate_id
    assert decision.metadata["staged_title"] == "AI & Climate Summit 2026"
    assert decision.metadata["candidate_title"] == "AI and Climate Summit 2026"
    assert decision.metadata["shared_start_date"] == "2026-09-22"


def test_same_event_title_with_different_start_date_does_not_fuzzy_match():
    record = normalize_event_record(
        {"title": "AI & Climate Summit 2026", "start_date": "2026-09-22"}
    )
    candidates = [
        {
            "event_id": str(uuid.uuid4()),
            "name": "AI & Climate Summit 2026",
            "next_date": "2027-09-22",
        }
    ]

    decision = route_event(record, candidates, thresholds=Thresholds(high=0.75, low=0.25))

    assert decision.zone == "create"
    assert decision.score == 0.0
    assert decision.target_entity_id is None


def test_event_fuzzy_review_threshold_is_read_from_config(tmp_path):
    config_dir = tmp_path / "agents" / "config"
    config_dir.mkdir(parents=True)
    record = normalize_event_record(
        {"title": "AI & Climate Summit 2026", "start_date": "2026-09-22"}
    )
    candidates = [
        {
            "event_id": str(uuid.uuid4()),
            "name": "AI and Climate Summit 2026",
            "next_date": "2026-09-22",
        }
    ]

    (config_dir / "sources.yaml").write_text(
        json.dumps({"routing": {"event_fuzzy_review_threshold": 0.99}}),
        encoding="utf-8",
    )
    strict = route_event(
        record, candidates, thresholds=Thresholds(high=0.75, low=0.25), project_root=tmp_path
    )

    (config_dir / "sources.yaml").write_text(
        json.dumps({"routing": {"event_fuzzy_review_threshold": 0.80}}),
        encoding="utf-8",
    )
    permissive = route_event(
        record, candidates, thresholds=Thresholds(high=0.75, low=0.25), project_root=tmp_path
    )

    assert strict.zone == "create"
    assert permissive.zone == "review"


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
    first = stage_record(
        store,
        run_id=run_id,
        raw_document_id=None,
        entity_type="event",
        record=record,
        prompt_version="event_v1",
    )
    second = stage_record(
        store,
        run_id=run_id,
        raw_document_id=None,
        entity_type="event",
        record=record,
        prompt_version="event_v1",
    )

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
    assert staged.status == "staged"

    with pytest.raises(RuntimeError, match="sector code set is empty"):
        classify_sector_matches(classified, valid_sector_codes=set())


def test_promote_refuses_out_of_sector_staged_records():
    staged = _staged_event()
    staged.sector_match = "out_of_sector"
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
    update_index = next(
        index for index, sql in enumerate(session.statements) if "UPDATE event" in sql
    )
    dirty_index = next(
        index for index, sql in enumerate(session.statements) if "INSERT INTO index_dirty" in sql
    )
    assert update_index < dirty_index
    assert session.transactions[-1].committed
    assert not session.transactions[-1].rolled_back


def test_promote_index_dirty_failure_rolls_back_canonical_create():
    session = FakeSession(fail_on_index_dirty=True)

    with pytest.raises(RuntimeError, match="index_dirty insert failed"):
        promote(
            _staged_event(), RouteDecision(zone="create", score=0.0), session=session, live=True
        )

    event_index = next(
        index for index, sql in enumerate(session.statements) if "INSERT INTO event" in sql
    )
    dirty_index = next(
        index for index, sql in enumerate(session.statements) if "INSERT INTO index_dirty" in sql
    )
    assert event_index < dirty_index
    assert session.transactions[-1].rolled_back
    assert not session.transactions[-1].committed


def test_event_review_route_writes_event_review_queue_row():
    candidate_id = str(uuid.uuid4())
    staged = _staged_event(
        {
            "name": "AI & Climate Summit 2026",
            "title": "AI & Climate Summit 2026",
            "start_date": "2026-09-22",
            "next_date": "2026-09-22",
        }
    )
    decision = route_event(
        staged.normalized_payload,
        [
            {
                "event_id": candidate_id,
                "name": "AI and Climate Summit 2026",
                "next_date": "2026-09-22",
            }
        ],
        thresholds=Thresholds(high=0.75, low=0.25),
    )
    session = FakeSession()

    result = promote(staged, decision, session=session, live=True)

    assert decision.zone == "review"
    assert result.action == "queued_for_review"
    assert result.entity_id == candidate_id
    assert any("INSERT INTO event_review_queue" in sql for sql in session.statements)
    assert session.transactions[-1].committed
    assert not session.transactions[-1].rolled_back


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
        if statement.startswith(
            ("INSERT INTO source", "INSERT INTO event", "UPDATE event", "INSERT INTO index_dirty")
        ):
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


class ActorStubToolClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0
        self.last_kwargs = None

    def extract_with_tool(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        return self.payload


class StubActorResolver:
    HIGH = 0.96
    LOW = 0.1889311318077817
    model_name = "combiner_name_mismatch"

    def __init__(self, score: float | None):
        self.score = score

    def _candidates(self, name: str):
        if self.score is None:
            return pd.DataFrame(columns=["actor_id", "name", "description", "hubs"])
        return pd.DataFrame(
            [
                {
                    "actor_id": "actor-candidate-1",
                    "name": "Candidate Actor",
                    "description": "Existing profile",
                    "hubs": "",
                }
            ]
        )

    def _score(self, record: dict[str, object], candidates):
        scored = candidates.copy()
        scored["score"] = [self.score]
        return scored


def test_actor_extractor_uses_tool_schema_and_preserves_nulls():
    actor = {field: None for field in ACTOR_FIELDS}
    actor.update(
        {
            "name": "Example Climate Lab",
            "description": "Develops climate analytics explicitly described on the page.",
            "website": "https://example.org",
            "country": "USA",
            "sector_codes": ["SUSTAIN"],
        }
    )
    client = ActorStubToolClient({"actors": [actor]})
    extractor = ActorExtractor(client)
    doc = FetchedDoc.from_content(
        url="fixture://actors", content="<html>Example Climate Lab</html>"
    )

    records = extractor.extract(doc)

    assert client.calls == 1
    assert client.last_kwargs["tool_name"] == "record_actors"
    assert "temperature" not in client.last_kwargs
    assert records[0]["name"] == "Example Climate Lab"
    assert records[0]["actor_type"] is None
    assert records[0]["source_url"] == "fixture://actors"
    assert records[0]["prompt_version"] == "actor_v1"


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.96, "absorb"),
        (0.9599, "review"),
        (0.1889311318077817, "review"),
        (0.1889, "create"),
        (None, "create"),
    ],
)
def test_actor_routing_uses_existing_resolver_thresholds(score, expected):
    record = normalize_actor_record(
        {
            "name": "Example Climate Lab",
            "description": "Climate analytics organization",
            "website": "https://example.org",
            "sector_codes": ["SUSTAIN"],
        }
    )

    decision = route_actor(record, StubActorResolver(score))

    assert decision.zone == expected
    if expected in {"absorb", "review"}:
        assert decision.target_entity_id == "actor-candidate-1"
    else:
        assert decision.target_entity_id is None


def test_promote_actor_create_writes_needs_review_actor_with_source_and_index_dirty():
    staged = _staged_event(
        {
            "name": "Example Climate Lab",
            "description": "Climate analytics organization",
            "website": "https://example.org",
            "sector_codes": ["SUSTAIN"],
        }
    )
    staged.entity_type = "actor"
    session = FakeSession()

    result = promote(staged, RouteDecision(zone="create", score=0.0), session=session, live=True)

    assert result.action == "created"
    assert result.entity_type == "actor"
    actor_insert = next(sql for sql in session.statements if "INSERT INTO actor" in sql)
    assert "verification_status" in actor_insert
    assert any("INSERT INTO source" in sql for sql in session.statements)
    assert any("INSERT INTO index_dirty" in sql for sql in session.statements)
    assert session.transactions[-1].committed


def test_promote_actor_create_truncates_long_slug_to_column_limit():
    staged = _staged_event(
        {
            "name": (
                "Merieux Foundation USA, Weill Cornell Medical College, GHESKIO Centers, "
                "Pan American Health Organization, Pandemic Fund, CEPI, APHL"
            ),
            "description": "Health preparedness organizer",
            "sector_codes": ["HEALTH"],
        }
    )
    staged.entity_type = "actor"
    session = FakeSession()

    promote(staged, RouteDecision(zone="create", score=0.0), session=session, live=True)

    actor_params = next(
        params
        for sql, params in zip(session.statements, session.params)
        if "INSERT INTO actor" in sql
    )
    assert len(actor_params["slug"]) <= 160
    assert actor_params["slug"].endswith(actor_params["actor_id"][:8])


def test_promote_actor_absorb_fills_only_empty_fields_with_gap_guard():
    actor_id = str(uuid.uuid4())
    staged = _staged_event(
        {
            "name": "Example Climate Lab",
            "description": "New description",
            "website": "https://example.org",
            "sector_codes": ["SUSTAIN"],
        }
    )
    staged.entity_type = "actor"
    session = FakeSession(
        actor_row={
            "actor_type": None,
            "actor_type_raw": None,
            "description": None,
            "website": "https://existing.example",
            "location_city": None,
            "state": None,
            "country": None,
            "primary_technical_focus": None,
            "technical_approach": None,
            "current_activities": None,
            "technology_ip_notes": None,
            "key_constraints": None,
            "estimated_trl": None,
            "primary_lifecycle_role": None,
            "source_id": None,
            "verification_status": None,
        }
    )

    result = promote(
        staged,
        RouteDecision(zone="absorb", score=0.99, target_entity_id=actor_id),
        session=session,
        live=True,
    )

    assert result.action == "absorbed"
    assert result.fields_absorbed == ["description"]
    update_sql = next(sql for sql in session.statements if "UPDATE actor" in sql)
    assert "description = :description" in update_sql
    assert "website = :website" not in update_sql
    assert "description IS NULL" in update_sql
    assert "source_id IS NULL" in update_sql


def test_promote_actor_absorb_raises_when_gap_guard_loses_race():
    actor_id = str(uuid.uuid4())
    staged = _staged_event({"name": "Example Climate Lab", "description": "New description"})
    staged.entity_type = "actor"
    session = FakeSession(
        actor_row={field: None for field in [*ACTOR_FIELDS, "source_id", "verification_status"]},
        update_rowcount=0,
    )

    with pytest.raises(RuntimeError, match="actor absorb gap guard matched zero rows"):
        promote(
            staged,
            RouteDecision(zone="absorb", score=0.99, target_entity_id=actor_id),
            session=session,
            live=True,
        )

    assert session.transactions[-1].rolled_back


@pytest.mark.parametrize(
    "name",
    [
        (
            "International Telecommunication Union (ITU), "
            "United Nations Development Programme (UNDP)"
        ),
        (
            "President of the United Nations General Assembly, "
            "in collaboration with the World Health Organization (WHO)"
        ),
        "Office of the Secretary-General",
        "Permanent Mission of Canada to the United Nations",
        "Example Climate Council and Example Health Foundation",
    ],
)
def test_promote_actor_absorb_guard_sends_combined_or_role_names_to_review(name):
    existing_actor_id = str(uuid.uuid4())
    staged = _staged_event({"name": name, "description": "Future actor source candidate"})
    staged.entity_type = "actor"
    session = FakeSession()

    result = promote(
        staged,
        RouteDecision(
            zone="absorb",
            score=0.99,
            target_entity_id=existing_actor_id,
            candidate_ids=[existing_actor_id],
            metadata={"model": "combiner_name_mismatch"},
        ),
        session=session,
        live=True,
    )

    assert result.action == "queued_for_review"
    assert result.zone == "review"
    assert result.entity_id != existing_actor_id
    assert not any(sql.strip().startswith("UPDATE actor") for sql in session.statements)
    assert any("INSERT INTO actor" in sql for sql in session.statements)
    assert any("INSERT INTO review_queue" in sql for sql in session.statements)
    assert session.transactions[-1].committed


def test_promote_actor_review_creates_candidate_and_existing_review_queue_row():
    existing_actor_id = str(uuid.uuid4())
    staged = _staged_event(
        {"name": "Example Climate Lab", "description": "Climate analytics organization"}
    )
    staged.entity_type = "actor"
    session = FakeSession()

    result = promote(
        staged,
        RouteDecision(
            zone="review",
            score=0.5,
            target_entity_id=existing_actor_id,
            metadata={"model": "combiner_name_mismatch"},
        ),
        session=session,
        live=True,
    )

    assert result.action == "queued_for_review"
    assert result.entity_type == "actor"
    assert any("INSERT INTO actor" in sql for sql in session.statements)
    assert any("INSERT INTO review_queue" in sql for sql in session.statements)
    assert any("INSERT INTO index_dirty" in sql for sql in session.statements)
    assert session.transactions[-1].committed


def test_person_extractor_only_public_professional_fields():
    person = {field: None for field in PERSON_FIELDS}
    person.update(
        {
            "name": "Dr. Amina Example",
            "affiliation": "Example Climate Lab",
            "role": "Research Director",
            "public_profile_url": "https://example.org/amina",
            "research_area": "climate analytics",
        }
    )
    client = ActorStubToolClient({"people": [person]})
    extractor = PersonExtractor(client)
    doc = FetchedDoc.from_content(
        url="fixture://people", content="<html>Dr. Amina Example, Research Director</html>"
    )

    records = extractor.extract(doc)

    assert client.calls == 1
    assert client.last_kwargs["tool_name"] == "record_people"
    assert "temperature" not in client.last_kwargs
    schema_text = json.dumps(client.last_kwargs["input_schema"])
    for forbidden in ("email", "phone", "tel", "bio"):
        assert forbidden not in schema_text.lower()
    assert records[0]["name"] == "Dr. Amina Example"
    assert records[0]["affiliation"] == "Example Climate Lab"
    assert records[0]["source_url"] == "fixture://people"
    assert records[0]["prompt_version"] == "person_v1"


def test_person_routing_review_only_even_on_perfect_name_match():
    candidate_id = str(uuid.uuid4())
    record = normalize_person_record(
        {
            "name": "Dr. Amina Example",
            "affiliation": "Example Climate Lab",
            "public_profile_url": "https://example.org/amina",
        }
    )

    decision = route_person(
        record,
        [
            {
                "person_id": candidate_id,
                "full_name": "Dr. Amina Example",
                "title": "Research Director",
                "linkedin_url": None,
            }
        ],
    )

    assert decision.zone == "review"
    assert decision.score == 1.0
    assert decision.target_entity_id == candidate_id
    assert decision.candidate_ids == [candidate_id]
    assert decision.metadata["candidate_name"] == "Dr. Amina Example"


def test_promote_person_guard_raises_for_non_review_route():
    staged = _staged_person()

    with pytest.raises(RuntimeError, match="person records must route to review only"):
        promote(staged, RouteDecision(zone="create", score=0.0), session=FakeSession(), live=True)


def test_promote_person_review_writes_person_review_queue_only():
    staged = _staged_person()
    session = FakeSession()
    candidate_id = str(uuid.uuid4())

    result = promote(
        staged,
        RouteDecision(
            zone="review",
            score=1.0,
            target_entity_id=candidate_id,
            candidate_ids=[candidate_id],
            metadata={"candidate_name": "Dr. Amina Example"},
        ),
        session=session,
        live=True,
    )

    assert result.action == "queued_for_review"
    assert result.entity_type == "person"
    assert result.entity_id == candidate_id
    assert any("INSERT INTO source" in sql for sql in session.statements)
    assert any("INSERT INTO person_review_queue" in sql for sql in session.statements)
    assert not any("INSERT INTO person " in sql for sql in session.statements)
    assert not any("UPDATE person" in sql for sql in session.statements)
    assert session.transactions[-1].committed
    review_params = next(
        params
        for sql, params in zip(session.statements, session.params)
        if "INSERT INTO person_review_queue" in sql
    )
    assert review_params["source_id"]
    assert review_params["source_url"] == "fixture://people"
    assert review_params["staged_name"] == "Dr. Amina Example"
    assert review_params["candidate_person_id"] == candidate_id
