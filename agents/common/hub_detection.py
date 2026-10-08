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
    # Which dimension a hub is about. "sector" is the GHUS decision of
    # 2026-10-08: an actor joins a hub because it works in the hub's SECTOR,
    # with topic recorded as secondary evidence on the proposal. "topic" is the
    # earlier behaviour, kept so the change is reversible without a code edit
    # and so both can be proved side by side in tests.
    cluster_dimension: str = "sector"

    def __post_init__(self) -> None:
        if self.cluster_dimension not in ("sector", "topic"):
            raise ValueError(
                f"cluster_dimension must be 'sector' or 'topic', got {self.cluster_dimension!r}"
            )


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
    # Sector is the dimension hub membership is decided on (GHUS decision,
    # 2026-10-08). An actor may work in several sectors, so this is a set; the
    # actor takes part in the clustering of each one. Topic above stays, as the
    # secondary signal recorded on the resulting proposal.
    sector_codes: frozenset[str] = field(default_factory=frozenset)
    assigned_sector_codes: frozenset[str] = field(default_factory=frozenset)

    def dimension_keys(self, dimension: str) -> tuple[str, ...]:
        """The partitions this actor belongs to, in deterministic order."""

        if dimension == "sector":
            return tuple(sorted(self.sector_codes))
        return (self.topic_id,)


@dataclass(frozen=True)
class TrustedHub:
    hub_id: str
    name: str
    topic_id: str | None
    center_latitude: float | None
    center_longitude: float | None
    radius_miles: float | None
    # A trusted hub answers for one primary sector. Left None on a hub that has
    # not been given one yet, which simply means it covers nothing by sector.
    sector_code: str | None = None

    def dimension_key(self, dimension: str) -> str | None:
        return self.sector_code if dimension == "sector" else self.topic_id


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
    # The dimension this proposal was clustered on, and its value. With the
    # 2026-10-08 decision these carry the sector; topic_id/topic_name above then
    # describe the cluster's dominant topic, which is secondary evidence.
    dimension: str
    dimension_key: str
    # Every topic the members carry, with how many carry it, most common first.
    # Secondary signal: it explains what the cluster is actually working on
    # without ever having gated who is in it.
    topic_mix: tuple[tuple[str, int], ...]
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
    dimension: str
    dimension_key: str
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
    dimension = config.cluster_dimension
    actors = tuple(sorted(actors, key=lambda item: (item.topic_id, item.actor_id)))
    edge_rows = tuple(edges)
    hubs = tuple(existing_hubs)
    prior = {(str(key), str(fingerprint)) for key, fingerprint in prior_fingerprints}
    proposals: list[HubProposalCandidate] = []
    suppressions: list[HubSuppression] = []
    prerequisites: dict[str, str] = {}
    unresolved: dict[str, str] = {}
    eligible_ids: list[str] = []

    # One partition per value of the configured dimension. Under the sector
    # rule an actor working in several sectors takes part in each one's
    # clustering, which is what a many-to-many sector tag has to mean.
    keys = sorted({key for actor in actors for key in actor.dimension_keys(dimension)})
    for key in keys:
        partition = [item for item in actors if key in item.dimension_keys(dimension)]
        eligible: list[DetectionActor] = []
        for actor in partition:
            reason = _eligibility_exclusion(actor, config, key)
            if reason:
                prerequisites[f"{key}:{actor.actor_id}"] = reason
            else:
                eligible.append(actor)
        resolution = resolve_actor_families((actor.actor_id for actor in eligible), edge_rows)
        for actor_id, reason in resolution.unresolved.items():
            unresolved[f"{key}:{actor_id}"] = reason
        eligible = [actor for actor in eligible if actor.actor_id in resolution.family_by_actor]
        eligible_ids.extend(actor.actor_id for actor in eligible)
        covering_hubs = tuple(
            candidate
            for candidate in hubs
            if candidate.dimension_key(dimension) == key
            and candidate.center_latitude is not None
            and candidate.center_longitude is not None
            and candidate.radius_miles is not None
            and candidate.radius_miles > 0
        )
        partition_proposals, partition_suppressions = _detect_partition(
            eligible,
            resolution.family_by_actor,
            dimension,
            key,
            covering_hubs,
            prior,
            config,
        )
        proposals.extend(partition_proposals)
        suppressions.extend(partition_suppressions)

    return HubDetectionResult(
        proposals=tuple(proposals),
        suppressions=tuple(suppressions),
        prerequisite_exclusions=dict(sorted(prerequisites.items())),
        unresolved_hierarchy=dict(sorted(unresolved.items())),
        eligible_actor_ids=tuple(sorted(eligible_ids)),
    )


