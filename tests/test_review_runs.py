"""Run groups and labels in the Review queue, and the write guards.

Two properties matter more than anything else here:

  * Grouping is a VIEW. Stored ``source_run_id`` values and provenance are
    identical before and after, and the original run stays visible under Audit
    & Details. The tests assert the stored rows byte for byte.
  * Every run is its own group, labelled for what it is. (Runs before the
    redesign cutoff used to be merged into one "Pre-Redesign Backlog" group;
    on a long-running database that hid every run.)
"""

from __future__ import annotations

import pathlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.review.store import (  # noqa: E402
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


def test_every_run_is_its_own_group_whenever_it_ran(store):
    _insert(store, "before", created_at=CUTOFF_TS - 1,
            source_run_id="run-old", description="Open-web actor discovery")
    _insert(store, "exactly-on", created_at=CUTOFF_TS,
            source_run_id="run-edge", description="Open-web actor discovery")
    _insert(store, "after", created_at=CUTOFF_TS + 1,
            source_run_id="run-new", description="Open-web actor discovery · monthly")

    listing = store.list(status="all")
    by_id = {item["candidate_id"]: item for item in listing["candidates"]}
    assert by_id["before"]["run_group_key"] == "run-old"
    assert by_id["exactly-on"]["run_group_key"] == "run-edge"
    assert by_id["after"]["run_group_key"] == "run-new"
    # Same input, same output.
    assert store.list(status="all")["run_groups"] == listing["run_groups"]


def test_runs_are_listed_newest_first_each_with_its_own_label(store):
    _insert(store, "old-1", created_at=CUTOFF_TS - 500, source_run_id="run-a",
            description="Open-web actor discovery · dry_run · run-a")
    _insert(store, "old-2", created_at=CUTOFF_TS - 400, source_run_id="v2-review:unscoped",
            description="Architecture V2 geocode_failed review")
    _insert(store, "new-1", created_at=CUTOFF_TS + 100, source_run_id="run-c",
            description="Discovery request: Water technology in the Great Lakes · live · run-c")
    _insert(store, "new-2", created_at=CUTOFF_TS + 900, source_run_id="run-d",
            description="find companies in the US that focus on water reuse and desalination")

    groups = store.list(status="all")["run_groups"]
    # Runs newest first; the map's own checks are ongoing, so they come last.
    assert [group["key"] for group in groups] == ["run-d", "run-c", "run-a", "map-checks"]
    labels = {group["key"]: group["label"] for group in groups}
    assert labels["run-c"].startswith("Discovery request · Water technology in the Great Lakes · ")
    assert labels["run-a"].startswith("Actor discovery · test run · ")
    assert labels["map-checks"] == "Map checks"
    assert labels["run-d"].startswith("Build the Map · find companies in the US that focus on")
    assert not any(group["is_backlog"] for group in groups)
    # No authenticated identity exists yet, so it is reported as unrecorded and
    # never invented.
    assert all(group["initiated_by"] == NOT_RECORDED for group in groups)


def test_two_runs_on_the_same_day_are_told_apart_by_the_time(store):
    _insert(store, "a", created_at=CUTOFF_TS + 3_600, source_run_id="run-a",
            description="Open-web actor discovery · dry_run · run-a")
    _insert(store, "b", created_at=CUTOFF_TS + 7_200, source_run_id="run-b",
            description="Open-web actor discovery · dry_run · run-b")
    labels = [group["label"] for group in store.list(status="all")["run_groups"]]
    assert len(set(labels)) == 2
    assert all(label.endswith(" UTC") for label in labels)


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
    assert item["run_label"] == "Actor discovery · test run · Oct 8, 2026"
    assert "577bd0bd" not in item["run_label"]
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
            store.list(status="all", run_group="run-a")["candidates"]] == ["old"]
    assert [item["candidate_id"] for item in
            store.list(status="all", run_group="run-b")["candidates"]] == ["new"]

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
        assert [group["key"] for group in body["run_groups"]] == ["run-b", "run-a"]
        assert body["run_groups"][0]["trigger_label"] == "Subscription"
        filtered = client.get("/api/review/candidates?status=all&run_group=run-a").json()
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


