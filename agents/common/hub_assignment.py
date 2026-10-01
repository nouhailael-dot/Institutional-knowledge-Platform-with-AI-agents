"""Deterministic Architecture V2 hub assignment decisions.

This module is deliberately pure: it evaluates controlled topic and geography
inputs but never writes memberships.  ``agents.discovery.promote`` remains the
approved discovery writer.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from agents.common.geography import distance_miles

HUB_ASSIGNMENT_METHOD_VERSION = "hub_assignment_v1"
ASSIGNED = "assigned"
NEEDS_REVIEW_TOPIC = "needs_review_topic"
NEEDS_REVIEW_LOCATION = "needs_review_location"


@dataclass(frozen=True)
class ActorHubContext:
    actor_id: str | None
    topic_id: str | None
    latitude: float | None
    longitude: float | None


@dataclass(frozen=True)
class HubCandidate:
    hub_id: str
    name: str
    topic_id: str | None
    center_latitude: float | None
    center_longitude: float | None
    radius_miles: float = 200.0


@dataclass(frozen=True)
class HubEvaluation:
    hub_id: str
    hub_name: str
    outcome: str
    priority: str
    topic_matched: bool
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
    same_topic_overlap_hub_ids: tuple[str, ...]


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
) -> HubEvaluation:
    """Evaluate topic before geography and short-circuit on topic failure."""
    actor_topic_id = actor.topic_id
    hub_topic_id = hub.topic_id
    topic_matched = bool(actor_topic_id and hub_topic_id and actor_topic_id == hub_topic_id)
    if not topic_matched:
        return HubEvaluation(
            hub_id=hub.hub_id,
            hub_name=hub.name,
            outcome=NEEDS_REVIEW_TOPIC,
            priority="low",
            topic_matched=False,
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
            topic_matched=True,
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
        topic_matched=True,
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
) -> HubAssignmentPlan:
    """Choose one nearest same-topic hub, with stable hub-id tie breaking."""
    evaluations = [
        evaluate_hub_candidate(actor, hub, distance_fn=distance_fn)
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
        same_topic_overlap_hub_ids=tuple(item.hub_id for item in eligible) if len(eligible) > 1 else (),
    )


def legacy_membership_assessment(
    actor: ActorHubContext,
    hub: HubCandidate,
    *,
    distance_fn: Callable[[float, float, float, float], float] = distance_miles,
) -> LegacyMembershipAssessment:
    """Assess an authoritative legacy membership without changing it."""
    evaluation = evaluate_hub_candidate(actor, hub, distance_fn=distance_fn)
    return LegacyMembershipAssessment(
        evaluation=evaluation,
        canonical_review_kind=(
            "hub_member_outside_radius" if evaluation.outside_radius else None
        ),
    )
