from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from agents.common.hub_assignment import (
    ASSIGNED,
    NEEDS_REVIEW_LOCATION,
    NEEDS_REVIEW_SECTOR,
    NEEDS_REVIEW_TOPIC,
    ActorHubContext,
    HubCandidate,
    build_hub_assignment_plan,
    evaluate_hub_candidate,
    legacy_membership_assessment,
)
from agents.common.hub_centers import (
    CenterMember,
    compute_density_center,
    eligible_center_members,
    preview_center_drift,
)
from agents.discovery.promote import _insert_hub_review_bridge
from agents.enrichment.decisions import (
    apply_hub_center_decision,
    record_hub_center_drift_review,
)

ROOT = Path(__file__).resolve().parents[2]


# Hub membership now gates on SECTOR (GHUS decision, 2026-10-08). This suite is
# the regression suite for the ORIGINAL topic rule, which is retained as a
# configuration option, so every call here asks for it explicitly. The sector
# rule has its own tests at the bottom of this file.
TOPIC_MODE = "topic"


def actor(topic="topic-a", latitude=0.0, longitude=0.0, sectors=()):
    return ActorHubContext("actor-a", topic, latitude, longitude, frozenset(sectors))


def hub(hub_id="hub-a", topic="topic-a", latitude=1.0, longitude=1.0, radius=200.0,
        sector=None):
    return HubCandidate(hub_id, hub_id, topic, latitude, longitude, radius, sector)


@pytest.mark.parametrize(
    ("distance", "outcome", "outside"),
    [(199.0, ASSIGNED, False), (200.0, ASSIGNED, False), (201.0, NEEDS_REVIEW_LOCATION, True)],
)
def test_assignment_radius_boundaries(distance, outcome, outside):
    result = evaluate_hub_candidate(actor(), hub(), distance_fn=lambda *_: distance, dimension=TOPIC_MODE)
    assert (result.outcome, result.outside_radius) == (outcome, outside)


@pytest.mark.parametrize(
    ("candidate", "context"),
    [(hub(latitude=None), actor()), (hub(), actor(latitude=None)), (hub(), actor(longitude=None))],
)
def test_missing_actor_or_hub_coordinates_routes_location_review(candidate, context):
    result = evaluate_hub_candidate(context, candidate, dimension=TOPIC_MODE)
    assert result.outcome == NEEDS_REVIEW_LOCATION
    assert result.location_evaluated is False
    assert result.distance_miles is None


def test_topic_mismatch_is_low_priority_and_never_evaluates_distance():
    def forbidden(*_):
        raise AssertionError("distance must not run before topic passes")

    result = evaluate_hub_candidate(actor(), hub(topic="topic-b"), distance_fn=forbidden, dimension=TOPIC_MODE)
    assert result.outcome == NEEDS_REVIEW_TOPIC
    assert result.priority == "low"
    assert result.location_evaluated is False


def test_different_topics_can_each_have_a_membership_plan():
    first = build_hub_assignment_plan(actor(topic="a"), [hub("a", topic="a")], distance_fn=lambda *_: 10, dimension=TOPIC_MODE)
    second = build_hub_assignment_plan(actor(topic="b"), [hub("b", topic="b")], distance_fn=lambda *_: 20, dimension=TOPIC_MODE)
    assert first.assigned_hub_ids == ("a",)
    assert second.assigned_hub_ids == ("b",)


def test_same_topic_selects_nearest_and_retains_complete_overlap_evidence():
    distances = {"hub-a": 80.0, "hub-b": 20.0, "hub-c": 40.0}
    # Give each candidate a distinct latitude that identifies it to the fake distance function.
    candidates = [hub("hub-a", latitude=1), hub("hub-b", latitude=2), hub("hub-c", latitude=3)]
    plan = build_hub_assignment_plan(actor(), candidates, distance_fn=lambda _a, _b, lat, _lon: {1: 80, 2: 20, 3: 40}[lat]
    , dimension=TOPIC_MODE)
    assert plan.assigned_hub_ids == ("hub-b",)
    assert plan.same_topic_overlap_hub_ids == ("hub-b", "hub-c", "hub-a")
    assert {item.hub_id for item in plan.evaluations if item.outcome == ASSIGNED} == set(distances)