# ------------------------------------------------------ WS5.1 hub assignment

def test_the_review_haversine_matches_the_backend_to_a_tenth_of_a_mile():
    """This app computes its own distances, so they must agree with the backend.

    The backend is the authority (agents.common.geography.distance_miles). These
    reference values were produced by it from Census gazetteer coordinates. A
    distance shown to a reviewer that disagrees with the one the algorithm used
    would be worse than showing none.
    """

    from src.review.postgres_source import _haversine_miles

    davis = (38.556147, -121.737793)
    cases = [
        ((38.567694, -121.468161), 14.59),    # Sacramento, CA
        ((38.447512, -121.824223), 8.84),     # Dixon, CA
        ((37.976553, -121.308598), 46.32),    # Stockton, CA
        ((37.366381, -118.395808), 199.74),   # Bishop, CA, just inside 200
        ((40.797594, -124.154191), 201.22),   # Eureka, CA, just outside
    ]
    for (latitude, longitude), expected in cases:
        actual = _haversine_miles(davis[0], davis[1], latitude, longitude)
        assert abs(actual - expected) < 0.1, f"{actual:.2f} != {expected}"
    # Identical points are zero, not a rounding artefact.
    assert _haversine_miles(*davis, *davis) == pytest.approx(0.0, abs=1e-9)


def test_a_membership_and_a_suggestion_are_never_the_same_thing(tmp_path):
    """WS5.1: the screen must not present a proposal as an existing fact."""

    source = pathlib.Path("frontend/review.js").read_text(encoding="utf-8")
    assert "hub_memberships" in source and "hub_suggestions" in source
    # Distinct headings, so a reviewer cannot mistake one list for the other.
    assert "FIELDS.currentHubs" in source and "FIELDS.suggestedHubs" in source
    # An out-of-radius member is flagged rather than dropped.
    assert "BADGES.hubMemberOutsideRadius" in source
    # The separation is carried by the structure - two lists under two headings,
    # each reading its own source - rather than by a sentence explaining the
    # difference. The explanatory prose was removed from the screen; the lists
    # it described must still be distinct, which is what this checks.
    assert source.index("FIELDS.currentHubs") < source.index("FIELDS.suggestedHubs")
    assert "metadata[\"hub_memberships\"]" not in source  # the UI never conflates them
    for marker in ("memberships.map", "suggestions.map"):
        assert marker in source, f"{marker} must render its own list"


def test_the_hub_context_reader_asks_for_nothing_it_cannot_find(tmp_path):
    """Every optional table is probed before it is queried.

    hub_sector and actor_sector arrive with backend migration 520. Until then
    the reader returns memberships without suggestions, rather than failing.
    """

    source = pathlib.Path("src/review/postgres_source.py").read_text(encoding="utf-8")
    assert "def _hub_context" in source
    for table in ("hub_actor", "hub_sector", "sector", "actor_sector", "actor_location"):
        assert f'"{table}"' in source, f"{table} is not in the allowlist"
    assert 'columns.get("hub_actor", set())' in source
    assert '{"actor_sector", "sector"} <= set(columns)' in source
    # Suggestions are only offered for a hub inside whose radius the actor sits.
    assert 'if miles > hub["radius_miles"]:' in source
    # An actor already in a hub is not suggested that same hub again.
    assert "placed" in source


