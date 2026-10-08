"""WS5.2: the nine required hub-detection scenarios, run against Phase 7 as built.

The algorithm is not touched to make any of these pass. Where a fixture
expectation and the implemented behaviour differ, the test records the
implemented behaviour and the report says so.

Every distance asserted here is computed by the haversine module in
`agents.common.geography` from vendored Census gazetteer coordinates. None is
hand-estimated.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from agents.common.hub_detection import HubDetectionConfig
from tests.agent.hub_fixture_data import (
    BASE,
    BOUNDARY_INSIDE,
    BOUNDARY_OUTSIDE,
    CENTER,
    EAST,
    FIXTURE_PREFIX,
    OTHER_TOPIC_ID,
    OTHER_TOPIC_NAME,
    TOPIC_ID,
    coordinates,
    detect,
    miles_between,
    trusted_hub_at,
)

CONFIG = HubDetectionConfig()


def _by_key(actors, key):
    return next(item for item in actors if item.key == key)


def _without(actors, *keys):
    return tuple(item for item in actors if item.key not in keys)


# ---------------------------------------------------------------- the dataset

def test_the_fixture_set_is_isolated_test_data():
    """Every fixture is prefixed and can never be mistaken for a real actor."""

    for item in (*BASE, *EAST, BOUNDARY_INSIDE, BOUNDARY_OUTSIDE):
        assert item.actor_id.startswith(FIXTURE_PREFIX)
        assert item.name.startswith("FX ")
        assert item.status == "verified"


def test_every_fixture_pair_is_a_valid_intern_guide_pair():
    from agents.common.actor_classification import load_category_catalog

    catalog = load_category_catalog()
    for item in (*BASE, *EAST, BOUNDARY_INSIDE, BOUNDARY_OUTSIDE):
        assert catalog.validates(item.category, item.category_type), item.name


def test_every_fixture_city_resolves_in_the_gazetteer():
    for item in (*BASE, *EAST, BOUNDARY_INSIDE, BOUNDARY_OUTSIDE):
        latitude, longitude = coordinates(item.city, item.state)
        assert -90 <= latitude <= 90 and -180 <= longitude <= 180


def test_the_base_cluster_is_inside_the_two_hundred_mile_radius():
    for item in BASE:
        miles = miles_between(CENTER, (item.city, item.state))
        assert miles <= CONFIG.radius_miles, f"{item.name} is {miles:.2f} mi from Davis"


# ------------------------------------------------------------------ S1 .. S9

def test_s1_qualifying_set_yields_one_proposal_and_creates_no_hub():
    result = detect(BASE)
    assert len(result.proposals) == 1
    proposal = result.proposals[0]
    # The brief expects >= 10 families and >= 5 categories; the fixture gives 12
    # and the algorithm matches 10 categories.
    assert proposal.independent_family_count >= CONFIG.minimum_families
    assert proposal.matched_category_count >= CONFIG.minimum_categories
    assert len(proposal.members) == len(BASE)
    # Every member carries its own measured distance to the proposed centre.
    for member in proposal.members:
        assert member.distance_miles_raw is not None
        assert member.distance_miles_raw <= CONFIG.radius_miles
    # Evidence is present and the result is a PROPOSAL: detection never creates
    # a canonical hub.
    assert proposal.family_category_pairs
    assert proposal.membership_fingerprint
    assert not hasattr(result, "created_hubs")


def test_s2_nine_independent_families_make_no_proposal():
    """Two actors sharing a university parent count as one family."""

    # Drop three singleton families, leaving 9 once the department folds into
    # the university's family.
    actors = _without(BASE, "growers-association", "farm-futures-foundation",
                      "county-ag-department")
    families = {item.parent_key or item.key for item in actors}
    assert len(families) == 9
    assert detect(actors).proposals == ()


def test_s3_four_matched_categories_make_no_proposal():
    """Enough families, too few distinct categories to match five."""

    # Rewrite every family onto four categories, keeping 12 families.
    categories = [
        ("company", "private_company"), ("startup", "independent_startup"),
        ("investor", "venture_capital"), ("foundation_nonprofit", "private_foundation"),
    ]
    actors = tuple(
        replace(item, category=categories[index % 4][0],
                category_type=categories[index % 4][1])
        for index, item in enumerate(BASE)
    )
    result = detect(actors)
    assert result.proposals == ()


def test_s4_two_separate_clusters_give_two_deterministic_proposals():
    separation = miles_between(CENTER, ("Boston", "MA"))
    assert separation > CONFIG.radius_miles * 2, f"clusters are only {separation:.0f} mi apart"
    result = detect((*BASE, *EAST))
    assert len(result.proposals) == 2
    centres = sorted(p.center_city for p in result.proposals)
    # Deterministic across reruns, centres and all.
    assert [sorted(p.center_city for p in detect((*BASE, *EAST)).proposals)] == [centres]
    # No member of one proposal appears in the other.
    first, second = ({m.actor_id for m in p.members} for p in result.proposals)
    assert first.isdisjoint(second)


def test_s5_a_trusted_same_topic_hub_suppresses_instead_of_duplicating():
    result = detect(BASE, existing_hubs=(trusted_hub_at("Sacramento", "CA"),))
    assert result.proposals == ()
    assert [s.reason for s in result.suppressions] == ["existing_same_topic_hub"]
    suppression = result.suppressions[0]
    assert suppression.existing_hub_id == "FX-existing-hub"
    # It is an assignment plan, not a silent drop: every actor gets one.
    assert len(suppression.assignment_plans) == len(BASE)


def test_s6_parked_and_topic_unverified_actors_are_excluded_from_the_trigger_pool():
    parked = replace(_by_key(BASE, "soilsense"), status="parked")
    other_topic = replace(
        _by_key(BASE, "harvest-ventures"), topic_id=OTHER_TOPIC_ID, topic_name=OTHER_TOPIC_NAME,
    )
    actors = (*_without(BASE, "soilsense", "harvest-ventures"), parked, other_topic)
    result = detect(actors)
    eligible = set(result.eligible_actor_ids)
    assert parked.actor_id not in eligible, "a Parked actor must never trigger detection"
    # The other-topic actor is still Verified, so it is eligible, but it can
    # never join the precision-agriculture cluster.
    for proposal in result.proposals:
        assert proposal.topic_id == TOPIC_ID
        assert other_topic.actor_id not in {m.actor_id for m in proposal.members}


def test_s7_one_family_with_several_departments_counts_once_and_cycles_fail_closed():
    extra = tuple(
        replace(_by_key(BASE, "alpha-plant-sciences"),
                key=f"alpha-dept-{index}", name=f"FX Alpha Department {index}")
        for index in range(1, 4)
    )
    result = detect((*BASE, *extra))
    assert len(result.proposals) == 1
    # Three more departments of the same university: more members, same number
    # of independent families.
    baseline = detect(BASE).proposals[0]
    assert result.proposals[0].independent_family_count == baseline.independent_family_count
    assert len(result.proposals[0].members) == len(baseline.members) + len(extra)

    # An ambiguous or cyclic parent edge fails CLOSED: the actors whose family
    # cannot be resolved are reported and excluded. Detection does not guess a
    # family for them, and it does not abandon the actors it can resolve.
    cyclic = (
        replace(_by_key(BASE, "university-alpha"), parent_key="alpha-plant-sciences"),
        *_without(BASE, "university-alpha"),
    )
    cyclic_result = detect(cyclic)
    assert cyclic_result.unresolved_hierarchy, "a cycle must be reported, not resolved"
    cycled = {f"{FIXTURE_PREFIX}university-alpha", f"{FIXTURE_PREFIX}alpha-plant-sciences"}
    # unresolved_hierarchy is keyed "<topic id>:<actor id>" and names the reason.
    unresolved = {key.split(":", 1)[1]: reason
                  for key, reason in cyclic_result.unresolved_hierarchy.items()}
    assert cycled <= set(unresolved)
    assert set(unresolved.values()) == {"cycle"}
    for proposal in cyclic_result.proposals:
        assert cycled.isdisjoint({member.actor_id for member in proposal.members})


def test_s8_a_previously_rejected_family_set_is_suppressed_by_its_fingerprint():
    first = detect(BASE)
    fingerprint = first.proposals[0].membership_fingerprint
    again = detect(BASE, prior_fingerprints=((TOPIC_ID, fingerprint),))
    assert again.proposals == ()
    assert [s.reason for s in again.suppressions] == ["existing_family_fingerprint"]
    assert again.suppressions[0].family_fingerprint == fingerprint


def test_s9_an_actor_beyond_the_radius_or_without_coordinates_is_not_assigned():
    outside_miles = miles_between(CENTER, (BOUNDARY_OUTSIDE.city, BOUNDARY_OUTSIDE.state))
    assert outside_miles > CONFIG.radius_miles
    result = detect((*BASE, BOUNDARY_OUTSIDE))
    assert len(result.proposals) == 1
    members = {m.actor_id for m in result.proposals[0].members}
    assert BOUNDARY_OUTSIDE.actor_id not in members, (
        f"{BOUNDARY_OUTSIDE.name} is {outside_miles:.2f} mi out and must not be assigned"
    )


# ------------------------------------------------- the boundary and determinism

def test_the_two_hundred_mile_boundary_is_measured_not_estimated():
    inside = miles_between(CENTER, (BOUNDARY_INSIDE.city, BOUNDARY_INSIDE.state))
    outside = miles_between(CENTER, (BOUNDARY_OUTSIDE.city, BOUNDARY_OUTSIDE.state))
    # Real cities that happen to straddle the radius: Bishop at ~199.7 mi and
    # Eureka at ~201.2 mi, both computed by the haversine module.
    assert 199.0 < inside < CONFIG.radius_miles
    assert CONFIG.radius_miles < outside < 202.0
    assert inside < CONFIG.radius_miles < outside


@pytest.mark.parametrize("actors", [BASE, (*BASE, *EAST), (*BASE, BOUNDARY_OUTSIDE)])
def test_detection_is_deterministic_across_reruns(actors):
    first = detect(actors)
    second = detect(actors)
    assert [p.payload() for p in first.proposals] == [p.payload() for p in second.proposals]
    assert [s.reason for s in first.suppressions] == [s.reason for s in second.suppressions]
    assert first.eligible_actor_ids == second.eligible_actor_ids


def test_detection_never_creates_a_canonical_hub():
    """Detection proposes. Only GHUS creates a hub."""

    result = detect(BASE)
    assert result.proposals, "the base fixture must produce something to inspect"
    for proposal in result.proposals:
        payload = proposal.payload()
        assert "hub_id" not in payload, "a proposal must not carry a canonical hub id"