def test_ties_and_input_order_are_deterministic():
    candidates = [hub("hub-b"), hub("hub-a")]
    expected = build_hub_assignment_plan(actor(), candidates, distance_fn=lambda *_: 10, dimension=TOPIC_MODE)
    assert expected.assigned_hub_ids == ("hub-a",)
    for ordering in itertools.permutations(candidates):
        assert build_hub_assignment_plan(actor(), ordering, distance_fn=lambda *_: 10, dimension=TOPIC_MODE) == expected


def member(actor_id, status, latitude, longitude, category="company", city=None):
    return CenterMember(actor_id, city or actor_id, "CA", latitude, longitude, status, category)


def test_centers_use_only_verified_and_imported_and_exclude_aggregate():
    members = [
        member("verified", "verified", 0, 0),
        member("imported", "imported", 0.1, 0.1),
        member("parked", "parked", 10, 10),
        member("rejected", "rejected", 20, 20),
        member("aggregate", "verified", 30, 30, "aggregate"),
    ]
    assert {item.actor_id for item in eligible_center_members(members)} == {"verified", "imported"}
    result = compute_density_center(members)
    assert result is not None
    assert result.eligible_member_count == 2


def test_center_ties_are_stable_and_density_wins():
    members = [member("b", "verified", 0, 0, city="Beta"), member("a", "imported", 0, 0.1, city="Alpha")]
    result = compute_density_center(reversed(members), core_radius_miles=50)
    assert result is not None
    assert result.city == "Alpha"


def test_frozen_center_never_moves_and_large_shift_requires_review():
    proposed = compute_density_center([member("new", "verified", 0, 1)])
    drift = preview_center_drift(0, 0, proposed, frozen=True, threshold_miles=25)
    assert drift.shift_miles is not None and drift.shift_miles > 25
    assert drift.review_required is True
    assert drift.frozen is True


def test_all_821_legacy_memberships_are_preserved_by_assessment():
    pairs = [(f"actor-{index}", f"hub-{index % 49}") for index in range(821)]
    assessed = [
        (pair, legacy_membership_assessment(actor(), hub(pair[1]), distance_fn=lambda *_: 201, dimension=TOPIC_MODE))
        for pair in pairs
    ]
    assert [pair for pair, _ in assessed] == pairs
    assert all(result.membership_preserved for _, result in assessed)
    assert all(result.evidence_outcome == "legacy_membership_preserved" for _, result in assessed)
    assert all(result.evaluation.outside_radius for _, result in assessed)
    assert all(result.canonical_review_kind == "hub_member_outside_radius" for _, result in assessed)


def test_dry_run_and_live_use_the_same_pure_assignment_plan():
    candidates = [hub("hub-a", latitude=1), hub("hub-b", latitude=2)]
    dry_plan = build_hub_assignment_plan(actor(), candidates, distance_fn=lambda _a, _b, lat, _lon: {1: 50, 2: 75}[lat]
    , dimension=TOPIC_MODE)
    live_plan = build_hub_assignment_plan(actor(), candidates, distance_fn=lambda _a, _b, lat, _lon: {1: 50, 2: 75}[lat]
    , dimension=TOPIC_MODE)
    assert dry_plan == live_plan


def test_phase6_writer_and_review_bridges_are_explicit():
    promote = (ROOT / "agents" / "discovery" / "promote.py").read_text(encoding="utf-8")
    decisions = (ROOT / "agents" / "enrichment" / "decisions.py").read_text(encoding="utf-8")
    migration = (ROOT / "migrations" / "proposed" / "deferred" / "390_v2_hub_review_kinds.sql").read_text(encoding="utf-8")
    assert "INSERT INTO hub_actor" in promote
    assert "UPDATE hub SET center_city" in decisions
    assert "compatibility_bridge" in promote
    assert "canonical_outcome" in promote
    assert "method_version" in promote
    assert "COALESCE((payload->>'compatibility_bridge')::boolean, false)" in migration


class _MappingResult:
    def __init__(self, row=None):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row


class _RecordingSession:
    def __init__(self, row=None):
        self.row = row
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return _MappingResult(self.row)


