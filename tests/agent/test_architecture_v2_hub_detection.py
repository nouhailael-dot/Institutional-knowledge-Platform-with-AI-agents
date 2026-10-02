from __future__ import annotations

import math
import random
from dataclasses import replace
from pathlib import Path

from agents.common.geography import EARTH_RADIUS_MILES
from agents.common.hub_detection import (
    FAMILY_FINGERPRINT_VERSION,
    HUB_PROPOSAL_METHOD_VERSION,
    DetectionActor,
    HubDetectionConfig,
    TrustedHub,
    canonical_result_json,
    detect_new_hubs,
    family_set_fingerprint,
    maximum_category_matching,
)
from agents.common.hub_families import FamilyEdge, resolve_actor_families
from agents.hubs.detect import DetectionSnapshot, compute_detection_snapshot

ROOT = Path(__file__).resolve().parents[2]
CATEGORIES = (
    "university_academic",
    "research_center",
    "national_laboratory",
    "company",
    "government",
)


def actor(
    actor_id: str,
    *,
    category: str = "company",
    category_type: str = "established_company",
    latitude: float | None = 0.0,
    longitude: float | None = 0.0,
    city: str | None = "Alpha",
    state: str | None = "CA",
    status: str = "verified",
    topic: str = "topic-1",
    topic_name: str = "Fusion",
    assigned: frozenset[str] = frozenset(),
    merged: bool = False,
) -> DetectionActor:
    return DetectionActor(
        actor_id,
        f"Actor {actor_id}",
        topic,
        topic_name,
        city,
        state,
        latitude,
        longitude,
        status,
        category,
        category_type,
        assigned,
        merged,
    )


def cluster(
    prefix: str,
    count: int = 10,
    *,
    longitude: float = 0.0,
    categories: tuple[str, ...] = CATEGORIES,
    topic: str = "topic-1",
    status: str = "verified",
) -> list[DetectionActor]:
    return [
        actor(
            f"{prefix}-{index:02d}",
            category=categories[index % len(categories)],
            longitude=longitude,
            city=f"City {prefix}",
            topic=topic,
            status=status,
        )
        for index in range(count)
    ]


def run(
    actors,
    *,
    edges=(),
    hubs=(),
    prior=(),
    config: HubDetectionConfig | None = None,
):
    return detect_new_hubs(actors, edges, hubs, prior, config or HubDetectionConfig())


def latitude_for_miles(miles: float) -> float:
    return math.degrees(miles / EARTH_RADIUS_MILES)


def test_01_actor_without_parent_is_own_family():
    assert resolve_actor_families(["a"], []).family_by_actor == {"a": "a"}


def test_02_authoritative_relationships_resolve_top_root():
    for relationship in ("unit_of", "operated_by"):
        result = resolve_actor_families(["child"], [FamilyEdge("child", "root", relationship)])
        assert result.family_by_actor == {"child": "root"}


def test_03_nonstructural_relationships_are_ignored():
    for relationship in ("partner_of", "funded_by", "located_in"):
        result = resolve_actor_families(["child"], [FamilyEdge("child", "root", relationship)])
        assert result.family_by_actor == {"child": "child"}


def test_04_family_cycle_fails_closed():
    edges = [FamilyEdge("a", "b", "unit_of"), FamilyEdge("b", "a", "operated_by")]
    result = resolve_actor_families(["a", "b"], edges)
    assert result.family_by_actor == {}
    assert set(result.unresolved.values()) == {"cycle"}


def test_05_multiple_distinct_roots_fail_closed():
    edges = [FamilyEdge("a", "r1", "unit_of"), FamilyEdge("a", "r2", "operated_by")]
    result = resolve_actor_families(["a"], edges)
    assert result.unresolved == {"a": "multiple_distinct_roots"}


def test_06_ambiguous_ancestor_fails_closed():
    edges = [
        FamilyEdge("a", "p", "unit_of"),
        FamilyEdge("p", "r1", "unit_of"),
        FamilyEdge("p", "r2", "operated_by"),
    ]
    assert resolve_actor_families(["a"], edges).unresolved["a"] == "multiple_distinct_roots"


def test_07_family_resolution_is_input_order_invariant():
    edges = [FamilyEdge("a", "p", "unit_of"), FamilyEdge("p", "r", "operated_by")]
    assert resolve_actor_families(["a", "p"], edges) == resolve_actor_families(
        ["p", "a"], list(reversed(edges))
    )


def test_08_fingerprint_ignores_order_and_duplicate_units():
    assert family_set_fingerprint(["b", "a", "a"]) == family_set_fingerprint(["a", "b"])


def test_09_fingerprint_does_not_include_algorithm_version():
    expected = __import__("hashlib").sha256(b"a\nb").hexdigest()
    assert family_set_fingerprint(["b", "a"]) == expected
    assert FAMILY_FINGERPRINT_VERSION not in expected


def test_10_topic_is_separate_uniqueness_dimension():
    actors = cluster("a", topic="one") + cluster("a", topic="two")
    result = run(actors)
    assert len(result.proposals) == 2
    assert len({item.membership_fingerprint for item in result.proposals}) == 1
    assert {item.topic_id for item in result.proposals} == {"one", "two"}


