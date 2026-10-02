"""Pure deterministic Architecture V2 new-hub detection."""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field

from agents.common.geography import distance_miles
from agents.common.hub_assignment import (
    ActorHubContext,
    HubAssignmentPlan,
    HubCandidate,
    build_hub_assignment_plan,
)
from agents.common.hub_families import FamilyEdge, resolve_actor_families

HUB_PROPOSAL_METHOD_VERSION = "hub_proposal_v1"
FAMILY_FINGERPRINT_VERSION = "hub_family_set_v1"


@dataclass(frozen=True)
class HubDetectionConfig:
    trigger_statuses: tuple[str, ...] = ("verified",)
    minimum_families: int = 10
    minimum_categories: int = 5
    core_radius_miles: float = 50.0
    radius_miles: float = 200.0
    method_version: str = HUB_PROPOSAL_METHOD_VERSION
    fingerprint_version: str = FAMILY_FINGERPRINT_VERSION


@dataclass(frozen=True)
class DetectionActor:
    actor_id: str
    name: str
    topic_id: str
    topic_name: str
    city: str | None
    state_code: str | None
    latitude: float | None
    longitude: float | None
    record_status: str
    actor_category: str | None
    category_type: str | None
    assigned_topic_ids: frozenset[str] = field(default_factory=frozenset)
    merged: bool = False


@dataclass(frozen=True)
class TrustedHub:
    hub_id: str
    name: str
    topic_id: str | None
    center_latitude: float | None
    center_longitude: float | None
    radius_miles: float | None


@dataclass(frozen=True)
class ProposalMember:
    actor_id: str
    actor_category: str
    category_type: str
    family_id: str
    distance_miles_raw: float


@dataclass(frozen=True)
class HubProposalCandidate:
    topic_id: str
    topic_name: str
    center_city: str
    center_state_code: str
    center_latitude: float
    center_longitude: float
    radius_miles: float
    core_radius_miles: float
    suggested_name: str
    members: tuple[ProposalMember, ...]
    independent_family_count: int
    matched_category_count: int
    family_category_pairs: tuple[tuple[str, str], ...]
    independence_statement: str
    membership_fingerprint: str
    fingerprint_version: str = FAMILY_FINGERPRINT_VERSION
    method_version: str = HUB_PROPOSAL_METHOD_VERSION

    def payload(self) -> dict[str, object]:
        value = asdict(self)
        value["members"] = [asdict(member) for member in self.members]
        value["family_category_pairs"] = [list(pair) for pair in self.family_category_pairs]
        return value


@dataclass(frozen=True)
class HubSuppression:
    reason: str
    topic_id: str
    center_city: str
    actor_ids: tuple[str, ...]
    family_fingerprint: str | None = None
    existing_hub_id: str | None = None
    assignment_plans: tuple[tuple[str, HubAssignmentPlan], ...] = ()


@dataclass(frozen=True)
class HubDetectionResult:
    proposals: tuple[HubProposalCandidate, ...]
    suppressions: tuple[HubSuppression, ...]
    prerequisite_exclusions: dict[str, str]
    unresolved_hierarchy: dict[str, str]
    eligible_actor_ids: tuple[str, ...]


def family_set_fingerprint(family_ids: Iterable[str]) -> str:
    canonical = "\n".join(sorted({str(value) for value in family_ids}))
    return hashlib.sha256(canonical.encode()).hexdigest()


def maximum_category_matching(
    family_categories: Mapping[str, Iterable[str]],
) -> tuple[tuple[str, str], ...]:
    """Return a deterministic maximum-cardinality family/category matching."""
    adjacency = {
        family: tuple(sorted({category for category in categories if category}))
        for family, categories in sorted(family_categories.items())
    }
    category_owner: dict[str, str] = {}

    def augment(family: str, seen: set[str]) -> bool:
        for category in adjacency.get(family, ()):
            if category in seen:
                continue
            seen.add(category)
            owner = category_owner.get(category)
            if owner is None or augment(owner, seen):
                category_owner[category] = family
                return True
        return False

    for family in adjacency:
        augment(family, set())
    return tuple(sorted((family, category) for category, family in category_owner.items()))