def test_topic_bridge_preserves_distinct_outcome_and_full_marker_contract():
    session = _RecordingSession()
    _insert_hub_review_bridge(
        session,
        actor_id="00000000-0000-0000-0000-000000000001",
        topic_id="00000000-0000-0000-0000-000000000002",
        hub_ids=["00000000-0000-0000-0000-000000000003"],
        current_kind="hub_assignment",
        canonical_kind="hub_needs_review",
        canonical_outcome=NEEDS_REVIEW_TOPIC,
        priority="low",
        evidence={"topic_matched": False},
    )
    payload = json.loads(session.calls[0][1]["payload"])
    assert payload["compatibility_bridge"] is True
    assert payload["canonical_review_kind"] == "hub_needs_review"
    assert payload["canonical_outcome"] == NEEDS_REVIEW_TOPIC
    assert payload["issue"] == NEEDS_REVIEW_TOPIC
    assert payload["deterministic_evidence"] == {"topic_matched": False}
    assert payload["method_version"] == "hub_assignment_v1"
    assert session.calls[0][1]["priority"] == "low"


def test_center_drift_recording_is_evidence_only():
    session = _RecordingSession()
    record_hub_center_drift_review(
        session,
        hub_id="00000000-0000-0000-0000-000000000001",
        topic_id=None,
        proposed_city="Alpha",
        proposed_state_code="CA",
        proposed_latitude=1,
        proposed_longitude=2,
        shift_miles=26,
        threshold_miles=25,
        eligible_member_count=10,
    )
    statements = " ".join(statement for statement, _ in session.calls).lower()
    assert "insert into hub_center_review" in statements
    assert "insert into review_item" in statements
    assert "update hub " not in statements


def test_center_mutation_requires_approved_review_and_uses_decision_writer():
    rejected = _RecordingSession()
    with pytest.raises(ValueError, match="approved"):
        apply_hub_center_decision(
            rejected,
            hub_id="00000000-0000-0000-0000-000000000001",
            hub_center_review_id="00000000-0000-0000-0000-000000000002",
            decided_by="schema-owner",
        )

    approved = _RecordingSession(
        {
            "proposed_city": "Alpha",
            "proposed_state_code": "CA",
            "proposed_latitude": 1,
            "proposed_longitude": 2,
        }
    )
    apply_hub_center_decision(
        approved,
        hub_id="00000000-0000-0000-0000-000000000001",
        hub_center_review_id="00000000-0000-0000-0000-000000000002",
        decided_by="schema-owner",
    )
    assert "UPDATE hub SET center_city" in approved.calls[-1][0]


def test_phase6_does_not_introduce_forbidden_identifier():
    paths = [
        ROOT / "agents" / "common" / "hub_assignment.py",
        ROOT / "agents" / "common" / "hub_centers.py",
        ROOT / "agents" / "sql" / "380_v2_hub_assignment_evidence.sql",
    ]
    assert all("hub_overlap" not in path.read_text(encoding="utf-8") for path in paths)


# ===========================================================================
# Hub membership gates on SECTOR (GHUS decision, 2026-10-08).
#
# Architecture V2 Sept 2.2 makes Test 1 the topic. That decision overrides it;
# docs/decisions/2026-10-08-hub-membership-keys-on-sector.md records why. Topic
# is still evaluated and still recorded, it simply no longer decides.
# ===========================================================================

def test_sector_is_test_one_and_short_circuits_before_distance():
    def forbidden(*_args):
        raise AssertionError("distance must not be measured when the sector fails")

    result = evaluate_hub_candidate(
        actor(sectors=("AGRI",)), hub(sector="MINING"), distance_fn=forbidden
    )
    assert result.outcome == NEEDS_REVIEW_SECTOR
    assert result.sector_matched is False
    assert result.location_evaluated is False
    assert result.priority == "low"


def test_a_matching_sector_assigns_even_when_the_topic_differs():
    """The behaviour change, in one assertion."""

    result = evaluate_hub_candidate(
        actor(topic="topic-a", sectors=("AGRI",)),
        hub(topic="topic-b", sector="AGRI"),
        distance_fn=lambda *_: 10.0,
    )
    assert result.outcome == ASSIGNED
    assert result.sector_matched is True
    # The topic mismatch is recorded, not discarded, and did not decide.
    assert result.topic_matched is False
    assert result.dimension == "sector"