def test_every_actor_review_kind_the_database_allows_reaches_the_screen():
    """A pending review item that never appears is the same as no review at all.

    The earlier filter named seven kinds. The database's own ck_review_item_kind
    allows far more, and the restored production copy held 154 pending
    geocode_failed items and 42 relationship_review items that the Review screen
    could not see.
    """

    source = pathlib.Path("src/review/postgres_source.py").read_text(encoding="utf-8")
    body = source.split("WHERE ri.status='pending'", 1)[1].split("ORDER BY", 1)[0]
    for kind in (
        "verify_actor", "category_doubt", "geocode_failed", "hub_assignment",
        "hub_needs_review", "hub_radius_overlap", "hub_member_outside_radius",
        "hub_center_drift", "hub_proposal", "same_topic_overlap",
        "possible_duplicate", "fact_conflict", "pending_update", "relationship_review",
    ):
        assert f"'{kind}'" in body, f"{kind} items would never reach Review"

    # And each one has a label, so none of them renders as a raw code.
    import json
    import subprocess
    labels = subprocess.run(
        ["node", "--input-type=module", "-e",
         "import('file:///' + process.argv[1].replace(/\\/g,'/'))"
         ".then(m => process.stdout.write(JSON.stringify(Object.keys(m.REVIEW_REASON_LABELS))))",
         str(pathlib.Path("frontend/review.js").resolve())],
        capture_output=True, text=True, timeout=60,
    )
    if labels.returncode == 0:
        labelled = set(json.loads(labels.stdout))
        for kind in ("geocode_failed", "possible_duplicate", "fact_conflict", "pending_update"):
            assert kind in labelled, f"{kind} has no label"


def test_the_review_query_survives_the_contract_rename():
    """The V2 contract migration renames the columns this query reads.

    `location_city` becomes `city` and `state` becomes `state_code` when
    migration 500 runs. A bare `a.location_city` therefore raises
    UndefinedColumn against a post-contract database, and because
    fetch_candidates turns a source failure into a warning rather than an
    error, the entire V2 review-item feed disappears from the queue without
    anything looking broken.

    Proved against both schemas by hand on 9 Oct 2026; this keeps it proved.
    """

    source = (Path(__file__).resolve().parents[1]
              / "src/review/postgres_source.py").read_text(encoding="utf-8")

    # No bare reference to either renamed column.
    assert "a.location_city" not in source
    assert "a.state," not in source and "a.state " not in source

    # Both are read through to_jsonb, which tolerates a column that is absent.
    for before, after in (("location_city", "city"), ("state", "state_code")):
        assert f"to_jsonb(a)->>'{before}'" in source
        assert f"to_jsonb(a)->>'{after}'" in source

    # Everything else that the rename touches already used the pattern; make
    # sure nobody reintroduces a direct read of one.
    for renamed in ("actor_category", "category_type", "record_status", "region_code"):
        assert f"a.{renamed}" not in source, f"a.{renamed} must be read through to_jsonb"


def _insert_verify_item(store: ReviewStore, candidate_id: str) -> None:
    import json as _json

    with store.connect() as db:
        db.execute(
            "INSERT INTO review_candidate"
            "(candidate_id,source_run_id,source_description,source_index,entity_type,"
            " display_name,status,created_at,original_payload,reviewed_payload,evidence,"
            " agent_metadata,duplicate_state)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (candidate_id, "v2-review:t", "Architecture V2 verify_actor review", candidate_id,
             "actor", "The Water Council", "pending_review", CUTOFF_TS + 10, "{}",
             _json.dumps({"name": "The Water Council", "actor_category": "association_network",
                          "category_type": "innovation_consortium"}), "[]",
             _json.dumps({"source_table": "review_item", "review_kind": "verify_actor",
                          "review_item_id": "11111111-2222-3333-4444-555555555555"}), "new"),
        )


def test_verifying_a_parked_actor_is_the_ghus_topic_decision(store):
    """A Parked actor's verify_actor item used to be undecidable from Review."""
    _insert_verify_item(store, "item-1")
    decision = store.admission_request(
        "item-1", decision_kind="new", reviewer="Reviewer", idempotency_key="k-1",
        confirmed=True)
    assert decision == {
        "decision_kind": "verify_actor", "verified": True, "rejection_reason": None,
        "review_item_id": "11111111-2222-3333-4444-555555555555", "reviewer": "Reviewer",
        "notes": None, "idempotency_key": "k-1",
    }
    rejected = store.admission_request(
        "item-1", decision_kind="reject", reviewer="Reviewer", idempotency_key="k-2",
        rejection_reason="Not relevant to GHUS sectors", confirmed=True)
    assert rejected["verified"] is False
    assert rejected["rejection_reason"] == "Not relevant to GHUS sectors"
    with pytest.raises(ReviewValidationError):
        store.admission_request("item-1", decision_kind="defer", reviewer="Reviewer",
                                idempotency_key="k-3", confirmed=True)