def test_11_method_and_fingerprint_versions_are_separate_evidence():
    proposal = run(cluster("a")).proposals[0]
    assert proposal.method_version == HUB_PROPOSAL_METHOD_VERSION
    assert proposal.fingerprint_version == FAMILY_FINGERPRINT_VERSION
    assert proposal.method_version not in proposal.membership_fingerprint


def test_12_maximum_matching_finds_cardinality_not_greedy_count():
    pairs = maximum_category_matching({"f1": ["a", "b"], "f2": ["a"]})
    assert pairs == (("f1", "b"), ("f2", "a"))


def test_13_matching_is_deterministic_under_input_order():
    first = maximum_category_matching({"f2": ["b", "a"], "f1": ["a", "c"]})
    second = maximum_category_matching({"f1": ["c", "a"], "f2": ["a", "b"]})
    assert first == second


def test_14_distinct_category_count_cannot_replace_matching():
    mapping = {"f1": ["a", "b", "c", "d", "e"], "f2": ["a"], "f3": ["a"], "f4": ["a"]}
    assert len({item for values in mapping.values() for item in values}) == 5
    assert len(maximum_category_matching(mapping)) == 2


def test_15_verified_actor_is_eligible_by_default():
    assert len(run(cluster("a")).eligible_actor_ids) == 10


def test_16_imported_actor_is_excluded_by_default():
    result = run(cluster("a", status="imported"))
    assert not result.eligible_actor_ids
    assert set(result.prerequisite_exclusions.values()) == {"status_not_enabled"}


def test_17_verified_plus_imported_comparison_uses_same_snapshot():
    snapshot = DetectionSnapshot(tuple(cluster("a", status="imported")), (), (), ())
    default, comparison = compute_detection_snapshot(snapshot, HubDetectionConfig())
    assert not default.proposals
    assert len(comparison.proposals) == 1


def test_18_prerequisite_exclusions_fail_closed():
    cases = [
        ({"latitude": None}, "missing_deterministic_geography"),
        ({"longitude": None}, "missing_deterministic_geography"),
        ({"city": None}, "missing_deterministic_geography"),
        ({"state_code": None}, "missing_deterministic_geography"),
        ({"actor_category": None}, "missing_classification"),
        ({"category_type": None}, "missing_classification"),
        ({"merged": True}, "merged"),
        ({"actor_category": "aggregate"}, "aggregate"),
    ]
    for changes, reason in cases:
        item = replace(actor("a"), **changes)
        result = run([item], config=HubDetectionConfig(minimum_families=1, minimum_categories=1))
        assert result.prerequisite_exclusions["topic-1:a"] == reason


def test_19_same_topic_assignment_is_excluded_from_pool():
    item = actor("a", assigned=frozenset({"topic-1"}))
    assert run([item]).prerequisite_exclusions["topic-1:a"] == "already_assigned_same_topic"


def test_20_other_topic_assignment_does_not_exclude_actor():
    item = actor("a", assigned=frozenset({"topic-2"}))
    result = run([item], config=HubDetectionConfig(minimum_families=1, minimum_categories=1))
    assert result.eligible_actor_ids == ("a",)


def test_21_exact_ten_families_and_five_matched_categories_pass():
    proposal = run(cluster("a")).proposals[0]
    assert proposal.independent_family_count == 10
    assert proposal.matched_category_count == 5
    assert len(proposal.family_category_pairs) == 5


def test_22_nine_families_fail_threshold_without_removal_side_effect():
    result = run(cluster("a", count=9))
    assert not result.proposals and len(result.eligible_actor_ids) == 9


def test_23_four_category_matching_fails_threshold():
    result = run(cluster("a", categories=CATEGORIES[:4]))
    assert not result.proposals


def test_24_radius_boundary_is_inclusive_only_through_200():
    for miles, expected in ((200.0, 1), (201.0, 0)):
        actors = [actor("a"), actor("b", latitude=latitude_for_miles(miles), city="Beta")]
        config = HubDetectionConfig(minimum_families=2, minimum_categories=1)
        assert len(run(actors, config=config).proposals) == expected


def test_25_highest_ranked_center_failure_preserves_actors_for_later_center():
    failed = cluster("fail", count=11, categories=CATEGORIES[:4], longitude=0.0)
    passing = cluster("pass", count=10, categories=CATEGORIES, longitude=6.0)
    result = run(failed + passing)
    assert [proposal.center_city for proposal in result.proposals] == ["City pass"]
    assert set(result.eligible_actor_ids) == {item.actor_id for item in failed + passing}


def test_26_terminal_proposal_removes_cluster_then_recomputes_centers():
    result = run(cluster("a", longitude=0.0) + cluster("b", longitude=6.0))
    assert [proposal.center_city for proposal in result.proposals] == ["City a", "City b"]


def test_27_existing_fingerprint_suppresses_unchanged_family_set():
    actors = cluster("a")
    fingerprint = family_set_fingerprint(item.actor_id for item in actors)
    result = run(actors, prior=[("topic-1", fingerprint)])
    assert not result.proposals
    assert result.suppressions[0].reason == "existing_family_fingerprint"


