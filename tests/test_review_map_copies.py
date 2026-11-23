"""Review takes a map's cards only through "Save verified to Compass" (12 Nov 2026).

GHUS feedback of 11 Nov: events found by Explore and Map showed in Review but
could not be verified, saved or rejected ("This candidate has no authoritative
PostgreSQL source reference"), and edits were lost. Those rows were copies made
straight from the map, with no database record behind them.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from src.map_agent import save as map_save
from src.map_agent.run_store import RunStore
from src.review.store import ReviewStore

FIXTURE = Path(__file__).parent / "fixtures" / "review_map_result.json"


def _map(runs: RunStore, name="Find me all African Diaspora events") -> str:
    run_id = runs.create(name)
    runs.update(run_id, status="done", stage="Complete",
                result=json.loads(FIXTURE.read_text(encoding="utf-8")))
    return run_id


def _listed(store: ReviewStore) -> list[dict]:
    return store.list(status="pending_review")["candidates"]


def test_pending_map_copies_leave_review_and_decided_ones_stay(tmp_path):
    runs = RunStore(tmp_path / "runs.sqlite3")
    run_id = _map(runs)
    store = ReviewStore(tmp_path / "review.sqlite3", enable_test_canonical=True)
    store.sync_run_store(runs)  # what the old sync did
    copies = _listed(store)
    assert copies
    decided = copies[0]["candidate_id"]
    store.reject(decided, reviewer="R", rejection_reason="Not relevant",
                 idempotency_key="k1", confirmed=True)

    assert store.retire_map_copies(runs) == len(copies) - 1
    assert [c for c in _listed(store) if c["source_run_id"] == run_id] == []
    assert store.get(decided)["status"] == "rejected_by_reviewer"
    assert store.retire_map_copies(runs) == 0  # nothing more to fold


def test_the_hosted_review_sync_lists_no_map_copies(tmp_path):
    from backend import app as backend

    runs = RunStore(tmp_path / "runs.sqlite3")
    _map(runs)
    store = ReviewStore(tmp_path / "review.sqlite3")  # not the test/demo mode
    patches = [patch.object(backend, "map_store", return_value=runs),
               patch.object(backend, "review_store", return_value=store),
               patch.object(backend, "review_postgres_source", return_value=None),
               patch.object(backend, "review_source_store", return_value=None),
               patch.object(backend, "review_admission_bridge", return_value=MagicMock(configured=True))]
    for item in patches:
        item.start()
    try:
        backend._review_sync_last = 0.0
        backend._review_sync_store_key = None
        body = TestClient(backend.app).get("/api/review/candidates").json()
        assert body["candidates"] == []
    finally:
        for item in patches:
            item.stop()


def test_a_maps_saved_cards_count_as_its_pending_review(tmp_path):
    store = ReviewStore(tmp_path / "review.sqlite3")
    name = map_save.import_name("Find me all African Diaspora events")
    with store.connect() as db:
        for index, status in enumerate(("pending_review", "pending_review", "approved")):
            db.execute(
                "INSERT INTO review_candidate (candidate_id,source_run_id,source_index,"
                "source_description,entity_type,display_name,original_payload,reviewed_payload,"
                "evidence,agent_metadata,duplicate_state,status,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"c{index}", "datafeed:1", str(index), f"Data Feed import: {name} · file",
                 "event", f"Event {index}", "{}", "{}", "[]", "{}", "new", status, 1.0))
    prefix = "Data Feed import: " + name
    assert store.pending_by_description({"map-1": prefix, "map-2": "Data Feed import: other"}) \
        == {"map-1": 2}


def test_review_never_lists_a_maps_saved_records(tmp_path):
    """GHUS, 12 Nov 2026: a map is reviewed on its own page; Review Results is for
    new requests and organization updates only."""
    store = ReviewStore(tmp_path / "review.sqlite3")
    name = map_save.import_name("Find me all African Diaspora events")
    with store.connect() as db:
        for cid, description in (("map", f"Data Feed import: {name} · manual entry"),
                                 ("sheet", "Data Feed import: Phase 1 sheet · file.xlsx"),
                                 ("request", "Monitoring request: Water reuse in Texas")):
            db.execute(
                "INSERT INTO review_candidate (candidate_id,source_run_id,source_index,"
                "source_description,entity_type,display_name,original_payload,reviewed_payload,"
                "evidence,agent_metadata,duplicate_state,status,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, f"run-{cid}", "1", description, "event", cid, "{}", "{}", "[]", "{}",
                 "new", "pending_review", 1.0))
    assert store.retire_map_copies() == 1
    assert {c["candidate_id"] for c in _listed(store)} == {"sheet", "request"}


def test_the_dashboard_counts_cards_still_undecided_on_the_map(tmp_path):
    runs = RunStore(tmp_path / "runs.sqlite3")
    run_id = _map(runs)
    result = runs.get(run_id)["result"]
    cards = [c for group in result["entities"].values() for c in group]
    cards[0]["_review"] = "ready"
    runs.update(run_id, result=result)
    assert runs.undecided([run_id]) == {run_id: len(cards) - 1}
