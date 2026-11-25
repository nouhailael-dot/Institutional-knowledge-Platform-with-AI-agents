"""promote labels a Data Feed record with its origin, and keeps an event's own dates."""

from __future__ import annotations

from datetime import date

from agents.discovery import promote


def test_origin_is_the_pipeline_unless_the_data_feed_set_a_known_one():
    assert promote._record_origin({}) == "claude_discovered"
    assert promote._record_origin(None) == "claude_discovered"
    assert promote._record_origin({"_record_origin": "ghus_uploaded_doc"}) == "ghus_uploaded_doc"
    assert promote._record_origin({"_record_origin": "ghus_manual"}) == "ghus_manual"
    # Never a value that would claim GHUS verified or imported the record.
    for unknown in ("imported_phase1", "verified", "ghus_review", " "):
        assert promote._record_origin({"_record_origin": unknown}) == "claude_discovered"


def test_iso_day():
    assert promote._iso_day("2027-04-02") == "2027-04-02"
    assert promote._iso_day("2027-04-02T09:00:00Z") == "2027-04-02"
    assert promote._iso_day(date(2027, 4, 2)) == "2027-04-02"
    assert promote._iso_day("04/02/2027") is None
    assert promote._iso_day(None) is None


class _Session:
    """Records the event INSERT."""

    def __init__(self):
        self.params = None

    def execute(self, statement, params=None):
        if str(statement).startswith("INSERT INTO event"):
            self.params = params


def test_event_insert_keeps_both_dates_and_the_origin(monkeypatch):
    monkeypatch.setattr(promote, "_table_columns", lambda session, table: {
        "event_id", "name", "source_id", "next_date", "start_date", "end_date",
        "record_status", "source_origin", "date_status", "event_type", "website"})
    session = _Session()
    promote._insert_event(session, {
        "name": "Great Plains Water Summit", "next_date": "2027-04-02",
        "start_date": "2027-04-02", "end_date": "2027-04-03",
        "_record_origin": "ghus_uploaded_doc"}, "00000000-0000-0000-0000-000000000002")
    assert session.params["start_date"] == "2027-04-02"
    assert session.params["end_date"] == "2027-04-03"
    assert session.params["source_origin"] == "ghus_uploaded_doc"
    assert session.params["record_status"] == "parked"


class _PlaceSession:
    """Records the event INSERT, answers the region lookup and the event_sector insert."""

    def __init__(self, existing=None):
        self.params, self.sector_params, self.updates, self.existing = None, None, None, existing or {}

    def execute(self, statement, params=None):
        sql = str(statement)
        session = self

        class _Result:
            def scalar(self):
                return {"OR": "west_coast_pacific", "NY": "northeast"}.get((params or {}).get("state"))

            def all(self):
                return [("s1",)] if sql.startswith("INSERT INTO event_sector") else []

            def mappings(self):
                return self

            def first(self):
                return session.existing

        if sql.startswith("INSERT INTO event_sector"):
            self.sector_params = params
        elif sql.startswith("INSERT INTO event "):
            self.params = params
        elif sql.startswith("UPDATE event SET"):
            self.updates = params
        return _Result()


_PLACE_COLUMNS = {
    "event_id", "name", "source_id", "next_date", "start_date", "end_date", "record_status",
    "source_origin", "date_status", "location", "venue", "city", "state_code", "country",
    "region_code", "event_format", "registration_url", "organizer"}


def test_a_new_event_keeps_its_place_format_and_organizer(monkeypatch):
    # 25 Nov 2026: the 740 columns were left empty and the venue was lost.
    monkeypatch.setattr(promote, "_table_columns", lambda session, table: _PLACE_COLUMNS)
    session = _PlaceSession()
    promote._insert_event(session, {
        "name": "CANVAS 2026", "venue": "Oregon Convention Center", "city": "Portland",
        "state": "OR", "country": "USA", "event_format": "in_person",
        "organizer": "American Society of Agronomy", "location": "Oregon Convention Center, Portland, OR"},
        "00000000-0000-0000-0000-000000000002")
    p = session.params
    assert (p["venue"], p["city"], p["state_code"], p["country"]) == (
        "Oregon Convention Center", "Portland", "OR", "USA")
    assert p["region_code"] == "west_coast_pacific"
    assert p["event_format"] == "In person"
    assert p["organizer"] == "American Society of Agronomy"


def test_place_columns_are_skipped_where_the_database_lacks_them(monkeypatch):
    monkeypatch.setattr(promote, "_table_columns", lambda session, table: {
        "event_id", "name", "source_id", "location"})
    session = _PlaceSession()
    promote._insert_event(session, {"name": "X", "city": "Portland", "state": "OR",
                                    "event_format": "online"}, "00000000-0000-0000-0000-000000000002")
    assert not {"city", "state_code", "region_code", "event_format"} & set(session.params)


def test_an_unknown_format_is_left_out_never_guessed(monkeypatch):
    monkeypatch.setattr(promote, "_table_columns", lambda session, table: _PLACE_COLUMNS)
    session = _PlaceSession()
    promote._insert_event(session, {"name": "X", "event_format": "sometimes"},
                          "00000000-0000-0000-0000-000000000002")
    assert "event_format" not in session.params


def test_an_event_is_linked_to_its_sectors(monkeypatch):
    monkeypatch.setattr(promote, "_table_columns", lambda session, table: {"event_id", "sector_id"})
    session = _PlaceSession()
    staged = promote.StagedRecord(
        run_id="r", entity_type="event", natural_key="x", source_url="", payload={},
        normalized_payload={}, prompt_version="p", extracted_at="2026-11-25",
        staged_record_id="s", sector_codes=("agri", "AGRI", "water"))
    assert promote._append_event_sectors(session, event_id="e", staged=staged, source_id="src") == 1
    assert session.sector_params["codes"] == ["AGRI", "WATER"]


def test_updating_an_event_fills_only_its_empty_place_columns(monkeypatch):
    monkeypatch.setattr(promote, "_table_columns", lambda session, table: _PLACE_COLUMNS)
    monkeypatch.setattr(promote, "insert_source", lambda session, **kw: "src")
    # The event already has a city a person typed; its venue is empty.
    session = _PlaceSession(existing={"city": "Portland (typed by GHUS)", "venue": None,
                                      "event_type": "Conference", "source_id": "old"})
    staged = promote.StagedRecord(
        run_id="r", entity_type="event", natural_key="x", source_url="", payload={},
        normalized_payload={"venue": "Oregon Convention Center", "city": "Portland"},
        prompt_version="p", extracted_at="2026-11-25", staged_record_id="s")
    fields = promote._absorb_event_fields(session, "00000000-0000-0000-0000-000000000003", staged)
    assert "venue" in fields and "city" not in fields
    assert session.updates["venue"] == "Oregon Convention Center"