def test_a_matching_topic_no_longer_assigns_on_its_own():
    result = evaluate_hub_candidate(
        actor(topic="topic-a", sectors=("AGRI",)),
        hub(topic="topic-a", sector="MINING"),
        distance_fn=lambda *_: 10.0,
    )
    assert result.outcome == NEEDS_REVIEW_SECTOR
    assert result.topic_matched is True and result.sector_matched is False


def test_an_actor_in_several_sectors_matches_any_of_them():
    both = actor(sectors=("AGRI", "WATER"))
    for code in ("AGRI", "WATER"):
        assert evaluate_hub_candidate(
            both, hub(sector=code), distance_fn=lambda *_: 10.0
        ).outcome == ASSIGNED
    assert evaluate_hub_candidate(
        both, hub(sector="MINING"), distance_fn=lambda *_: 10.0
    ).outcome == NEEDS_REVIEW_SECTOR


def test_a_hub_with_no_sector_matches_nothing_rather_than_everything():
    result = evaluate_hub_candidate(
        actor(sectors=("AGRI",)), hub(sector=None), distance_fn=lambda *_: 10.0
    )
    assert result.outcome == NEEDS_REVIEW_SECTOR
    # Likewise an actor with no sectors at all.
    assert evaluate_hub_candidate(
        actor(sectors=()), hub(sector="AGRI"), distance_fn=lambda *_: 10.0
    ).outcome == NEEDS_REVIEW_SECTOR


def test_the_radius_still_decides_test_two():
    far = evaluate_hub_candidate(
        actor(sectors=("AGRI",)), hub(sector="AGRI"), distance_fn=lambda *_: 201.0
    )
    assert far.outcome == NEEDS_REVIEW_LOCATION and far.outside_radius is True


def test_overlapping_same_sector_hubs_pick_the_nearest_and_flag_the_overlap():
    near, far = hub("hub-near", sector="AGRI"), hub("hub-far", sector="AGRI")
    by_longitude = {near.center_longitude: 10.0, far.center_longitude: 50.0}
    far = HubCandidate("hub-far", "hub-far", "topic-a", 1.0, 2.0, 200.0, "AGRI")
    by_longitude = {1.0: 10.0, 2.0: 50.0}
    plan = build_hub_assignment_plan(
        actor(sectors=("AGRI",)),
        [far, near],
        distance_fn=lambda _alat, _alon, _hlat, hlon: by_longitude[hlon],
    )
    assert plan.assigned_hub_ids == ("hub-near",)
    assert set(plan.overlap_hub_ids) == {"hub-near", "hub-far"}
    # The deprecated name still answers, so older callers keep working.
    assert plan.same_topic_overlap_hub_ids == plan.overlap_hub_ids


def test_the_stored_evidence_says_which_dimension_decided():
    """A reviewer reading a stored assignment must be able to tell what gated it."""

    source = (ROOT / "agents/discovery/promote.py").read_text(encoding="utf-8")
    assert '"sector_matched": evaluation.sector_matched' in source
    assert '"dimension": evaluation.dimension' in source
    # Both results travel together; the topic one is kept, not dropped.
    assert '"topic_matched": evaluation.topic_matched' in source

    migration = (ROOT / "agents/sql/530_v2_conformance_fixes.sql").read_text(encoding="utf-8")
    assert "ALTER TABLE hub_assignment_evidence" in migration
    assert "sector_matched" in migration and "ck_hub_assignment_dimension" in migration
    # And the proposal records its dimension and its secondary topic mix.
    assert "ADD COLUMN IF NOT EXISTS dimension_key" in migration
    assert "topic_mix" in migration


def test_the_promote_writer_gathers_hubs_by_sector():
    source = (ROOT / "agents/discovery/promote.py").read_text(encoding="utf-8")
    assert "sector_codes=tuple(staged.sector_codes or ())" in source
    # The sector tables may not exist yet; the writer checks rather than assuming.
    assert "to_regclass('public.hub_sector')" in source


def test_the_detection_loader_reads_sectors_and_degrades_honestly():
    source = (ROOT / "agents/hubs/detect.py").read_text(encoding="utf-8")
    assert "FROM actor_sector asec" in source
    assert "assigned_sector_codes=" in source
    # No silent fall back to the topic rule when sector data is absent.
    assert "does not quietly fall back to the topic rule" in source
