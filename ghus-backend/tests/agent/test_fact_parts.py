"""Facts in parts: decomposed from the page, checked against it, compared one by one."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agents.collection.actor_updates import classify
from agents.collection.light_pull_reader import LightPullReader
from agents.common.fact_parts import (
    CARRIED_OVER,
    FACT_PARTS,
    clean_parts,
    compare_values,
    parts_line,
    supported_parts,
)
from agents.discovery.sources.base import FetchedDoc

NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)
HOME = "https://companyx.example/"
PAGE = ("<p>Company X has 500 employees, operates in Texas, and received a $2M grant from "
        "the Texas Energy Fund in March 2026. It is a subsidiary of Acme Holdings.</p>")


def _fetch(url):
    if url != HOME:
        raise RuntimeError("not found")
    return FetchedDoc.from_content(url=url, content=PAGE, content_type="text/html")


class Model:
    def __init__(self, answers):
        self.answers = answers

    def extract_with_tool(self, **kwargs):
        self.schema = kwargs["input_schema"]
        self.system = kwargs["system"]
        return self.answers


def _read(answers, fields):
    model = Model(answers)
    read = LightPullReader(model, _fetch).read(
        name="Company X", website=HOME, actor_category="company", read_at=NOW, fields=fields)
    return read, model


def test_one_sentence_becomes_separate_facts_in_their_own_boxes():
    read, model = _read({
        "ownership_and_size": {"stated": True, "page": HOME,
                               "value": {"employees": 500, "parent_organization": "Acme Holdings",
                                         "ownership": "subsidiary of Acme Holdings"},
                               "quotes": ["Company X has 500 employees",
                                          "It is a subsidiary of Acme Holdings."]},
        "mapped_geography_operations": {"stated": True, "page": HOME,
                                        "value": {"places": ["Texas"]},
                                        "quotes": ["operates in Texas"]},
        "funding_signal": {"stated": True, "page": HOME,
                           "value": {"amount": "$2M", "funder": "Texas Energy Fund",
                                     "funding_type": "grant", "date": "March 2026"},
                           "quotes": ["received a $2M grant from the Texas Energy Fund in March 2026"]},
    }, ["ownership_and_size", "mapped_geography_operations", "funding_signal"])
    ev = read.evidence
    assert ev["ownership_and_size"]["value"] == {
        "ownership": "subsidiary of Acme Holdings", "parent_organization": "Acme Holdings",
        "employees": 500}
    assert ev["mapped_geography_operations"]["value"] == {"places": ["Texas"]}
    assert ev["funding_signal"]["value"]["amount"] == "$2M"
    assert ev["funding_signal"]["quotes"]        # the evidence is kept with the fact
    # The model is asked for the parts, and told to split one paragraph into boxes.
    parts = model.schema["properties"]["ownership_and_size"]["properties"]["value"]["properties"]
    assert set(parts) == set(FACT_PARTS["ownership_and_size"])
    assert "never copy one paragraph into several boxes" in model.system


def test_a_part_the_quotes_do_not_state_is_dropped_never_kept():
    read, _ = _read({"ownership_and_size": {
        "stated": True, "page": HOME,
        # 650 is on no page; the revenue is invented.
        "value": {"employees": 650, "revenue": "$40 million", "parent_organization": "Acme Holdings"},
        "quotes": ["It is a subsidiary of Acme Holdings."]}}, ["ownership_and_size"])
    evidence = read.evidence["ownership_and_size"]
    assert evidence["value"] == {"parent_organization": "Acme Holdings"}
    assert evidence["dropped_parts"] == ["employees: 650", "revenue: $40 million"]
    # Nothing left that the quotes back: not found, with the reason.
    read, _ = _read({"funding_signal": {"stated": True, "page": HOME,
                                        "value": {"amount": "$9M"},
                                        "quotes": ["operates in Texas"]}}, ["funding_signal"])
    assert read.evidence["funding_signal"]["collection_state"] == "not_found"
    assert "no part" in read.rejected["funding_signal"]


def test_counts_are_whole_numbers_and_empty_parts_are_left_out():
    assert clean_parts("ownership_and_size", {"employees": "~2,000", "customers": None,
                                              "ownership": "  public "}) == {
        "employees": 2000, "ownership": "public"}
    kept, dropped = supported_parts("ownership_and_size", {"customers": 2000},
                                    "serves ~2,000 customers across the U.S.")
    assert kept == {"customers": 2000} and dropped == []


def test_changes_are_found_fact_by_fact():
    before = {"employees": 500, "ownership": "private"}
    result = compare_values("ownership_and_size", before, {"employees": 600, "ownership": "private"})
    assert result["outcome"] == "changed"
    assert {p["part"]: p["outcome"] for p in result["parts"]} == {
        "employees": "changed", "ownership": "confirmed"}
    assert result["merged"] == {"employees": 600, "ownership": "private"}
    assert parts_line(result["parts"]) == "Employees: 500 → 600 · Ownership: confirmed"
    places = compare_values("mapped_geography_operations", {"places": ["Texas"]},
                            {"places": ["Texas"]})
    assert places["outcome"] == "corroborated"


def test_a_shorter_reading_never_replaces_a_richer_record():
    before = {"employees": 500, "ownership": "private", "customers": 2000}
    poorer = compare_values("ownership_and_size", before, {"employees": 500})
    assert poorer["outcome"] == "corroborated" and poorer["merged"] == before
    # A change in one part keeps the parts this reading did not restate, and says so.
    changed = compare_values("ownership_and_size", before, {"employees": 600})
    assert changed["merged"] == {"employees": 600, "ownership": "private", "customers": 2000,
                                 CARRIED_OVER: ["customers", "ownership"]}
    # The same for text recorded before parts existed.
    legacy = "CPower Energy is an NRG company (acquired by NRG Energy); serves ~2,000 customers."
    assert compare_values("ownership_and_size", legacy,
                          {"parent_organization": "NRG Energy", "customers": 2000})["outcome"] \
        == "corroborated"
    assert compare_values("description", "An NRG company serving 2,000 customers.",
                          "An NRG company.")["outcome"] == "corroborated"


def test_more_details_are_additional_not_a_change():
    added = compare_values("ownership_and_size", {"employees": 500},
                           {"employees": 500, "customers": 2000})
    assert added["outcome"] == "additional"
    assert added["merged"] == {"employees": 500, "customers": 2000}
    members = compare_values("linked_members", {"members": ["A. O. Smith"]},
                             {"members": ["Badger Meter"]})
    assert members["outcome"] == "additional"
    assert members["merged"] == {"members": ["A. O. Smith", "Badger Meter"]}


def test_one_thing_described_is_replaced_whole_when_it_is_a_different_one():
    grant = compare_values("funding_signal", {"amount": "$1M", "funder": "DOE", "date": "2025"},
                           {"amount": "$2M", "funder": "Texas Energy Fund"})
    assert grant["outcome"] == "changed"
    assert grant["merged"] == {"amount": "$2M", "funder": "Texas Energy Fund"}
    # A different city never keeps the old state.
    moved = compare_values("location", {"city": "Baltimore", "state": "MD"}, {"city": "Houston"})
    assert moved["merged"] == {"city": "Houston"}


def _recorded(value, *, confidence="medium", when="2026-09-01T00:00:00+00:00", by="agent"):
    return {"collection_state": "found", "fact_value": value, "confidence": confidence,
            "retrieved_at": when, "creator_class": by, "source_url": "https://x.example/old"}


def _evidence(value):
    return {"collection_state": "found", "value": value, "confidence": "high",
            "source_url": HOME, "date_read": NOW.isoformat()}


@pytest.mark.parametrize(("before", "after", "outcome"), [
    ({"employees": 500, "places": ["Texas"]}, {"employees": 600, "places": ["Texas"]}, "changed"),
    ({"employees": 500}, {"employees": 500, "customers": 2000}, "additional"),
    ({"employees": 500, "customers": 2000}, {"employees": 500}, "corroborated"),
])
def test_an_update_classifies_each_box_by_its_facts(before, after, outcome):
    finding = classify("ownership_and_size", _recorded(before), _evidence(after), None,
                       read_at=NOW, topic_name="Energy")
    assert finding["outcome"] == outcome
    if outcome != "corroborated":
        assert finding["_write_value"] == finding["proposed"]["value"]
        assert finding["what_changed"]


def test_a_weaker_reading_with_more_details_is_a_conflict_and_ghus_values_stay():
    weaker = classify("ownership_and_size",
                      _recorded({"employees": 500}, confidence="high",
                                when="2026-10-25T00:00:00+00:00"),
                      _evidence({"employees": 600}), None, read_at=NOW, topic_name="Energy")
    assert weaker["outcome"] == "conflict"
    ghus = classify("ownership_and_size", _recorded({"employees": 500}, by="ghus_human"),
                    _evidence({"employees": 500, "customers": 10}), None,
                    read_at=NOW, topic_name="Energy")
    assert ghus["outcome"] == "protected"


def test_a_country_alone_is_not_an_international_connection():
    """Where graduates find jobs is not a connection the organisation has."""
    read, _ = _read({"international_connection": {
        "stated": True, "page": HOME, "value": {"country": "Texas"},
        "quotes": ["operates in Texas"]}}, ["international_connection"])
    assert read.evidence["international_connection"]["collection_state"] == "not_found"
    assert "names no partner" in read.rejected["international_connection"]


def test_the_agents_own_wording_is_not_a_change():
    """2026-10-22: two reads of the same page, worded differently each time."""
    was = {"strength": "strong", "reason": "The page describes the UA mining engineering degree "
                                           "program itself, covering academic tracks and research centers."}
    now = {"strength": "strong", "reason": "This page describes the University of Arizona's mining "
                                           "engineering degree program and its research centers."}
    assert compare_values("why_matched", was, now)["outcome"] == "corroborated"
    assert compare_values("why_matched", was, {**now, "strength": "moderate"})["outcome"] == "changed"
    same = compare_values(
        "topic_unit_and_work",
        "School of Mining Engineering and Mineral Resources at the UA College of Engineering works "
        "on mineral extraction and processing, geomechanics and sustainable development.",
        "The School of Mining Engineering and Mineral Resources at the University of Arizona "
        "College of Engineering offers a mining engineering degree in mineral processing.")
    assert same["outcome"] == "corroborated"
    different = compare_values(
        "mission_sector_focus",
        "Provides innovative technical, economic and policy solutions to enable communities to "
        "participate equitably in the clean energy transition",
        "National, nonprofit organization working to advance clean energy and mitigate climate "
        "change through innovation in policy, technology and finance.")
    assert different["outcome"] in {"changed", "additional"}


def test_rewording_does_not_hide_changed_figures():
    assert compare_values("description", "Employs 500 engineers in Boston",
                          "Employs 600 engineers in Boston")["outcome"] == "changed"