def _eligibility_exclusion(
    actor: DetectionActor, config: HubDetectionConfig, key: str | None = None
) -> str | None:
    if actor.record_status.casefold() not in {value.casefold() for value in config.trigger_statuses}:
        return "status_not_enabled"
    if config.cluster_dimension == "sector":
        if (key or "") in actor.assigned_sector_codes:
            return "already_assigned_same_sector"
    elif actor.topic_id in actor.assigned_topic_ids:
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


def _dominant_topic(cluster: tuple[DetectionActor, ...]) -> tuple[str, str]:
    """The cluster's most common (topic_id, topic_name). Secondary evidence.

    Ties break alphabetically so the result is deterministic.
    """

    counts: dict[tuple[str, str], int] = {}
    for actor in cluster:
        pair = (str(actor.topic_id or ""), str(actor.topic_name or ""))
        counts[pair] = counts.get(pair, 0) + 1
    if not counts:
        return ("", "")
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _topic_mix(cluster: tuple[DetectionActor, ...]) -> tuple[tuple[str, int], ...]:
    """Which topics the members carry, most common first, then alphabetical.

    Secondary evidence only. It describes what a cluster is working on; it never
    decided who is in the cluster.
    """

    counts: dict[str, int] = {}
    for actor in cluster:
        name = str(actor.topic_name or actor.topic_id or "")
        if name:
            counts[name] = counts.get(name, 0) + 1
    return tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _detect_partition(
    actors: list[DetectionActor],
    family_by_actor: Mapping[str, str],
    dimension: str,
    key: str,
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
                        reason=("existing_same_sector_hub" if dimension == "sector"
                                else "existing_same_topic_hub"),
                        topic_id=_dominant_topic(cluster)[0],
                        dimension=dimension,
                        dimension_key=key,
                        center_city=center.city,
                        actor_ids=tuple(actor.actor_id for actor in cluster),
                        family_fingerprint=fingerprint,
                        existing_hub_id=covering.hub_id,
                        assignment_plans=plans,
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
            if (key, fingerprint) in prior:
                suppressions.append(
                    HubSuppression(
                        reason="existing_family_fingerprint",
                        topic_id=_dominant_topic(cluster)[0],
                        dimension=dimension,
                        dimension_key=key,
                        center_city=center.city,
                        actor_ids=tuple(actor.actor_id for actor in cluster),
                        family_fingerprint=fingerprint,
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
            topic_id, topic_name = _dominant_topic(cluster)
            mix = _topic_mix(cluster)
            label = key if dimension == "sector" else topic_name
            secondary = (
                f" Its most common topic is {mix[0][0]} ({mix[0][1]} of {len(cluster)} members)."
                if dimension == "sector" and mix else ""
            )
            statement = (
                f"{len(family_ids)} independent families from {len(matching)} matched "
                f"categories work in {label}, concentrated around {center.city}, "
                f"with every proposed member within {config.radius_miles:g} miles."
                f"{secondary}"
            )
            proposals.append(
                HubProposalCandidate(
                    topic_id=topic_id,
                    topic_name=topic_name,
                    dimension=dimension,
                    dimension_key=key,
                    topic_mix=mix,
                    center_city=center.city,
                    center_state_code=center.state_code,
                    center_latitude=center.latitude,
                    center_longitude=center.longitude,
                    radius_miles=config.radius_miles,
                    core_radius_miles=config.core_radius_miles,
                    suggested_name=f"{center.city} {label} Hub",
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
            prior.add((key, fingerprint))
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