def detect_new_hubs(
    actors: Iterable[DetectionActor],
    edges: Iterable[FamilyEdge],
    existing_hubs: Iterable[TrustedHub],
    prior_fingerprints: Iterable[tuple[str, str]],
    config: HubDetectionConfig | None = None,
) -> HubDetectionResult:
    config = config or HubDetectionConfig()
    actors = tuple(sorted(actors, key=lambda item: (item.topic_id, item.actor_id)))
    edge_rows = tuple(edges)
    hubs = tuple(existing_hubs)
    prior = {(str(topic), str(fingerprint)) for topic, fingerprint in prior_fingerprints}
    proposals: list[HubProposalCandidate] = []
    suppressions: list[HubSuppression] = []
    prerequisites: dict[str, str] = {}
    unresolved: dict[str, str] = {}
    eligible_ids: list[str] = []

    topics = sorted({actor.topic_id for actor in actors})
    for topic_id in topics:
        topic_actors = [item for item in actors if item.topic_id == topic_id]
        eligible: list[DetectionActor] = []
        for actor in topic_actors:
            reason = _eligibility_exclusion(actor, config)
            if reason:
                prerequisites[f"{topic_id}:{actor.actor_id}"] = reason
            else:
                eligible.append(actor)
        resolution = resolve_actor_families((actor.actor_id for actor in eligible), edge_rows)
        for actor_id, reason in resolution.unresolved.items():
            unresolved[f"{topic_id}:{actor_id}"] = reason
        eligible = [actor for actor in eligible if actor.actor_id in resolution.family_by_actor]
        eligible_ids.extend(actor.actor_id for actor in eligible)
        topic_name = eligible[0].topic_name if eligible else next(
            (actor.topic_name for actor in topic_actors), topic_id
        )
        topic_hubs = tuple(
            candidate
            for candidate in hubs
            if candidate.topic_id == topic_id
            and candidate.center_latitude is not None
            and candidate.center_longitude is not None
            and candidate.radius_miles is not None
            and candidate.radius_miles > 0
        )
        topic_proposals, topic_suppressions = _detect_topic(
            eligible,
            resolution.family_by_actor,
            topic_id,
            topic_name,
            topic_hubs,
            prior,
            config,
        )
        proposals.extend(topic_proposals)
        suppressions.extend(topic_suppressions)

    return HubDetectionResult(
        proposals=tuple(proposals),
        suppressions=tuple(suppressions),
        prerequisite_exclusions=dict(sorted(prerequisites.items())),
        unresolved_hierarchy=dict(sorted(unresolved.items())),
        eligible_actor_ids=tuple(sorted(eligible_ids)),
    )


def _eligibility_exclusion(actor: DetectionActor, config: HubDetectionConfig) -> str | None:
    if actor.record_status.casefold() not in {value.casefold() for value in config.trigger_statuses}:
        return "status_not_enabled"
    if actor.topic_id in actor.assigned_topic_ids:
        return "already_assigned_same_topic"
    if actor.merged:
        return "merged"
    if str(actor.actor_category).casefold() == "aggregate":
        return "aggregate"
    if actor.latitude is None or actor.longitude is None or not actor.city or not actor.state_code:
        return "missing_deterministic_geography"
    if not actor.actor_category or not actor.category_type:
        return "missing_classification"
    return None


def _detect_topic(
    actors: list[DetectionActor],
    family_by_actor: Mapping[str, str],
    topic_id: str,
    topic_name: str,
    hubs: tuple[TrustedHub, ...],
    prior: set[tuple[str, str]],
    config: HubDetectionConfig,
) -> tuple[list[HubProposalCandidate], list[HubSuppression]]:
    working = {actor.actor_id: actor for actor in actors}
    proposals: list[HubProposalCandidate] = []
    suppressions: list[HubSuppression] = []
    while working:
        ranked = _rank_centers(tuple(working.values()), family_by_actor, config)
        terminal = False
        for center in ranked:
            cluster = tuple(
                actor
                for actor in sorted(working.values(), key=lambda item: item.actor_id)
                if _distance_to(center, actor) <= config.radius_miles
            )
            if not cluster:
                continue
            family_ids = {family_by_actor[actor.actor_id] for actor in cluster}
            fingerprint = family_set_fingerprint(family_ids)
            covering = _covering_hub(center, hubs)
            if covering is not None:
                plans = tuple(
                    (
                        actor.actor_id,
                        build_hub_assignment_plan(
                            ActorHubContext(
                                actor.actor_id,
                                actor.topic_id,
                                actor.latitude,
                                actor.longitude,
                            ),
                            [
                                HubCandidate(
                                    covering.hub_id,
                                    covering.name,
                                    covering.topic_id,
                                    covering.center_latitude,
                                    covering.center_longitude,
                                    float(covering.radius_miles),
                                )
                            ],
                        ),
                    )
                    for actor in cluster
                )
                suppressions.append(
                    HubSuppression(
                        "existing_same_topic_hub",
                        topic_id,
                        center.city,
                        tuple(actor.actor_id for actor in cluster),
                        fingerprint,
                        covering.hub_id,
                        plans,
                    )
                )
                _remove_cluster(working, cluster)
                terminal = True
                break

            family_categories: dict[str, set[str]] = {}
            for actor in cluster:
                family_categories.setdefault(family_by_actor[actor.actor_id], set()).add(
                    str(actor.actor_category)
                )
            matching = maximum_category_matching(family_categories)
            if len(family_ids) < config.minimum_families or len(matching) < config.minimum_categories:
                continue
            if (topic_id, fingerprint) in prior:
                suppressions.append(
                    HubSuppression(
                        "existing_family_fingerprint",
                        topic_id,
                        center.city,
                        tuple(actor.actor_id for actor in cluster),
                        fingerprint,
                    )
                )
                _remove_cluster(working, cluster)
                terminal = True
                break
            members = tuple(
                ProposalMember(
                    actor.actor_id,
                    str(actor.actor_category),
                    str(actor.category_type),
                    family_by_actor[actor.actor_id],
                    _distance_to(center, actor),
                )
                for actor in cluster
            )
            statement = (
                f"{len(family_ids)} independent families from {len(matching)} matched "
                f"categories are on {topic_name}, concentrated around {center.city}, "
                f"with every proposed member within {config.radius_miles:g} miles."
            )
            proposals.append(
                HubProposalCandidate(
                    topic_id=topic_id,
                    topic_name=topic_name,
                    center_city=center.city,
                    center_state_code=center.state_code,
                    center_latitude=center.latitude,
                    center_longitude=center.longitude,
                    radius_miles=config.radius_miles,
                    core_radius_miles=config.core_radius_miles,
                    suggested_name=f"{center.city} {topic_name} Hub",
                    members=members,
                    independent_family_count=len(family_ids),
                    matched_category_count=len(matching),
                    family_category_pairs=matching,
                    independence_statement=statement,
                    membership_fingerprint=fingerprint,
                    fingerprint_version=config.fingerprint_version,
                    method_version=config.method_version,
                )
            )
            prior.add((topic_id, fingerprint))
            _remove_cluster(working, cluster)
            terminal = True
            break
        if not terminal:
            break
    return proposals, suppressions


