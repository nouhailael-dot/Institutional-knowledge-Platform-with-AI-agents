"""Deterministic density-center previews for Architecture V2 hubs."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from agents.common.geography import distance_miles

HUB_CENTER_METHOD_VERSION = "density_center_v1"
ELIGIBLE_CENTER_STATUSES = frozenset({"verified", "imported"})


@dataclass(frozen=True)
class CenterMember:
    actor_id: str
    city: str
    state_code: str
    latitude: float | None
    longitude: float | None
    record_status: str
    actor_category: str | None = None
    merged: bool = False


@dataclass(frozen=True)
class CenterResult:
    city: str
    state_code: str
    latitude: float
    longitude: float
    core_member_count: int
    average_radius_distance_miles: float
    eligible_member_count: int
    method_version: str = HUB_CENTER_METHOD_VERSION


@dataclass(frozen=True)
class CenterDrift:
    shift_miles: float | None
    review_required: bool
    frozen: bool
    threshold_miles: float


def eligible_center_members(members: Iterable[CenterMember]) -> tuple[CenterMember, ...]:
    return tuple(
        member
        for member in members
        if member.record_status.casefold() in ELIGIBLE_CENTER_STATUSES
        and member.actor_category != "aggregate"
        and not member.merged
        and member.latitude is not None
        and member.longitude is not None
    )


def compute_density_center(
    members: Iterable[CenterMember],
    *,
    core_radius_miles: float = 50.0,
    radius_miles: float = 200.0,
) -> CenterResult | None:
    """Select the actor city with densest core, then lowest radius mean.

    Candidate centers are unique controlled city/state/coordinate tuples.  Ties
    are resolved by normalized state, city, latitude, then longitude.
    """
    eligible = eligible_center_members(members)
    if not eligible:
        return None
    candidates = sorted(
        {
            (m.state_code.casefold(), m.city.casefold(), float(m.latitude), float(m.longitude), m)
            for m in eligible
        },
        key=lambda row: (row[0], row[1], row[2], row[3], row[4].actor_id),
    )
    scored: list[tuple[tuple[float | str, ...], CenterResult]] = []
    seen_coordinates: set[tuple[str, str, float, float]] = set()
    for state_key, city_key, latitude, longitude, member in candidates:
        key = (state_key, city_key, latitude, longitude)
        if key in seen_coordinates:
            continue
        seen_coordinates.add(key)
        distances = [
            distance_miles(latitude, longitude, float(other.latitude), float(other.longitude))
            for other in eligible
        ]
        core_count = sum(distance <= core_radius_miles for distance in distances)
        radius_distances = [distance for distance in distances if distance <= radius_miles]
        average = sum(radius_distances) / len(radius_distances)
        result = CenterResult(
            city=member.city,
            state_code=member.state_code,
            latitude=latitude,
            longitude=longitude,
            core_member_count=core_count,
            average_radius_distance_miles=average,
            eligible_member_count=len(eligible),
        )
        score = (-core_count, average, state_key, city_key, latitude, longitude)
        scored.append((score, result))
    return min(scored, key=lambda row: row[0])[1]


def preview_center_drift(
    current_latitude: float | None,
    current_longitude: float | None,
    proposed: CenterResult | None,
    *,
    frozen: bool,
    threshold_miles: float = 25.0,
) -> CenterDrift:
    if proposed is None or current_latitude is None or current_longitude is None:
        return CenterDrift(None, False, frozen, threshold_miles)
    shift = distance_miles(
        current_latitude,
        current_longitude,
        proposed.latitude,
        proposed.longitude,
    )
    return CenterDrift(shift, frozen and shift > threshold_miles, frozen, threshold_miles)
