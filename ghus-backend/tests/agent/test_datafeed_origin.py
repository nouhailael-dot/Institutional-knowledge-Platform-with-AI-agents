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