@dataclass(frozen=True)
class _Center:
    city: str
    state_code: str
    latitude: float
    longitude: float
    family_core_count: int
    mean_radius_distance: float


def _rank_centers(
    actors: tuple[DetectionActor, ...],
    family_by_actor: Mapping[str, str],
    config: HubDetectionConfig,
) -> tuple[_Center, ...]:
    candidates: dict[tuple[str, str, float, float], DetectionActor] = {}
    for actor in actors:
        key = (
            _normalize_city(str(actor.city)),
            str(actor.state_code).casefold(),
            float(actor.latitude),
            float(actor.longitude),
        )
        candidates.setdefault(key, actor)
    scored: list[_Center] = []
    for key, representative in candidates.items():
        distances = [
            (
                actor,
                distance_miles(
                    float(representative.latitude),
                    float(representative.longitude),
                    float(actor.latitude),
                    float(actor.longitude),
                ),
            )
            for actor in actors
        ]
        core_families = {
            family_by_actor[actor.actor_id]
            for actor, distance in distances
            if distance <= config.core_radius_miles
        }
        radius_distances = [distance for _, distance in distances if distance <= config.radius_miles]
        mean_distance = sum(radius_distances) / len(radius_distances) if radius_distances else math.inf
        scored.append(
            _Center(
                str(representative.city),
                str(representative.state_code),
                float(representative.latitude),
                float(representative.longitude),
                len(core_families),
                mean_distance,
            )
        )
    return tuple(
        sorted(
            scored,
            key=lambda value: (
                -value.family_core_count,
                value.mean_radius_distance,
                _normalize_city(value.city),
                value.state_code.casefold(),
                value.latitude,
                value.longitude,
            ),
        )
    )


def _normalize_city(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    return " ".join("".join(char for char in text if not unicodedata.combining(char)).casefold().split())


def _distance_to(center: _Center, actor: DetectionActor) -> float:
    return distance_miles(
        center.latitude,
        center.longitude,
        float(actor.latitude),
        float(actor.longitude),
    )


def _covering_hub(center: _Center, hubs: Iterable[TrustedHub]) -> TrustedHub | None:
    covering = [
        hub
        for hub in hubs
        if distance_miles(
            center.latitude,
            center.longitude,
            float(hub.center_latitude),
            float(hub.center_longitude),
        )
        <= float(hub.radius_miles)
    ]
    return min(covering, key=lambda hub: hub.hub_id) if covering else None


def _remove_cluster(working: dict[str, DetectionActor], cluster: Iterable[DetectionActor]) -> None:
    for actor in cluster:
        working.pop(actor.actor_id, None)


def canonical_result_json(result: HubDetectionResult) -> str:
    """Stable representation used by parity and order-invariance tests."""
    payload = {
        "proposals": [proposal.payload() for proposal in result.proposals],
        "suppressions": [asdict(value) for value in result.suppressions],
        "prerequisite_exclusions": result.prerequisite_exclusions,
        "unresolved_hierarchy": result.unresolved_hierarchy,
        "eligible_actor_ids": result.eligible_actor_ids,
    }
    return json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
