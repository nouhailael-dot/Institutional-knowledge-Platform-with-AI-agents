"""Actor updates in Review: one profile per actor, its boxes filled, its changes decided.

An actor updated three times used to appear as three update cards, plus one
card per conflicting box and per proposal - the same organisation five times.
These tests pin the replacement down:

  * one profile per actor; the per-run cards and per-change items it shows are
    folded into it - kept, decisions and all, but not listed again;
  * a newer run replaces a pending profile, never a decided one;
  * a change is decided on the profile (keep current, use new, keep both only
    for a location) through the backend's writer, and stays listed as decided;
  * the profile is marked reviewed only once its changes are decided.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.review.store import (  # noqa: E402
    ReviewConflict,
    ReviewStore,
    ReviewValidationError,
    _external_candidate_id,
)

ACTOR = "11111111-2222-4333-8444-555555555555"
CHANGE = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
LOCATION_CHANGE = "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"


@pytest.fixture
def store(tmp_path):
    return ReviewStore(tmp_path / "review.sqlite3", enable_test_canonical=True)


def _card(key, run, *, kind="actor_update", meta=None, created=1_800_000_000.0):
    return {
        "source_key": key, "source_run_id": f"actor-update:{run}", "source_index": key,
        "source_description": "Actor update: CPower Energy", "entity_type": "actor",
        "payload": {"name": "CPower Energy", "website": "https://cpowerenergy.com/",
                    "actor_category": "company"},
        "evidence": [], "agent_metadata": {"source_table": kind, "entity_id": ACTOR,
                                           "run_id": run, **(meta or {})},
        "duplicate_state": "not_checked", "created_at": created,
    }


def _profile(run, *, folds=(), changes=(), created=1_800_000_100.0):
    card = _card(f"postgres:actor_updates:{ACTOR}:{run}", run, created=created, meta={
        "review_kind": "actor_profile", "topic_name": "Energy Transition",
        "facts": [{"fact_key": "location", "fact_type": "light_pull", "layer": 1,
                   "collection_state": "found", "value": {"city": "Baltimore", "state": "MD"},
                   "update": {"outcome": "changed", "run_id": run}}],
        "update_runs": [{"run_id": run, "title": "CPower Energy", "counts": {"changed": 1}}],
        "changes": list(changes)})
    card["folds"] = list(folds)
    return card


FACT_CHANGE = {"review_item_id": CHANGE, "kind": "fact", "field_key": "funding_signal",
               "current": {"value": "$1M."}, "proposed": {"value": "$3M."},
               "can_keep_both": False}
LOCATION = {"review_item_id": LOCATION_CHANGE, "kind": "fact", "field_key": "location",
            "current": {"value": {"city": "Baltimore"}}, "proposed": {"value": {"city": "Houston"}},
            "can_keep_both": True}


def _listed(store):
    return [c["source_index"] for c in store.list(status="all")["candidates"]]


def test_one_profile_per_actor_and_the_cards_it_shows_are_folded_not_deleted(store):
    old_run, old_item = "postgres:actor_update:r1:a", "postgres:review_item:i1"
    store.sync_external_candidates([_card(old_run, "r1"), _card(old_item, "r1", kind="review_item")])
    assert len(_listed(store)) == 2

    profile = _profile("r1", folds=[old_run, old_item], changes=[FACT_CHANGE])
    store.sync_external_candidates([profile])
    assert _listed(store) == [profile["source_key"]]
    # Kept, with the profile it is now part of; counts and runs count it once.
    folded = store.get(_external_candidate_id(old_run))
    assert folded["folded_into"] == _external_candidate_id(profile["source_key"])
    listing = store.list(status="all")
    assert listing["counts"]["pending_review"] == 1
    assert sum(g["candidate_count"] for g in listing["run_groups"]) == 1
    # A folded card is decided on its profile, not on its own.
    with pytest.raises(ReviewConflict, match="update profile"):
        store.admission_request(folded["candidate_id"], decision_kind="new", reviewer="R",
                                idempotency_key="k-folded", confirmed=True)


def test_a_newer_run_replaces_a_pending_profile_but_never_a_decided_one(store):
    first = _profile("r1")
    store.sync_external_candidates([first])
    second = _profile("r2", folds=[first["source_key"]], created=1_800_000_200.0)
    store.sync_external_candidates([second])
    assert _listed(store) == [second["source_key"]]

    # Reviewed (looks right), then a third run arrives: the decided profile stays.
    profile_id = _external_candidate_id(second["source_key"])
    decision = store.admission_request(profile_id, decision_kind="new", reviewer="R",
                                       idempotency_key="k-ok", confirmed=True)
    assert decision["decision_kind"] == "acknowledge_update"
    store.record_admission_success(profile_id, idempotency_key="k-ok", decision_kind="new",
                                   reviewer="R", notes=None, rejection_reason=None,
                                   outcome={"status": "applied"})
    third = _profile("r3", folds=[first["source_key"], second["source_key"]],
                     created=1_800_000_300.0)
    store.sync_external_candidates([third])
    assert store.get(profile_id)["status"] == "approved"
    assert store.get(profile_id)["folded_into"] is None
    assert set(_listed(store)) == {second["source_key"], third["source_key"]}


def test_retired_update_runs_leave_the_queue_but_stay_stored(store):
    test_run = "postgres:actor_update:test-run:a"
    store.sync_external_candidates([_card(test_run, "test-run")])
    store.sync_external_candidates([], retired={test_run: "inactive_sector"})
    assert _listed(store) == []
    assert store.get(_external_candidate_id(test_run))["folded_into"] == "inactive_sector"


def test_a_profile_is_marked_reviewed_only_once_its_changes_are_decided(store):
    store.sync_external_candidates([_profile("r1", changes=[FACT_CHANGE])])
    profile_id = _external_candidate_id(f"postgres:actor_updates:{ACTOR}:r1")
    with pytest.raises(ReviewValidationError, match="1 change"):
        store.admission_request(profile_id, decision_kind="new", reviewer="R",
                                idempotency_key="k1", confirmed=True)
    # Flagging needs no decision on the changes.
    flagged = store.admission_request(profile_id, decision_kind="reject", reviewer="R",
                                      idempotency_key="k2", confirmed=True)
    assert flagged["looks_right"] is False


@pytest.mark.parametrize(("choice", "shape"), [
    ("keep_current", {"decision_kind": "resolve_fact", "accept": False, "keep_both": False}),
    ("use_new", {"decision_kind": "resolve_fact", "accept": True, "keep_both": False}),
])
def test_a_value_change_is_kept_or_replaced_through_the_backend_writer(store, choice, shape):
    store.sync_external_candidates([_profile("r1", changes=[FACT_CHANGE])])
    profile_id = _external_candidate_id(f"postgres:actor_updates:{ACTOR}:r1")
    decision = store.change_request(profile_id, CHANGE, choice=choice, reviewer="R",
                                    idempotency_key=f"k-{choice}", confirmed=True)
    assert {k: decision[k] for k in shape} == shape
    assert decision["review_item_id"] == CHANGE


def test_keep_both_only_where_a_box_can_hold_two_values(store):
    store.sync_external_candidates([_profile("r1", changes=[FACT_CHANGE, LOCATION])])
    profile_id = _external_candidate_id(f"postgres:actor_updates:{ACTOR}:r1")
    with pytest.raises(ReviewValidationError, match="only to a location"):
        store.change_request(profile_id, CHANGE, choice="keep_both", reviewer="R",
                             idempotency_key="k1", confirmed=True)
    both = store.change_request(profile_id, LOCATION_CHANGE, choice="keep_both", reviewer="R",
                                idempotency_key="k2", confirmed=True)
    assert both["keep_both"] is True and both["accept"] is False
    with pytest.raises(ReviewValidationError, match="Unsupported choice"):
        store.change_request(profile_id, CHANGE, choice="confirm", reviewer="R",
                             idempotency_key="k3", confirmed=True)
    with pytest.raises(ReviewValidationError, match="confirmation"):
        store.change_request(profile_id, CHANGE, choice="use_new", reviewer="R",
                             idempotency_key="k4")


def test_a_decided_change_moves_to_decided_and_cannot_be_decided_twice(store):
    store.sync_external_candidates([_profile("r1", changes=[FACT_CHANGE])])
    profile_id = _external_candidate_id(f"postgres:actor_updates:{ACTOR}:r1")
    updated = store.record_change_decision(profile_id, CHANGE, choice="use_new", reviewer="R",
                                           idempotency_key="k1", notes=None,
                                           outcome={"action": "decided"})
    meta = updated["agent_metadata"]
    assert meta["changes"] == []
    assert [(d["field_key"], d["choice"], d["reviewer"]) for d in meta["decided_changes"]] == [
        ("funding_signal", "use_new", "R")]
    with pytest.raises(ReviewConflict, match="already been decided"):
        store.change_request(profile_id, CHANGE, choice="keep_current", reviewer="R",
                             idempotency_key="k2", confirmed=True)
    # With its changes decided, the profile can be marked reviewed.
    assert store.admission_request(profile_id, decision_kind="new", reviewer="R",
                                   idempotency_key="k3", confirmed=True)["looks_right"] is True


def test_the_change_route_applies_through_the_bridge_and_returns_the_profile(store, monkeypatch):
    from fastapi.testclient import TestClient

    import backend.app as app_module

    store.sync_external_candidates([_profile("r1", changes=[FACT_CHANGE])])
    profile_id = _external_candidate_id(f"postgres:actor_updates:{ACTOR}:r1")
    applied = []

    class Bridge:
        def apply(self, decision):
            applied.append(decision)
            return {"decision_kind": decision["decision_kind"], "status": "applied"}

    monkeypatch.setattr(app_module, "review_store", lambda: store)
    monkeypatch.setattr(app_module, "review_admission_bridge", lambda: Bridge())
    monkeypatch.setattr(app_module, "_sync_review_candidates", lambda **kwargs: [])
    client = TestClient(app_module.app)
    body = {"choice": "keep_current", "reviewer": "R", "idempotency_key": "k1", "confirmed": True}
    response = client.post(f"/api/review/candidates/{profile_id}/changes/{CHANGE}", json=body)
    assert response.status_code == 200, response.text
    assert applied == [{"review_item_id": CHANGE, "reviewer": "R", "notes": None,
                        "idempotency_key": "k1", "decision_kind": "resolve_fact",
                        "accept": False, "keep_both": False}]
    assert response.json()["agent_metadata"]["decided_changes"][0]["choice"] == "keep_current"
    again = client.post(f"/api/review/candidates/{profile_id}/changes/{CHANGE}", json=body)
    assert again.status_code == 409 and len(applied) == 1
    assert client.post(f"/api/review/candidates/{profile_id}/changes/not-a-uuid",
                       json=body).status_code == 404


def test_the_earlier_profile_fills_one_box_per_fact_and_never_recent_activity():
    from src.review.postgres_source import PostgresReviewSource

    rows = [
        {"fact_key": "current_activities", "value": "Supports boundary water governance.",
         "confidence": "low", "retrieved_at": None, "fact_type": "legacy_profile", "source_url": None},
        {"fact_key": "primary_technical_focus", "value": "Water quality and restoration.",
         "confidence": "low", "retrieved_at": None, "fact_type": "legacy_baseline", "source_url": None},
        {"fact_key": "funding_summary", "value": "Government contributions.",
         "confidence": "low", "retrieved_at": None, "fact_type": "legacy_profile", "source_url": None},
    ]

    class DB:
        def execute(self, sql, params):
            self.params = params
            return self

        def fetchall(self):
            return rows

    source = PostgresReviewSource.__new__(PostgresReviewSource)
    facts = source._legacy_record_facts(DB(), ACTOR, "association_network")
    boxes = {f["fact_key"]: f["value"] for f in facts}
    assert boxes == {
        "sector_geographic_scope": "Water quality and restoration.",
        "current_initiative_working_group": "Supports boundary water governance.",
        "funding_signal": "Government contributions.",
    }
    assert "recent_activity" not in boxes
    assert len(set(boxes.values())) == len(boxes)          # no paragraph in two boxes
    assert all(f["from_record"] == "earlier GHUS profile" and f["source_origin"] == "imported"
               for f in facts)


TYPE_CHANGE = {"review_item_id": CHANGE, "kind": "category_type",
               "actor_category": "association_network", "category_type": "professional_network",
               "category_label": "Association / Consortium / Network",
               "type_label": "Professional Network", "source_url": "https://ijc.org/en/about"}


def test_a_proposed_category_type_is_used_or_refused_through_the_backend_writer(store):
    store.sync_external_candidates([_profile("r1", changes=[TYPE_CHANGE])])
    profile_id = _external_candidate_id(f"postgres:actor_updates:{ACTOR}:r1")
    use = store.change_request(profile_id, CHANGE, choice="confirm", reviewer="R",
                               idempotency_key="k1", confirmed=True)
    assert (use["decision_kind"], use["accept"]) == ("resolve_category_type", True)
    refuse = store.change_request(profile_id, CHANGE, choice="refuse", reviewer="R",
                                  idempotency_key="k2", confirmed=True)
    assert refuse["accept"] is False
    with pytest.raises(ReviewValidationError, match="Unsupported choice"):
        store.change_request(profile_id, CHANGE, choice="use_new", reviewer="R",
                             idempotency_key="k3", confirmed=True)


def test_a_category_type_proposal_reads_as_a_change_with_its_labels():
    from src.review.postgres_source import PostgresReviewSource

    item = {"source_run_id": "actor-update:r1", "created_at": 1, "agent_metadata": {
        "review_kind": "category_doubt", "review_item_id": CHANGE, "pipeline": {
            "proposal": "category_type", "actor_category": "association_network",
            "proposed_category_type": "professional_network", "category_note": None,
            "main_job": "It convenes water managers.", "source_url": "https://ijc.org"}}}
    change = PostgresReviewSource._change_of(object.__new__(PostgresReviewSource), item, {})
    assert change["kind"] == "category_type" and change["run_id"] == "r1"
    assert (change["category_label"], change["type_label"]) == (
        "Association / Consortium / Network", "Professional Network")
    # A category doubt from discovery is not a profile change: it keeps its own card.
    item["agent_metadata"]["pipeline"] = {"issue": "category_doubt"}
    assert PostgresReviewSource._change_of(object.__new__(PostgresReviewSource), item, {}) is None


def test_old_items_are_set_aside_off_the_page_and_can_be_listed_again(store):
    old_item, recent = "postgres:review_item:old", "postgres:actor_update:recent:a"
    store.sync_external_candidates([_card(old_item, "r0", kind="review_item"), _card(recent, "r1")])
    old_id = _external_candidate_id(old_item)
    assert store.set_aside([old_id], reason="old_items") == 1
    assert _listed(store) == [recent]
    assert store.list(status="all")["counts"]["pending_review"] == 1
    kept = store.get(old_id)                       # still stored, still pending, undecided
    assert (kept["status"], kept["folded_into"]) == ("pending_review", "set_aside:old_items")
    # A later sync does not bring it back; restoring does.
    store.sync_external_candidates([_card(old_item, "r0", kind="review_item")])
    assert _listed(store) == [recent]
    assert store.restore_set_aside("old_items") == 1
    assert set(_listed(store)) == {old_item, recent}


def test_the_old_item_rules_pick_only_old_work():
    import json as _json
    from datetime import UTC, datetime

    from scripts.set_aside_old_review_items import group_of

    def row(run, description="", kind=None, day=(2026, 10, 28)):
        return {"source_run_id": run, "source_description": description,
                "agent_metadata": _json.dumps({"review_kind": kind}),
                "created_at": datetime(*day, tzinfo=UTC).timestamp()}

    assert group_of(row("v2-review:x", kind="geocode_failed", day=(2026, 10, 9))) == "migration"
    assert group_of(row("v2-review:x", kind="fact_conflict", day=(2026, 10, 20))) == "early_update"
    assert group_of(row("v2-review:x", kind="fact_conflict", day=(2026, 10, 28))) is None
    assert group_of(row("discovery:r", "Open-web actor discovery - dry_run - 38e8")) == "test_run"
    assert group_of(row("datafeed:r", "Data Feed import: Admission E2E actors")) == "test_import"
    assert group_of(row("datafeed:r", "Data Feed import: Verified example")) is None
    assert group_of(row("actor-update:r", "Actor update: General update")) is None
