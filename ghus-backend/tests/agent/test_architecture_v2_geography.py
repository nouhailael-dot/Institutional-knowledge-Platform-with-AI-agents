from __future__ import annotations

import math

import pytest

from agents.common.geography import (
    GAZETTEER_SHA256,
    REGION_STATES,
    STATE_TO_REGION,
    CensusPlacesGazetteer,
    GazetteerPlace,
    default_gazetteer,
    distance_miles,
    normalize_city,
    normalize_state,
    prepare_actor_geography,
    region_for_state,
)


def test_region_partition_all_states_and_dc():
    assert len(REGION_STATES) == 7
    assert len(STATE_TO_REGION) == 51
    assert set().union(*map(set, REGION_STATES.values())) == set(STATE_TO_REGION)
    assert sum(len(states) for states in REGION_STATES.values()) == 51


@pytest.mark.parametrize(
    ("region", "states"),
    [
        ("northeast", {"CT", "ME", "MA", "NH", "NY", "RI", "VT"}),
        ("mid_atlantic", {"DE", "MD", "NJ", "PA", "VA", "WV", "DC"}),
        ("southeast", {"AL", "FL", "GA", "KY", "MS", "NC", "SC", "TN"}),
        (
            "midwest_great_lakes",
            {"IL", "IN", "IA", "KS", "MI", "MN", "MO", "NE", "ND", "OH", "SD", "WI"},
        ),
        ("south_central_texas_gulf", {"AR", "LA", "OK", "TX"}),
        ("mountain_west", {"AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY"}),
        ("west_coast_pacific", {"AK", "CA", "HI", "OR", "WA"}),
    ],
)
def test_fixed_region_memberships(region, states):
    assert set(REGION_STATES[region]) == states


@pytest.mark.parametrize(
    ("value", "code", "region"),
    [
        ("DC", "DC", "mid_atlantic"),
        ("D.C.", "DC", "mid_atlantic"),
        ("District of Columbia", "DC", "mid_atlantic"),
        ("Washington, DC", "DC", "mid_atlantic"),
        ("Washington State", "WA", "west_coast_pacific"),
        ("Washington", "WA", "west_coast_pacific"),
    ],
)
def test_dc_is_not_washington_state(value, code, region):
    assert normalize_state(value) == code
    assert region_for_state(value) == region


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("St. Louis city", "Saint Louis"),
        ("Ft Worth", "Fort Worth city"),
        ("New York City", "New York"),
        ("Coeur d'Alene", "coeur d alene city"),
    ],
)
def test_city_normalization_variants(left, right):
    assert normalize_city(left) == normalize_city(right)


def test_vendored_gazetteer_checksum_coverage_and_known_lookups():
    gazetteer = default_gazetteer()
    assert len(GAZETTEER_SHA256) == 64
    assert len(gazetteer.places) > 30_000
    assert {place.state_code for place in gazetteer.places} == set(STATE_TO_REGION)

    boston = gazetteer.lookup("Boston", "Massachusetts")
    new_york = gazetteer.lookup("New York City", "NY")
    sacramento = gazetteer.lookup("Sacramento city", "CA")
    san_francisco = gazetteer.lookup("San Francisco", "California")
    assert all(result.found for result in (boston, new_york, sacramento, san_francisco))

    assert boston.matched_place_name == "Boston city"
    assert new_york.matched_place_name == "New York city"
    assert sacramento.matched_place_name == "Sacramento city"
    assert san_francisco.matched_place_name == "San Francisco city"


def test_haversine_known_city_distances_in_miles():
    # Conventional municipal reference points are used here so the distance
    # contract is independent of Census boundary centroids (San Francisco's
    # Census internal point includes its offshore islands).
    boston_new_york = distance_miles(42.3601, -71.0589, 40.7128, -74.0060)
    sacramento_san_francisco = distance_miles(38.5816, -121.4944, 37.7749, -122.4194)
    assert boston_new_york == pytest.approx(190, rel=0.02)
    assert sacramento_san_francisco == pytest.approx(75, rel=0.02)


def test_ambiguous_city_is_not_guessed():
    gazetteer = CensusPlacesGazetteer(
        [
            GazetteerPlace("1", "CA", "Example city", "example", 1.0, 2.0, "", "A"),
            GazetteerPlace("2", "CA", "Example CDP", "example", 3.0, 4.0, "", "S"),
        ]
    )
    result = gazetteer.lookup("Example", "CA")
    assert result.state == "not_found"
    assert result.reason == "ambiguous_city"
    assert result.latitude is None
    assert result.longitude is None


def test_region_and_coordinates_are_derived_never_candidate_inputs():
    prepared = prepare_actor_geography(
        {
            "name": "Example",
            "city": "Boston",
            "state": "MA",
            "region": "west_coast_pacific",
            "latitude": 0,
            "longitude": 0,
        }
    )
    assert prepared.actor_values["region_code"] == "northeast"
    assert not math.isclose(prepared.actor_values["latitude"], 0)
    assert not math.isclose(prepared.actor_values["longitude"], 0)
    assert prepared.failures == ()


def test_multi_location_geocodes_rows_not_parent():
    prepared = prepare_actor_geography(
        {
            "name": "Example Network",
            "locations": [
                {"city": "Boston", "state": "MA", "location_name": "Boston office"},
                {"city": "New York", "state": "NY", "location_name": "New York office"},
            ],
        }
    )
    assert prepared.actor_values["is_multi_location"] is True
    assert "region_code" not in prepared.actor_values
    assert "latitude" not in prepared.actor_values
    assert len(prepared.locations) == 2
    assert all(location.result.found for location in prepared.locations)
    assert prepared.locations[0].result.latitude != prepared.locations[1].result.latitude


def test_no_gazetteer_match_records_not_found_without_coordinates():
    prepared = prepare_actor_geography(
        {"name": "Example", "city": "Not A Census Place", "state": "TX"}
    )
    assert prepared.actor_values["region_code"] == "south_central_texas_gulf"
    assert prepared.actor_values["latitude"] is None
    assert prepared.actor_values["longitude"] is None
    assert len(prepared.failures) == 1
    assert prepared.failures[0].result.state == "not_found"
    assert prepared.failures[0].result.reason == "city_not_found"
