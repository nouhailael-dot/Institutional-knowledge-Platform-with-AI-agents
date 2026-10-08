"""WS4: run labels, the pre-redesign backlog grouping, and the write guards.

Two properties matter more than anything else here:

  * Grouping is a VIEW. Stored ``source_run_id`` values and provenance are
    identical before and after, and the original run stays visible under Audit
    & Details. The tests assert the stored rows byte for byte.
  * Grouping is deterministic around the cutoff, including exactly ON it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.review.store import (  # noqa: E402
    BACKLOG_GROUP_KEY,
    BACKLOG_GROUP_LABEL,
    NOT_RECORDED,
    ReviewStore,
    ReviewValidationError,
    review_redesign_cutoff,
)

CUTOFF = "2026-10-08T00:00:00Z"
CUTOFF_TS = 1791417600.0  # 2026-10-08T00:00:00Z


@pytest.fixture(autouse=True)
def _pinned_cutoff(monkeypatch):
    monkeypatch.setenv("REVIEW_REDESIGN_CUTOFF", CUTOFF)


@pytest.fixture
def store(tmp_path):
    return ReviewStore(tmp_path / "review.sqlite3")


def _insert(store: ReviewStore, candidate_id: str, *, created_at: float,
            source_run_id: str, description: str, status: str = "pending_review",
            payload: dict | None = None) -> None:
    body = {"name": f"Actor {candidate_id}", **(payload or {})}
    with store.connect() as db:
        db.execute(
            "INSERT INTO review_candidate"
            "(candidate_id,source_run_id,source_description,source_index,entity_type,"
            " display_name,status,created_at,original_payload,reviewed_payload,evidence,"
            " agent_metadata,duplicate_state)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (candidate_id, source_run_id, description, candidate_id, "actor",
             body["name"], status, created_at, "{}", __import__("json").dumps(body),
             "[]", "{}", "new"),
        )


def test_the_cutoff_is_configurable_and_rejects_nonsense(monkeypatch):
    assert review_redesign_cutoff() == pytest.approx(CUTOFF_TS)
    monkeypatch.setenv("REVIEW_REDESIGN_CUTOFF", "2026-01-01")
    assert review_redesign_cutoff() < CUTOFF_TS
    # An unparseable value falls back to the documented default rather than
    # silently grouping everything into the backlog.
    monkeypatch.setenv("REVIEW_REDESIGN_CUTOFF", "not-a-date")
    assert review_redesign_cutoff() == pytest.approx(CUTOFF_TS)


def test_grouping_is_deterministic_around_the_cutoff(store):
    _insert(store, "before", created_at=CUTOFF_TS - 1,
            source_run_id="run-old", description="Open-web actor discovery")
    _insert(store, "exactly-on", created_at=CUTOFF_TS,
            source_run_id="run-edge", description="Open-web actor discovery")
    _insert(store, "after", created_at=CUTOFF_TS + 1,
            source_run_id="run-new", description="Open-web actor discovery · monthly")

    listing = store.list(status="all")
    by_id = {item["candidate_id"]: item for item in listing["candidates"]}
    # Strictly before the cutoff is backlog; the cutoff instant itself is not.
    assert by_id["before"]["run_group_key"] == BACKLOG_GROUP_KEY
    assert by_id["exactly-on"]["run_group_key"] == "run-edge"
    assert by_id["after"]["run_group_key"] == "run-new"
    # Same input, same output.
    assert store.list(status="all")["run_groups"] == listing["run_groups"]


def test_the_backlog_group_comes_first_and_then_the_newest_run(store):
    _insert(store, "old-1", created_at=CUTOFF_TS - 500, source_run_id="run-a",
            description="Open-web actor discovery")
    _insert(store, "old-2", created_at=CUTOFF_TS - 400, source_run_id="run-b",
            description="Architecture V2 verify_actor review")
    _insert(store, "new-1", created_at=CUTOFF_TS + 100, source_run_id="run-c",
            description="Open-web actor discovery · manual")
    _insert(store, "new-2", created_at=CUTOFF_TS + 900, source_run_id="run-d",
            description="Actor update subscription · monthly")

    groups = store.list(status="all")["run_groups"]
    assert [group["key"] for group in groups] == [BACKLOG_GROUP_KEY, "run-d", "run-c"]
    backlog = groups[0]
    assert backlog["label"] == BACKLOG_GROUP_LABEL
    assert backlog["is_backlog"] is True
    assert backlog["candidate_count"] == 2
    # The backlog spans several real runs, and names every one of them.
    assert backlog["source_run_ids"] == ["run-a", "run-b"]
    # No authenticated identity exists yet, so it is reported as unrecorded and
    # never invented.
    assert backlog["initiated_by"] == NOT_RECORDED
    assert all(group["initiated_by"] == NOT_RECORDED for group in groups)


def test_the_trigger_is_read_from_the_source_and_never_guessed(store):
    _insert(store, "sub", created_at=CUTOFF_TS + 10, source_run_id="run-sub",
            description="Actor update subscription · monthly")
    _insert(store, "mig", created_at=CUTOFF_TS + 20, source_run_id="existing_canonical_migration",
            description="Existing canonical migration")
    _insert(store, "sched", created_at=CUTOFF_TS + 30, source_run_id="run-weekly",
            description="Weekly scheduled discovery")
    _insert(store, "plain", created_at=CUTOFF_TS + 40, source_run_id="run-plain",
            description="Open-web actor discovery")

    by_id = {item["candidate_id"]: item for item in store.list(status="all")["candidates"]}
    assert by_id["sub"]["run_trigger"] == "subscription"
    assert by_id["mig"]["run_trigger"] == "migration"
    assert by_id["sched"]["run_trigger"] == "scheduled_event"
    # Unrecognised stays manual rather than becoming a guess.
    assert by_id["plain"]["run_trigger"] == "manual"


def test_run_labels_hide_uuids_and_stored_provenance_is_untouched(store):
    run_id = "discovery:577bd0bd-263a-43a7-90f8-373f7cab65ae"
    description = "Open-web actor discovery · dry_run · 577bd0bd-263a-43a7-90f8-373f7cab65ae"
    _insert(store, "uuid", created_at=CUTOFF_TS + 5, source_run_id=run_id,
            description=description)

    item = store.list(status="all")["candidates"][0]
    assert item["run_label"] == "Open-web actor discovery · dry_run"
    # The label is a projection. The stored values are identical.
    assert item["source_run_id"] == run_id
    assert item["source_description"] == description
    with store.connect() as db:
        row = db.execute(
            "SELECT source_run_id, source_description FROM review_candidate"
        ).fetchone()
    assert row["source_run_id"] == run_id
    assert row["source_description"] == description


def test_filtering_by_group_never_rewrites_what_is_stored(store):
    _insert(store, "old", created_at=CUTOFF_TS - 10, source_run_id="run-a",
            description="Open-web actor discovery")
    _insert(store, "new", created_at=CUTOFF_TS + 10, source_run_id="run-b",
            description="Open-web actor discovery")
    with store.connect() as db:
        before = [dict(row) for row in db.execute(
            "SELECT * FROM review_candidate ORDER BY candidate_id")]

    assert [item["candidate_id"] for item in
            store.list(status="all", run_group=BACKLOG_GROUP_KEY)["candidates"]] == ["old"]
    assert [item["candidate_id"] for item in
            store.list(status="all", run_group="run-b")["candidates"]] == ["new"]
    # A run id that belongs to the backlog is not reachable as its own group,
    # because the backlog is the group it was put in.
    assert store.list(status="all", run_group="run-a")["candidates"] == []

    with store.connect() as db:
        after = [dict(row) for row in db.execute(
            "SELECT * FROM review_candidate ORDER BY candidate_id")]
    assert after == before


def test_the_queue_filters_by_category_reason_and_region(store):
    _insert(store, "lab", created_at=CUTOFF_TS + 1, source_run_id="run-a",
            description="Open-web actor discovery",
            payload={"actor_category": "research_center", "state": "MA", "country": "United States"})
    _insert(store, "startup", created_at=CUTOFF_TS + 2, source_run_id="run-a",
            description="Open-web actor discovery",
            payload={"actor_category": "startup", "state": "CA"})

    assert [item["candidate_id"] for item in
            store.list(status="all", actor_category="startup")["candidates"]] == ["startup"]
    assert [item["candidate_id"] for item in
            store.list(status="all", region="Northeast")["candidates"]] == ["lab"]
    assert [item["candidate_id"] for item in
            store.list(status="all", region="West Coast / Pacific")["candidates"]] == ["startup"]
    with pytest.raises(ReviewValidationError, match="Unsupported actor category"):
        store.list(status="all", actor_category="aggregate")


# ------------------------------------------------- WS1 and WS2 write guards

def test_an_invalid_category_pair_cannot_be_saved(store):
    _insert(store, "a", created_at=CUTOFF_TS + 1, source_run_id="run-a",
            description="Open-web actor discovery",
            payload={"actor_category": "company", "category_type": "small_mid_size"})
    with pytest.raises(ReviewValidationError, match="belongs to"):
        store.update("a", {"category_type": "medical_school"})
    # The refused edit changed nothing.
    assert store.get("a")["reviewed_payload"]["category_type"] == "small_mid_size"


def test_the_retired_catch_all_cannot_be_saved(store):
    _insert(store, "a", created_at=CUTOFF_TS + 1, source_run_id="run-a",
            description="Open-web actor discovery",
            payload={"actor_category": "company"})
    with pytest.raises(ReviewValidationError, match="retired"):
        store.update("a", {"category_type": "other"})


def test_not_applicable_requires_a_note(store):
    _insert(store, "a", created_at=CUTOFF_TS + 1, source_run_id="run-a",
            description="Open-web actor discovery",
            payload={"actor_category": "company"})
    with pytest.raises(ReviewValidationError, match="deliberate choice"):
        store.update("a", {"category_type": "not_applicable"})
    saved = store.update("a", {
        "category_type": "not_applicable",
        "category_note": "No listed company type fits the self-description.",
    })
    assert saved["reviewed_payload"]["category_type"] == "not_applicable"


def test_a_legacy_null_type_survives_an_unrelated_edit(store):
    """Decision D4: a legacy NULL stays NULL. It is never promoted to N/A."""

    _insert(store, "a", created_at=CUTOFF_TS - 1, source_run_id="run-a",
            description="Open-web actor discovery",
            payload={"actor_category": "company"})
    saved = store.update("a", {"name": "Renamed Legacy Actor"})
    assert saved["reviewed_payload"]["category_type"] is None
    assert saved["reviewed_payload"]["name"] == "Renamed Legacy Actor"


def test_the_region_is_recomputed_from_the_state_and_never_taken_from_input(store):
    _insert(store, "a", created_at=CUTOFF_TS + 1, source_run_id="run-a",
            description="Open-web actor discovery",
            payload={"actor_category": "company", "state": "MA"})
    # A client that sends a wrong region does not get to keep it.
    saved = store.update("a", {"state": "DC", "region": "Pacific Northwest"})
    assert saved["reviewed_payload"]["region"] == "Mid-Atlantic"
    saved = store.update("a", {"state": "WA"})
    assert saved["reviewed_payload"]["region"] == "West Coast / Pacific"
    saved = store.update("a", {"state": "", "country": "Morocco"})
    assert saved["reviewed_payload"]["region"] == "Not Applicable (Non-US)"


# ----------------------------------------------------------------- the API

def _api_client(tmp_path):
    from unittest.mock import MagicMock, patch

    from fastapi.testclient import TestClient

    from backend import app as backend
    from src.map_agent.run_store import RunStore

    store = ReviewStore(tmp_path / "review.sqlite3", enable_test_canonical=True)
    runs = RunStore(tmp_path / "runs.sqlite3")
    bridge = MagicMock()
    bridge.configured = True
    patches = [
        patch.object(backend, "map_store", return_value=runs),
        patch.object(backend, "review_store", return_value=store),
        patch.object(backend, "review_postgres_source", return_value=None),
        patch.object(backend, "review_source_store", return_value=None),
        patch.object(backend, "review_admission_bridge", return_value=bridge),
    ]
    for item in patches:
        item.start()
    backend._review_sync_last = 0.0
    backend._review_sync_store_key = None
    return TestClient(backend.app), store, patches


def test_the_api_serves_one_controlled_catalog(tmp_path):
    client, _store, patches = _api_client(tmp_path)
    try:
        body = client.get("/api/review/catalog").json()
        assert len(body["categories"]) == 12
        assert sum(len(row["types"]) for row in body["categories"]) == 69
        assert body["not_applicable"] == "not_applicable"
        assert body["retired_catch_all"] == "other"
        assert len(body["states"]) == 51
        assert len(body["link_types"]) == 11
        parents = [row["code"] for row in body["link_types"] if row["is_parent"]]
        assert parents == ["unit_of", "operated_by"]
    finally:
        for item in patches:
            item.stop()


def test_the_api_refuses_an_invalid_pair_with_a_clear_422(tmp_path):
    client, store, patches = _api_client(tmp_path)
    try:
        _insert(store, "a", created_at=CUTOFF_TS + 1, source_run_id="run-a",
                description="Open-web actor discovery",
                payload={"actor_category": "company", "category_type": "small_mid_size"})
        response = client.patch(
            "/api/review/candidates/a",
            json={"fields": {"category_type": "medical_school"}},
        )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "medical_school" in detail and "company" in detail
        # The refused edit changed nothing.
        assert store.get("a")["reviewed_payload"]["category_type"] == "small_mid_size"
    finally:
        for item in patches:
            item.stop()


def test_the_queue_endpoint_exposes_the_run_groups(tmp_path):
    client, store, patches = _api_client(tmp_path)
    try:
        _insert(store, "old", created_at=CUTOFF_TS - 10, source_run_id="run-a",
                description="Open-web actor discovery")
        _insert(store, "new", created_at=CUTOFF_TS + 10, source_run_id="run-b",
                description="Actor update subscription · monthly")
        body = client.get("/api/review/candidates?status=all").json()
        assert [group["key"] for group in body["run_groups"]] == [BACKLOG_GROUP_KEY, "run-b"]
        assert body["run_groups"][1]["trigger_label"] == "Subscription"
        assert body["review_redesign_cutoff"] == CUTOFF_TS
        filtered = client.get(
            f"/api/review/candidates?status=all&run_group={BACKLOG_GROUP_KEY}").json()
        assert [row["candidate_id"] for row in filtered["candidates"]] == ["old"]
    finally:
        for item in patches:
            item.stop()


def test_a_recorded_trigger_beats_the_derived_one(store):
    """collection_run.trigger_type is authoritative once the backend records it."""

    with store.connect() as db:
        db.execute(
            "INSERT INTO review_candidate"
            "(candidate_id,source_run_id,source_description,source_index,entity_type,"
            " display_name,status,created_at,original_payload,reviewed_payload,evidence,"
            " agent_metadata,duplicate_state)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("recorded", "run-x", "Open-web actor discovery", "1", "actor",
             "Actor recorded", "pending_review", CUTOFF_TS + 1, "{}",
             '{"name": "Actor recorded"}', "[]",
             '{"trigger_type": "subscription", "cadence": "monthly",'
             ' "initiated_by": "A GHUS Reviewer"}', "new"),
        )
    item = store.list(status="all")["candidates"][0]
    # The description says nothing about a subscription; the recorded value wins.
    assert item["run_trigger"] == "subscription"
    assert item["run_cadence"] == "monthly"
    assert item["run_initiated_by"] == "A GHUS Reviewer"


def test_an_unrecognised_recorded_trigger_falls_back_rather_than_being_trusted(store):
    _insert(store, "odd", created_at=CUTOFF_TS + 1, source_run_id="run-y",
            description="Actor update subscription · monthly")
    with store.connect() as db:
        db.execute(
            "UPDATE review_candidate SET agent_metadata=? WHERE candidate_id='odd'",
            ('{"trigger_type": "something_invented"}',),
        )
    item = store.list(status="all")["candidates"][0]
    # A value outside the controlled set is not passed through to the UI.
    assert item["run_trigger"] == "subscription"
    # And an absent initiator still reads as unrecorded, never defaulted.
    assert item["run_initiated_by"] == NOT_RECORDED