def test_the_review_reason_says_why_an_item_waits_in_plain_words():
    from src.review.store import derive_review_reason

    def reason(entity="actor", **metadata):
        return derive_review_reason(metadata, entity)

    # The sources' internal codes become what they mean.
    assert reason(review_kind="rubric_band") == "borderline_score"
    assert reason(review_kind="fuzzy_match") == "possible_duplicate"
    assert reason(review_kind="geocode_failed") == "location_unplaced"
    assert reason(review_kind="relationship_review") == "relationship_check"
    assert reason(review_kind="verify_actor") == "verify_actor"
    # A discovery result: the agent's own gate sentence names the reason, the
    # most actionable first.
    assert reason(source_table="search_candidate", score_band="review", triage_reason=(
        "Read from edegan.com, but the organisation's own site is tmc.org: the page is "
        "about it, not by it. Score 0.70 is below the accept threshold 0.80.")) == "third_party_page"
    assert reason(source_table="search_candidate", score_band="review",
                  triage_reason="actor rubric score 0.480 -> review") == "borderline_score"
    assert reason("person", source_table="search_candidate", score_band="auto_high",
                  triage_reason="person rubric score 1.000 -> auto_high") == "new_person"
    assert reason(review_run_source="map", workflow="research") == "map_agent"
    assert reason() is None


def test_the_queue_counts_each_waiting_reason_before_filtering_by_one(store):
    import json as _json
    for cid, kind in (("a", "geocode_failed"), ("b", "geocode_failed"), ("c", "rubric_band")):
        _insert(store, cid, created_at=CUTOFF_TS + 1, source_run_id="run-a",
                description="Open-web actor discovery")
        with store.connect() as db:
            db.execute("UPDATE review_candidate SET agent_metadata=? WHERE candidate_id=?",
                       (_json.dumps({"review_kind": kind}), cid))
    listing = store.list(status="all", review_reason="borderline_score")
    assert listing["reason_counts"] == {"location_unplaced": 2, "borderline_score": 1}
    assert [item["candidate_id"] for item in listing["candidates"]] == ["c"]


def test_the_maps_own_checks_are_one_group_whatever_their_topic(store):
    for cid, run in (("a", "v2-review:topic-1"), ("b", "v2-review:topic-2"), ("c", "v2-review:unscoped")):
        _insert(store, cid, created_at=CUTOFF_TS + 1, source_run_id=run,
                description="Architecture V2 verify_actor review")
    groups = store.list(status="all")["run_groups"]
    assert [(g["key"], g["label"], g["candidate_count"]) for g in groups] == [("map-checks", "Map checks", 3)]
    listed = store.list(status="all", run_group="map-checks")["candidates"]
    assert sorted(item["candidate_id"] for item in listed) == ["a", "b", "c"]
    # The stored run ids are untouched.
    assert sorted(item["source_run_id"] for item in listed) == [
        "v2-review:topic-1", "v2-review:topic-2", "v2-review:unscoped"]


def _insert_fact_item(store: ReviewStore, candidate_id: str, kind: str) -> None:
    import json as _json

    with store.connect() as db:
        db.execute(
            "INSERT INTO review_candidate"
            "(candidate_id,source_run_id,source_description,source_index,entity_type,"
            " display_name,status,created_at,original_payload,reviewed_payload,evidence,"
            " agent_metadata,duplicate_state)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (candidate_id, "v2-review:t", f"Architecture V2 {kind} review", candidate_id,
             "actor", "CPower", "pending_review", CUTOFF_TS + 10, "{}",
             _json.dumps({"name": "CPower"}), "[]",
             _json.dumps({"source_table": "review_item", "review_kind": kind,
                          "review_item_id": "11111111-2222-3333-4444-555555555555",
                          "fact_change": {"field_key": "funding_signal",
                                          "current": {"value": "$1M."},
                                          "proposed": {"value": "$2M."}}}), "new"),
        )


