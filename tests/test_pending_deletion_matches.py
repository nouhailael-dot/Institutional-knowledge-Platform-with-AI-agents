"""A new record matching one waiting in Pending Deletion is still matched, and the
reviewer is told (GHUS, 24 Nov 2026): who deleted it, when, until when, and that it
must be restored before anything updates it. No database: stand-ins only."""

from __future__ import annotations

from datetime import datetime, timezone

from src.datafeed import matching, service
from src.map_agent import save as map_save

GONE = {"deleted_at": "2026-11-23", "purge_after": "2026-12-23", "deleted_by": "Ismail Sabbar"}


class Conn:
    """Answers the matcher's queries: the deletions table exists; one record waits."""

    def __init__(self, pending=True):
        self.pending, self.sql = pending, []

    def execute(self, sql, params=None):
        self.sql.append(sql)
        rows = []
        if "information_schema.columns" in sql:
            rows = [("alt_names",)]
        elif "to_regclass('compass.deleted_record')" in sql:
            rows = [(True,)]
        elif "FROM compass.deleted_record" in sql:
            rows = [("2026-11-23", "2026-12-23", "Ismail Sabbar")] if self.pending else []

        class Result:
            def fetchall(_):
                return rows
        return Result()


def test_a_match_to_a_deleted_record_is_kept_and_flagged():
    m = matching.Matcher(Conn())
    match = {"kind": "existing", "entity_id": "11111111-1111-1111-1111-111111111111", "name": "Tech:NYC"}
    flagged = m.flag("actor", match)
    assert flagged["kind"] == "existing" and flagged["entity_id"] == match["entity_id"]   # still matched
    assert flagged["pending_deletion"] == GONE
    assert "pending_deletion" not in matching.Matcher(Conn(pending=False)).flag("actor", match)
    assert matching.Matcher(Conn()).flag("actor", {"kind": "new"}) == {"kind": "new"}


def test_the_preview_marks_it_and_says_why():
    svc = service.DataFeedService(bridge=None, connect=None)
    svc.bridge = type("B", (), {"configured": True})()
    svc._store = lambda preview: None                                # never touches disk
    match = {"kind": "existing", "entity_id": "x", "name": "Tech:NYC", "pending_deletion": GONE}
    results = [{"row_number": 2, "errors": [], "warnings": [], "missing": [], "match": match,
                "payload": {"name": "Tech:NYC"}, "values": {}},
               {"row_number": 3, "errors": [], "warnings": [], "missing": [], "match": {"kind": "new"},
                "payload": {"name": "New Lab"}, "values": {}}]
    preview = svc._save("actor", "manual", results)
    rows = {r["row_number"]: r for r in preview["rows"]}
    assert rows[2]["status"] == "deleted" and rows[3]["status"] == "new"
    note = " ".join(rows[2]["warnings"])
    assert "Tech:NYC" in note and "Ismail Sabbar deleted on 11/23/2026" in note
    assert "Pending Deletion until 12/23/2026" in note and "restore" in note
    assert preview["counts"]["deleted_matches"] == 1
    assert preview["can_confirm"] is True                            # the new row can still go
    assert service.STATUS_LABELS["deleted"] == "Matches a deleted record"
    only_deleted = svc._save("actor", "manual", [dict(results[0], warnings=[])])
    assert only_deleted["can_confirm"] is False                      # nothing would be stored


def test_explore_and_map_does_not_save_it_and_says_why():
    outcome, reason = map_save._check_outcome(
        {"status": "deleted", "errors": [], "match": {"name": "Tech:NYC", "pending_deletion": GONE}})
    assert outcome == map_save.NOT_SAVED
    assert "Tech:NYC" in reason and "Pending Deletion" in reason and "restore" in reason


def test_review_shows_a_deleted_possible_duplicate(monkeypatch):
    import backend.app as app_module
    from backend import accounts_routes

    class Store:
        def deletions(self):
            return [{"entity_type": "actor", "entity_id": "aaa", "deleted_by": "Ismail Sabbar",
                     "deleted_at": datetime(2026, 11, 23, tzinfo=timezone.utc),
                     "purge_after": datetime(2026, 12, 23, tzinfo=timezone.utc)}]

    monkeypatch.setattr(app_module, "_accounts_on", lambda: True)
    monkeypatch.setattr(accounts_routes, "accounts_store", lambda: Store())
    item = {"entity_type": "actor", "top_matches": [{"entity_id": "aaa", "name": "Tech:NYC"},
                                                    {"entity_id": "bbb", "name": "Other"}]}
    flagged = app_module._flag_deleted_matches(item)
    assert flagged["top_matches"][0]["pending_deletion"] == GONE
    assert "pending_deletion" not in flagged["top_matches"][1]
    # Without accounts nothing is added; a failure to read deletions never breaks the page.
    monkeypatch.setattr(app_module, "_accounts_on", lambda: False)
    assert "pending_deletion" not in app_module._flag_deleted_matches(
        {"entity_type": "actor", "top_matches": [{"entity_id": "bbb"}]})["top_matches"][0]
