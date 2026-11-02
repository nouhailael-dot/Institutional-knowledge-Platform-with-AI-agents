"""Dashboard reads (GHUS Dashboard Design, 2026-11-02): read only, nothing invented."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from types import SimpleNamespace

from src import dashboard
from src.map_agent.run_store import MICRO, RunStore
from src.review.store import ReviewStore


class FakeCursor:
    def __init__(self, rows, cols):
        self.rows, self.description, self.executed = rows, [SimpleNamespace(name=c) for c in cols], []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_directory_activity_needs_a_name_and_only_reads(monkeypatch):
    calls = []
    monkeypatch.setattr(dashboard, "_readonly", lambda: calls.append(1))
    assert dashboard.directory_activity("   ") == []
    assert calls == []

    when = datetime(2026, 11, 1, 9, tzinfo=timezone.utc)
    cursor = FakeCursor([("actor", "a1", "verified", when, "BioSTL")],
                        ["entity_type", "entity_id", "action", "decided_at", "name"])
    monkeypatch.setattr(dashboard, "_readonly", lambda: FakeConn(cursor))
    rows = dashboard.directory_activity(" Ismail Sabbar ", days=7)
    assert rows == [{"entity_type": "actor", "entity_id": "a1", "action": "verified",
                     "decided_at": when.isoformat(), "name": "BioSTL"}]
    sql, params = cursor.executed[0]
    assert params == {"me": "Ismail Sabbar", "days": 7, "limit": 5}
    assert sql.lstrip().upper().startswith("WITH")
    for word in ("INSERT", "UPDATE ", "DELETE"):
        assert word not in sql.upper()
    # A record whose name cannot be read is left out, never given a made-up one.
    assert "IS NOT NULL" in sql


def test_spending_by_month_keeps_every_month(monkeypatch):
    cursor = FakeCursor([("2026-11", "ismail", 2, 1.5), ("2026-11", "not recorded", 1, 0.25),
                         ("2026-10", "not recorded", 46, 12.2795)], ["month", "who", "runs", "spent"])
    monkeypatch.setattr(dashboard, "_readonly", lambda: FakeConn(cursor))
    months = dashboard.spending_by_month()
    assert [m["month"] for m in months] == ["2026-11", "2026-10"]
    assert months[0]["spent_usd"] == 1.75 and months[0]["runs"] == 3
    assert months[1]["by"] == [{"initiated_by": "not recorded", "runs": 46, "spent_usd": 12.2795}]


def test_recent_maps_carry_type_and_spend(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite3")
    run_id = store.create()
    with store.connect() as db:
        db.execute("UPDATE runs SET plan=? WHERE id=?", (json.dumps({"map_type": "people"}), run_id))
        db.execute("INSERT INTO calls(id,run_id,stage,model,status,reserved,cost,pricing,started) "
                   "VALUES('c1',?,'plan','m','done',0,?,'{}',?)", (run_id, int(0.42 * MICRO), time.time()))
    [row] = store.recent()
    assert row["map_type"] == "people"
    assert abs(row["spent_usd"] - 0.42) < 1e-9


def test_pending_by_run_counts_listed_undecided_records(tmp_path):
    store = ReviewStore(tmp_path / "review.sqlite3")
    assert store.pending_by_run([]) == {}
    now = time.time()
    with store.connect() as db:
        for cid, run, status, folded in (("c1", "m1", "pending_review", None), ("c2", "m1", "pending_review", None),
                                         ("c3", "m1", "approved", None), ("c4", "m1", "pending_review", "set_aside:x"),
                                         ("c5", "m2", "pending_review", None)):
            db.execute("INSERT INTO review_candidate(candidate_id,source_run_id,source_index,entity_type,"
                       "display_name,original_payload,reviewed_payload,evidence,agent_metadata,duplicate_state,"
                       "status,created_at,folded_into) VALUES(?,?,?,'actor','N','{}','{}','[]','{}','none',?,?,?)",
                       (cid, run, cid, status, now, folded))
    assert store.pending_by_run(["m1", "m3"]) == {"m1": 2}