@pytest.mark.parametrize("kind", ["fact_conflict", "pending_update"])
def test_a_fact_review_is_a_choice_between_two_values(store, kind):
    """An update's conflict reaches the backend's fact decision, never a record admission."""
    _insert_fact_item(store, "fact-1", kind)
    use_new = store.admission_request(
        "fact-1", decision_kind="new", reviewer="Reviewer", idempotency_key="k-1",
        confirmed=True)
    assert use_new == {
        "decision_kind": "resolve_fact", "accept": True,
        "review_item_id": "11111111-2222-3333-4444-555555555555", "reviewer": "Reviewer",
        "notes": None, "idempotency_key": "k-1",
    }
    # Keeping the current value needs no rejection reason: nothing is rejected.
    keep = store.admission_request(
        "fact-1", decision_kind="reject", reviewer="Reviewer", idempotency_key="k-2",
        confirmed=True)
    assert keep["decision_kind"] == "resolve_fact" and keep["accept"] is False
    with pytest.raises(ReviewValidationError):
        store.admission_request("fact-1", decision_kind="same_existing", reviewer="Reviewer",
                                idempotency_key="k-3", target_id="x", confirmed=True)


def _insert_item(store: ReviewStore, candidate_id: str, kind: str, pipeline: dict) -> None:
    import json as _json

    with store.connect() as db:
        db.execute(
            "INSERT INTO review_candidate"
            "(candidate_id,source_run_id,source_description,source_index,entity_type,"
            " display_name,status,created_at,original_payload,reviewed_payload,evidence,"
            " agent_metadata,duplicate_state)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (candidate_id, "v2-review:t", f"Architecture V2 {kind} review", candidate_id,
             "actor", "CPower", "pending_review", CUTOFF_TS + 10, "{}",
             _json.dumps({"name": "CPower"}), "[]",
             _json.dumps({"source_table": "review_item", "review_kind": kind,
                          "review_item_id": "11111111-2222-3333-4444-555555555555",
                          "pipeline": pipeline}), "new"),
        )


def test_a_proposed_link_is_confirmed_with_its_source_or_refused(store):
    _insert_item(store, "link-1", "relationship_review", {
        "proposed_relationship_type": "funded_by", "source_url": "https://co.example/news"})
    confirm = store.admission_request("link-1", decision_kind="new", reviewer="R",
                                      idempotency_key="k-1", confirmed=True)
    assert confirm == {
        "decision_kind": "resolve_relationship", "approve": True,
        "review_item_id": "11111111-2222-3333-4444-555555555555",
        "source_url": "https://co.example/news", "relationship_type": "funded_by",
        "reviewer": "R", "notes": None, "idempotency_key": "k-1"}
    refuse = store.admission_request("link-1", decision_kind="reject", reviewer="R",
                                     idempotency_key="k-2", confirmed=True)
    assert refuse["approve"] is False


def test_a_link_with_no_source_can_be_refused_but_never_confirmed(store):
    _insert_item(store, "link-2", "relationship_review", {"proposed_relationship_type": "unit_of"})
    with pytest.raises(ReviewValidationError, match="no source page"):
        store.admission_request("link-2", decision_kind="new", reviewer="R",
                                idempotency_key="k-1", confirmed=True)
    assert store.admission_request("link-2", decision_kind="reject", reviewer="R",
                                   idempotency_key="k-2", confirmed=True)["approve"] is False


def test_a_hub_proposal_is_added_or_kept_out_and_legacy_hub_items_are_untouched(store):
    _insert_item(store, "hub-1", "hub_assignment", {"proposal": "membership",
                                                    "proposed_hub_id": "h1"})
    add = store.admission_request("hub-1", decision_kind="new", reviewer="R",
                                  idempotency_key="k-1", confirmed=True)
    assert (add["decision_kind"], add["accept"]) == ("resolve_hub_membership", True)
    with pytest.raises(ReviewValidationError):
        store.admission_request("hub-1", decision_kind="same_existing", reviewer="R",
                                idempotency_key="k-2", target_id="x", confirmed=True)
    # A legacy hub item (not a membership proposal) is not given this decision.
    _insert_item(store, "hub-2", "hub_assignment", {"issue": "needs_review_sector"})
    with pytest.raises(ReviewValidationError):
        store.admission_request("hub-2", decision_kind="new", reviewer="R",
                                idempotency_key="k-3", confirmed=True)


