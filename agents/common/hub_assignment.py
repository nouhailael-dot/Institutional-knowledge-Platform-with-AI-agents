"""Deterministic Architecture V2 hub assignment decisions.

This module is deliberately pure: it evaluates the membership dimension and
geography but never writes memberships. ``agents.discovery.promote`` remains the
approved discovery writer.

**Test 1 is SECTOR** (GHUS decision, 2026-10-08). An actor belongs to a hub
because it works in that hub's sector and sits inside its radius. Architecture
V2 Sept 2.2 makes Test 1 the topic; that decision overrides it, and
docs/decisions/2026-10-08-hub-membership-keys-on-sector.md records why.

Topic is still evaluated and still recorded on every evaluation, because it is
useful evidence about what the actor was found for. It simply no longer decides.
Pass ``dimension="topic"`` to get the earlier behaviour back.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from agents.common.geography import distance_miles

HUB_ASSIGNMENT_METHOD_VERSION = "hub_assignment_v1"
ASSIGNED = "assigned"
NEEDS_REVIEW_TOPIC = "needs_review_topic"
NEEDS_REVIEW_SECTOR = "needs_review_sector"
NEEDS_REVIEW_LOCATION = "needs_review_location"
DEFAULT_DIMENSION = "sector"


@dataclass(frozen=True)
class ActorHubContext:
    actor_id: str | None
    topic_id: str | None
    latitude: float | None
    longitude: float | None
    # The sectors this actor works in. Many-to-many, as Architecture V2 Sept 5.1
    # specifies ("the sector(s) this actor fits").
    sector_codes: frozenset[str] = frozenset()


@dataclass(frozen=True)
class HubCandidate:
    hub_id: str
    name: str
    topic_id: str | None
    center_latitude: float | None
    center_longitude: float | None
    radius_miles: float = 200.0
    # The hub's primary sector. None means the hub has not been given one, and
    # it then matches nothing by sector rather than matching everything.
    sector_code: str | None = None


@dataclass(frozen=True)
class HubEvaluation:
    hub_id: str
    hub_name: str
    outcome: str
    priority: str
    # Whether the actor's topic matched the hub's. Kept, and still recorded,
    # but secondary: it no longer decides the outcome unless dimension is
    # "topic".
    topic_matched: bool
    # Whether the actor works in the hub's sector. This is Test 1.
    sector_matched: bool
    dimension: str
    location_evaluated: bool
    distance_miles: float | None
    radius_miles: float
    outside_radius: bool
    selected: bool = False
    method_version: str = HUB_ASSIGNMENT_METHOD_VERSION


@dataclass(frozen=True)
class HubAssignmentPlan:
    evaluations: tuple[HubEvaluation, ...]
    assigned_hub_ids: tuple[str, ...]
    # Hubs on the SAME dimension whose circles both contain the actor. The
    # nearest centre wins and the overlap is flagged for GHUS (Arch V2 2.2).
    overlap_hub_ids: tuple[str, ...]

    @property
    def same_topic_overlap_hub_ids(self) -> tuple[str, ...]:
        """Deprecated name kept so older callers keep working."""

        return self.overlap_hub_ids


@dataclass(frozen=True)
class LegacyMembershipAssessment:
    evaluation: HubEvaluation
    membership_preserved: bool = True
    evidence_outcome: str = "legacy_membership_preserved"
    canonical_review_kind: str | None = None


def evaluate_hub_candidate(
    actor: ActorHubContext,
    hub: HubCandidate,
    *,
    distance_fn: Callable[[float, float, float, float], float] = distance_miles,
    dimension: str = DEFAULT_DIMENSION,
) -> HubEvaluation:
    """Evaluate Test 1 before geography, and short-circuit when Test 1 fails.

    Test 1 is the sector by default. Both the sector and the topic results are
    recorded either way, so an evaluation always says what matched and what did
    not, whichever one was decisive.
    """

    if dimension not in ("sector", "topic"):
        raise ValueError(f"dimension must be 'sector' or 'topic', got {dimension!r}")
    topic_matched = bool(actor.topic_id and hub.topic_id and actor.topic_id == hub.topic_id)
    sector_matched = bool(hub.sector_code and hub.sector_code in actor.sector_codes)
    gate_passed = sector_matched if dimension == "sector" else topic_matched
    if not gate_passed:
        return HubEvaluation(
            hub_id=hub.hub_id,
            hub_name=hub.name,
            outcome=(NEEDS_REVIEW_SECTOR if dimension == "sector" else NEEDS_REVIEW_TOPIC),
            priority="low",
            topic_matched=topic_matched,
            sector_matched=sector_matched,
            dimension=dimension,
            location_evaluated=False,
            distance_miles=None,
            radius_miles=hub.radius_miles,
            outside_radius=False,
        )
    coordinates = (
        actor.latitude,
        actor.longitude,
        hub.center_latitude,
        hub.center_longitude,
    )
    if any(value is None for value in coordinates):
        return HubEvaluation(
            hub_id=hub.hub_id,
            hub_name=hub.name,
            outcome=NEEDS_REVIEW_LOCATION,
            priority="normal",
            topic_matched=topic_matched,
            sector_matched=sector_matched,
            dimension=dimension,
            location_evaluated=False,
            distance_miles=None,
            radius_miles=hub.radius_miles,
            outside_radius=False,
        )
    distance = distance_fn(*(float(value) for value in coordinates))
    outside = distance > hub.radius_miles
    return HubEvaluation(
        hub_id=hub.hub_id,
        hub_name=hub.name,
        outcome=NEEDS_REVIEW_LOCATION if outside else ASSIGNED,
        priority="normal",
        topic_matched=topic_matched,
        sector_matched=sector_matched,
        dimension=dimension,
        location_evaluated=True,
        distance_miles=distance,
        radius_miles=hub.radius_miles,
        outside_radius=outside,
    )


def build_hub_assignment_plan(
    actor: ActorHubContext,
    hubs: Iterable[HubCandidate],
    *,
    distance_fn: Callable[[float, float, float, float], float] = distance_miles,
    dimension: str = DEFAULT_DIMENSION,
) -> HubAssignmentPlan:
    """Choose the nearest hub on the same dimension, ties broken by hub id."""
    evaluations = [
        evaluate_hub_candidate(actor, hub, distance_fn=distance_fn, dimension=dimension)
        for hub in sorted(hubs, key=lambda item: item.hub_id)
    ]
    eligible = [item for item in evaluations if item.outcome == ASSIGNED]
    eligible.sort(key=lambda item: (float(item.distance_miles or 0.0), item.hub_id))
    selected_id = eligible[0].hub_id if eligible else None
    evaluations = [
        HubEvaluation(**{**item.__dict__, "selected": item.hub_id == selected_id})
        for item in evaluations
    ]
    return HubAssignmentPlan(
        evaluations=tuple(evaluations),
        assigned_hub_ids=(selected_id,) if selected_id else (),
        overlap_hub_ids=tuple(item.hub_id for item in eligible) if len(eligible) > 1 else (),
    )


def legacy_membership_assessment(
    actor: ActorHubContext,
    hub: HubCandidate,
    *,
    distance_fn: Callable[[float, float, float, float], float] = distance_miles,
    dimension: str = DEFAULT_DIMENSION,
) -> LegacyMembershipAssessment:
    """Assess an authoritative legacy membership without changing it."""
    evaluation = evaluate_hub_candidate(
        actor, hub, distance_fn=distance_fn, dimension=dimension
    )
    return LegacyMembershipAssessment(
        evaluation=evaluation,
        canonical_review_kind=(
            "hub_member_outside_radius" if evaluation.outside_radius else None
        ),
    )
