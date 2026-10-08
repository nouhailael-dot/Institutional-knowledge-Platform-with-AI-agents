"""WS5.2: the synthetic hub-detection fixture set (Appendix E).

Everything here is test data and is named with the `FX-` prefix so it can never
be confused with a real actor. Two rules govern this file:

  * The algorithm is never changed to make a fixture pass. These fixtures run
    the implemented Phase 7 detection exactly as it is: 10 independent families,
    5 matched categories by maximum bipartite matching, a 50-mile core and a
    200-mile cluster. Where a fixture and the algorithm disagree, the report
    says so and the algorithm wins.
  * No distance is ever hand-estimated. City coordinates come from the vendored
    Census gazetteer and every distance is computed by the haversine module in
    `agents.common.geography`.

Detection runs entirely in memory through `compute_detection_snapshot`, so the
fixtures need no database and no network.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache

from agents.common.geography import default_gazetteer, distance_miles
from agents.common.hub_detection import DetectionActor, HubDetectionConfig, TrustedHub
from agents.common.hub_families import FamilyEdge

FIXTURE_PREFIX = "FX-"
TOPIC_ID = "fx-topic-precision-agriculture"
TOPIC_NAME = "FX Precision Agriculture"
OTHER_TOPIC_ID = "fx-topic-irrigation-efficiency"
OTHER_TOPIC_NAME = "FX Irrigation Efficiency"

# Hub membership keys on SECTOR (GHUS decision, 2026-10-08). Topic is recorded
# on the resulting proposal as secondary evidence and never gates membership.
SECTOR = "AGRI"
OTHER_SECTOR = "MINING"


@lru_cache(maxsize=1)
def _gazetteer():
    return default_gazetteer()


@lru_cache(maxsize=128)
def coordinates(city: str, state: str) -> tuple[float, float]:
    """Gazetteer coordinates. Raises rather than guessing an unknown city."""

    found = _gazetteer().lookup(city, state)
    if not found.found or found.latitude is None or found.longitude is None:
        raise AssertionError(f"{city}, {state} is not in the Census gazetteer")
    return (float(found.latitude), float(found.longitude))


def miles_between(a: tuple[str, str], b: tuple[str, str]) -> float:
    """Haversine miles between two gazetteer cities. Never hand-estimated."""

    lat_a, lon_a = coordinates(*a)
    lat_b, lon_b = coordinates(*b)
    return distance_miles(lat_a, lon_a, lat_b, lon_b)


@dataclass(frozen=True)
class FixtureActor:
    key: str
    name: str
    category: str
    category_type: str
    city: str
    state: str
    family_note: str
    parent_key: str | None = None
    parent_relationship: str = "unit_of"
    status: str = "verified"
    topic_id: str = TOPIC_ID
    topic_name: str = TOPIC_NAME
    sector_codes: tuple[str, ...] = (SECTOR,)

    @property
    def actor_id(self) -> str:
        return f"{FIXTURE_PREFIX}{self.key}"


# ---------------------------------------------------------------------------
# Base positive fixture. Sacramento Valley, one controlled topic, 13 actors.
# Actors 1 and 2 share a family on purpose (the department is a unit of the
# university), which is what makes the family count 12 rather than 13.
# Every category and type below is a valid Intern Guide pair.
# ---------------------------------------------------------------------------
BASE: tuple[FixtureActor, ...] = (
    FixtureActor("university-alpha", "FX University Alpha", "university_academic",
                 "university_system", "Davis", "CA", "F1 root"),
    FixtureActor("alpha-plant-sciences", "FX Alpha Dept. of Plant Sciences",
                 "university_academic", "academic_department", "Davis", "CA",
                 "F1, same family as the university", parent_key="university-alpha"),
    FixtureActor("valley-crop-institute", "FX Valley Crop Institute", "research_center",
                 "independent_institute", "Sacramento", "CA", "F2"),
    FixtureActor("delta-field-station", "FX Delta Field Station", "applied_facility",
                 "nonprofit_operated", "Dixon", "CA", "F3"),
    FixtureActor("agricorp", "FX AgriCorp", "company", "private_company",
                 "Woodland", "CA", "F4"),
    FixtureActor("irrigation-systems", "FX Irrigation Systems", "company", "small_mid_size",
                 "Elk Grove", "CA", "F5"),
    FixtureActor("soilsense", "FX SoilSense", "startup", "independent_startup",
                 "Sacramento", "CA", "F6"),
    # Spinout of, NOT a parent: the Guide is explicit that a spinout keeps its
    # own family, so this actor must count as an independent family.
    FixtureActor("seedgen", "FX SeedGen", "startup", "university_spinout", "Davis", "CA",
                 "F7, spinout of the university but its own family"),
    FixtureActor("ag-accelerator", "FX Ag Accelerator", "innovation_platform", "accelerator",
                 "Sacramento", "CA", "F8"),
    FixtureActor("harvest-ventures", "FX Harvest Ventures", "investor", "venture_capital",
                 "Roseville", "CA", "F9"),
    FixtureActor("county-ag-department", "FX County Ag Department", "government",
                 "local_municipal", "Woodland", "CA", "F10"),
    FixtureActor("farm-futures-foundation", "FX Farm Futures Foundation",
                 "foundation_nonprofit", "private_foundation", "Sacramento", "CA", "F11"),
    FixtureActor("growers-association", "FX Growers Association", "association_network",
                 "trade_association", "Stockton", "CA", "F12"),
)

# A second, geographically separate cluster for S4. Greater Boston, same topic,
# far enough from Sacramento that the two can never merge into one proposal.
EAST: tuple[FixtureActor, ...] = (
    FixtureActor("bay-state-university", "FX Bay State University", "university_academic",
                 "university_system", "Boston", "MA", "E1 root"),
    FixtureActor("charles-crop-institute", "FX Charles Crop Institute", "research_center",
                 "independent_institute", "Cambridge", "MA", "E2"),
    FixtureActor("bay-field-station", "FX Bay Field Station", "applied_facility",
                 "nonprofit_operated", "Worcester", "MA", "E3"),
    FixtureActor("harbor-agri", "FX Harbor Agri", "company", "private_company",
                 "Providence", "RI", "E4"),
    FixtureActor("mill-irrigation", "FX Mill Irrigation", "company", "small_mid_size",
                 "Lowell", "MA", "E5"),
    FixtureActor("rootdata", "FX RootData", "startup", "independent_startup",
                 "Cambridge", "MA", "E6"),
    FixtureActor("greenline-bio", "FX Greenline Bio", "startup", "corporate_spinout",
                 "Springfield", "MA", "E7"),
    FixtureActor("bay-accelerator", "FX Bay Accelerator", "innovation_platform", "accelerator",
                 "Boston", "MA", "E8"),
    FixtureActor("harbor-ventures", "FX Harbor Ventures", "investor", "venture_capital",
                 "Boston", "MA", "E9"),
    FixtureActor("county-extension-office", "FX County Extension Office", "government",
                 "local_municipal", "Worcester", "MA", "E10"),
    FixtureActor("coastal-foundation", "FX Coastal Foundation", "foundation_nonprofit",
                 "private_foundation", "Providence", "RI", "E11"),
    FixtureActor("northeast-growers", "FX Northeast Growers", "association_network",
                 "trade_association", "Portland", "ME", "E12"),
)

# The 200-mile boundary pair, both real gazetteer cities. Bishop is 199.7 miles
# from Davis and Eureka is 201.2, both measured by the haversine module.
BOUNDARY_INSIDE = FixtureActor(
    "boundary-inside", "FX Boundary Inside", "hospital_clinical", "independent_standalone",
    "Bishop", "CA", "B1, inside the 200-mile cluster",
)
BOUNDARY_OUTSIDE = FixtureActor(
    "boundary-outside", "FX Boundary Outside", "hospital_clinical", "independent_standalone",
    "Eureka", "CA", "B2, outside the 200-mile cluster",
)

CENTER = ("Davis", "CA")


def build_snapshot(actors):
    """Turn fixture actors into the detection snapshot the algorithm consumes."""

    from agents.hubs.detect import DetectionSnapshot

    detection_actors = []
    edges = []
    for item in actors:
        latitude, longitude = coordinates(item.city, item.state)
        detection_actors.append(DetectionActor(
            actor_id=item.actor_id,
            name=item.name,
            topic_id=item.topic_id,
            topic_name=item.topic_name,
            city=item.city,
            state_code=item.state,
            latitude=latitude,
            longitude=longitude,
            record_status=item.status,
            actor_category=item.category,
            category_type=item.category_type,
            sector_codes=frozenset(item.sector_codes),
        ))
        if item.parent_key:
            edges.append(FamilyEdge(
                item.actor_id, f"{FIXTURE_PREFIX}{item.parent_key}", item.parent_relationship,
            ))
    return DetectionSnapshot(
        actors=tuple(detection_actors),
        edges=tuple(edges),
        existing_hubs=(),
        prior_fingerprints=(),
    )


def detect(actors, *, existing_hubs=(), prior_fingerprints=(), config=None):
    """Run the implemented Phase 7 detection, unmodified."""

    from agents.hubs.detect import compute_detection_snapshot

    snapshot = build_snapshot(actors)
    snapshot = replace(
        snapshot,
        existing_hubs=tuple(existing_hubs),
        prior_fingerprints=tuple(prior_fingerprints),
    )
    result, _comparison = compute_detection_snapshot(
        snapshot, config or HubDetectionConfig()
    )
    return result


def trusted_hub_at(city: str, state: str, *, hub_id="FX-existing-hub", topic_id=TOPIC_ID,
                   sector_code=SECTOR, radius_miles=200.0) -> TrustedHub:
    latitude, longitude = coordinates(city, state)
    return TrustedHub(
        hub_id=hub_id, name=f"FX Existing Hub ({city})", topic_id=topic_id,
        center_latitude=latitude, center_longitude=longitude, radius_miles=radius_miles,
        sector_code=sector_code,
    )