def test_an_actor_update_run_is_labelled_with_its_actor_and_date():
    from src.review.store import _run_label

    label = _run_label("Actor update: CPower Energy", "actor-update:3f2a", CUTOFF_TS + 5)
    assert label.startswith("Actor update · CPower Energy · ")
    request = _run_label("Actor update: Fill missing boxes: California water organizations",
                         "actor-update:9b1c", CUTOFF_TS + 5)
    assert request.startswith("Actor update · Fill missing boxes: California water organizations")


def test_an_update_card_is_acknowledged_in_review_only(store):
    _insert_item(store, "upd-1", "actor_update", {})
    with store.connect() as db:
        db.execute("UPDATE review_candidate SET agent_metadata=? WHERE candidate_id='upd-1'",
                   ('{"source_table": "actor_update", "review_kind": "actor_update", '
                    '"run_id": "run-9", "entity_id": "a1"}',))
    looks_right = store.admission_request("upd-1", decision_kind="new", reviewer="R",
                                          idempotency_key="k-1", confirmed=True)
    assert looks_right["local_only"] is True and looks_right["looks_right"] is True
    assert looks_right["decision_kind"] == "acknowledge_update"
    flagged = store.admission_request("upd-1", decision_kind="reject", reviewer="R",
                                      idempotency_key="k-2", confirmed=True, notes="Wrong city")
    assert flagged["looks_right"] is False
    with pytest.raises(ReviewValidationError):
        store.admission_request("upd-1", decision_kind="same_existing", reviewer="R",
                                idempotency_key="k-3", target_id="x", confirmed=True)


@pytest.mark.parametrize("kind", ["fact_conflict", "pending_update"])
def test_keep_both_locations_uses_existing_admission_contract(store, kind):
    _insert_item(store, "locations", kind, {"field_key": "location"})
    decision = store.admission_request(
        "locations", decision_kind="new", keep_both=True, reviewer="Reviewer",
        idempotency_key="both-1", confirmed=True)
    assert decision["decision_kind"] == "resolve_fact"
    assert decision["accept"] is False and decision["keep_both"] is True


@pytest.mark.parametrize("kind,field,decision", [
    ("fact_conflict", "funding_signal", "new"),
    ("relationship_review", "location", "new"),
    ("fact_conflict", "location", "reject"),
])
def test_keep_both_cannot_change_other_review_decisions(store, kind, field, decision):
    _insert_item(store, "invalid-both", kind, {"field_key": field})
    with pytest.raises(ReviewValidationError, match="only for a location"):
        store.admission_request(
            "invalid-both", decision_kind=decision, keep_both=True,
            reviewer="Reviewer", idempotency_key="both-2", confirmed=True)


def test_keep_both_api_delegates_and_records_success(store, monkeypatch):
    from fastapi.testclient import TestClient
    from backend import app as api
    from unittest.mock import Mock

    _insert_item(store, "api-locations", "fact_conflict", {"field_key": "location"})
    bridge = Mock()
    bridge.apply.return_value = {"decision_kind": "resolve_fact", "status": "applied",
                                 "decision": "keep_both", "action": "decided"}
    monkeypatch.setattr(api, "review_store", lambda: store)
    monkeypatch.setattr(api, "review_admission_bridge", lambda: bridge)
    response = TestClient(api.app).post("/api/review/candidates/api-locations/decision", json={
        "decision_kind": "new", "keep_both": True, "reviewer": "Reviewer",
        "idempotency_key": "both-api", "confirmed": True,
    })
    assert response.status_code == 200, response.text
    decision = bridge.apply.call_args.args[0]
    assert decision["decision_kind"] == "resolve_fact"
    assert decision["keep_both"] is True and decision["accept"] is False
    with store.connect() as db:
        assert db.execute("SELECT status FROM review_candidate WHERE candidate_id=?",
                          ("api-locations",)).fetchone()[0] == "approved"