def test_28_rejected_unchanged_family_set_remains_suppressed():
    actors = cluster("a")
    prior = [("topic-1", family_set_fingerprint(item.actor_id for item in actors))]
    assert run(actors, prior=prior).suppressions[0].family_fingerprint == prior[0][1]


def test_29_changed_family_set_may_be_reconsidered():
    old = cluster("a")
    changed = old + [actor("new", category=CATEGORIES[0])]
    prior = [("topic-1", family_set_fingerprint(item.actor_id for item in old))]
    assert len(run(changed, prior=prior).proposals) == 1


def test_30_trusted_same_topic_hub_suppresses_and_builds_assignment_plans():
    hub = TrustedHub("hub-1", "Alpha Hub", "topic-1", 0.0, 0.0, 200.0)
    result = run(cluster("a"), hubs=[hub])
    suppression = result.suppressions[0]
    assert suppression.reason == "existing_same_topic_hub"
    assert suppression.existing_hub_id == "hub-1"
    assert len(suppression.assignment_plans) == 10
    assert all(plan.assigned_hub_ids == ("hub-1",) for _, plan in suppression.assignment_plans)


def test_31_wrong_topic_hub_cannot_suppress():
    hub = TrustedHub("hub-1", "Other Hub", "topic-2", 0.0, 0.0, 200.0)
    assert len(run(cluster("a"), hubs=[hub]).proposals) == 1


def test_32_untrusted_incomplete_hub_cannot_suppress():
    hubs = [
        TrustedHub("h", "No topic", None, 0.0, 0.0, 200.0),
        TrustedHub("h", "No latitude", "topic-1", None, 0.0, 200.0),
        TrustedHub("h", "No longitude", "topic-1", 0.0, None, 200.0),
        TrustedHub("h", "No radius", "topic-1", 0.0, 0.0, None),
    ]
    for hub in hubs:
        assert len(run(cluster("a"), hubs=[hub]).proposals) == 1


def test_33_proposal_payload_stores_matching_and_independence_evidence():
    payload = run(cluster("a")).proposals[0].payload()
    assert payload["matched_category_count"] == 5
    assert len(payload["family_category_pairs"]) == 5
    assert "independent families" in payload["independence_statement"]


def test_34_member_distance_keeps_unrounded_decision_value():
    actors = cluster("a")
    actors[1] = replace(actors[1], latitude=latitude_for_miles(1.234567))
    proposal = run(actors).proposals[0]
    distance = next(item.distance_miles_raw for item in proposal.members if item.actor_id == "a-01")
    assert distance != round(distance, 2)


def test_35_runtime_defaults_match_architecture_values():
    config = HubDetectionConfig()
    assert (config.minimum_families, config.minimum_categories) == (10, 5)
    assert (config.core_radius_miles, config.radius_miles) == (50.0, 200.0)
    assert config.trigger_statuses == ("verified",)


def test_36_dry_and_live_computation_inputs_produce_identical_payloads():
    snapshot = DetectionSnapshot(tuple(cluster("a")), (), (), ())
    dry, live_candidate = compute_detection_snapshot(snapshot, HubDetectionConfig())
    assert canonical_result_json(dry) == canonical_result_json(live_candidate)


def test_37_detection_is_invariant_to_actor_and_edge_order():
    actors = cluster("a")
    shuffled = actors.copy()
    random.Random(7).shuffle(shuffled)
    assert canonical_result_json(run(actors)) == canonical_result_json(run(shuffled))


def test_38_unresolved_hierarchy_actor_is_reported_and_excluded():
    actors = cluster("a")
    edges = [FamilyEdge("a-00", "p1", "unit_of"), FamilyEdge("a-00", "p2", "operated_by")]
    result = run(actors, edges=edges)
    assert result.unresolved_hierarchy["topic-1:a-00"] == "multiple_distinct_roots"
    assert "a-00" not in result.eligible_actor_ids


def test_39_units_collapse_to_one_independent_family():
    actors = cluster("a", count=18)
    edges = [FamilyEdge(item.actor_id, "parent", "unit_of") for item in actors[:10]]
    result = run(actors, edges=edges)
    assert not result.proposals  # one parent family plus eight independent families = nine


def test_40_center_tie_break_is_alphabetical_and_stable():
    actors = cluster("z")
    actors[0] = replace(actors[0], city="Alpha")
    proposal = run(actors).proposals[0]
    assert proposal.center_city == "Alpha"


def test_41_detector_never_inserts_a_canonical_hub():
    source = (ROOT / "agents" / "hubs" / "detect.py").read_text(encoding="utf-8").upper()
    assert "INSERT INTO HUB " not in source
    assert "UPDATE HUB " not in source


def test_42_detector_delegates_membership_writes_to_approved_writer():
    source = (ROOT / "agents" / "hubs" / "detect.py").read_text(encoding="utf-8")
    assert "persist_hub_assignment_plan(" in source
    assert "INSERT INTO hub_actor" not in source
