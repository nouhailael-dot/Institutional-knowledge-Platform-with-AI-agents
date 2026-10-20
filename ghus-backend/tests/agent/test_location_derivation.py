"""A missing state, region or coordinates, derived from the record - only when unique."""

from __future__ import annotations

import pytest

from agents.common.location_derivation import city_variants, derive, state_from_name
from agents.review.admission import _state_from_record


@pytest.mark.parametrize("name,expected", [
    ("University of Texas at Austin", "TX"),
    ("Arizona State University", "AZ"),
    ("West Virginia University", "WV"),        # not Virginia
    ("Washington State University", "WA"),
    ("Washington University in St. Louis", None),  # Missouri
    ("George Washington Carver Center", None),
    ("Kansas City Water Services", None),       # Kansas City is mostly in Missouri
    ("Texas and Oklahoma Energy Alliance", None),  # two states: not one place
    ("Clean Energy Group", None),
])
def test_a_state_is_read_from_a_name_only_when_the_name_means_the_place(name, expected):
    assert state_from_name(name) == expected


def test_a_compound_city_is_tried_part_by_part():
    assert city_variants("Washington D.C.")[:2] == ["Washington D.C.", "Washington"]
    assert "Urbana" in city_variants("Urbana-Champaign")
    assert city_variants(None) == []


def test_coordinates_come_from_a_city_in_the_records_own_state():
    d = derive(name="Illinois Materials Research Laboratory", city="Urbana-Champaign", state="IL")
    assert (d.latitude is not None, d.region_code) == (True, "midwest_great_lakes")
    assert d.state_code is None  # the state was already recorded


def test_a_name_gives_a_city_only_after_at_or_a_dash_and_never_a_state_name():
    d = derive(name="University of Texas at Austin", city=None, state=None)
    assert (d.city, d.state_code, d.latitude is not None) == ("Austin", "TX", True)
    assert derive(name="Center for Energy in Texas", city=None, state=None).city is None


def test_nothing_is_derived_for_several_sites_an_ambiguous_city_or_abroad():
    assert not derive(name="NETL", city="Pittsburgh / Morgantown",
                      state="Oregon / Pennsylvania / West Virginia").any
    assert derive(name="X", city="Montpelier", state=None).state_code is None  # several states
    assert not derive(name="IREL (India) Limited", city="Mumbai", state="Maharashtra",
                      country="India").any


def test_verification_fills_a_missing_state_from_the_record():
    payload = {"name": "University of Texas at Austin"}
    _state_from_record(payload)
    assert (payload["state"], payload["location_city"]) == ("TX", "Austin")
    kept = {"name": "University of Texas at Austin", "state": "CA"}
    _state_from_record(kept)
    assert kept["state"] == "CA"  # a recorded state is never changed
