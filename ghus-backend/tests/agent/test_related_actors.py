"""Organisations an update names: only names in checked values, in the right direction."""

from __future__ import annotations

from agents.collection import related_actors as ra

FINDINGS = [
    {"field": "international_connection", "proposed": {
        "value": "Joint water-reuse project with Mohammed VI Polytechnic University in Morocco.",
        "source_url": "https://co.example/partners"}},
    {"field": "funding_signal", "proposed": {
        "value": "$2M grant from the National Science Foundation in 2026.",
        "source_url": "https://co.example/news"}},
    {"field": "linked_members", "proposed": {
        "value": ["Acme Water", "Blue River Labs"], "source_url": "https://co.example/members"}},
    {"field": "recent_activity", "proposed": {   # not a relation box
        "value": "Hosted the Water Summit with Fake Partner Inc.", "source_url": "https://x"}},
    {"field": "main_funders", "proposed": None},  # nothing found
]


def test_only_relation_boxes_with_a_checked_value_are_read():
    values = ra.relation_values(FINDINGS)
    assert sorted(values) == ["funding_signal", "international_connection", "linked_members"]
    assert values["linked_members"]["text"] == "Acme Water Blue River Labs"


def test_a_name_is_kept_only_if_it_is_in_the_checked_value_of_its_box():
    values = ra.relation_values(FINDINGS)
    kept = ra.grounded([
        {"name": "National Science Foundation", "box": "funding_signal", "relation": "funder"},
        # Invented: not in the value.
        {"name": "Department of Energy", "box": "funding_signal", "relation": "funder"},
        # Real name, wrong box.
        {"name": "Acme Water", "box": "funding_signal", "relation": "funder"},
        # The actor itself, and a duplicate.
        {"name": "Clean Co", "box": "international_connection", "relation": "partner"},
        {"name": "national science foundation", "box": "funding_signal", "relation": "funder"},
        # Not one of the allowed relations.
        {"name": "Blue River Labs", "box": "linked_members", "relation": "rival"},
        {"name": "Blue River Labs", "box": "linked_members", "relation": "member"},
    ], values, actor_name="Clean Co")
    assert [k["name"] for k in kept] == ["National Science Foundation", "Blue River Labs"]
    assert kept[0]["source_url"] == "https://co.example/news"


def test_the_relation_says_who_is_the_subject_of_the_edge():
    assert ra.RELATIONS["funder"] == ("funded_by", True)           # actor funded_by funder
    assert ra.RELATIONS["funded_by_this"] == ("funded_by", False)  # grantee funded_by actor
    assert ra.RELATIONS["member"] == ("member_of", False)          # member member_of actor
    assert ra.RELATIONS["parent"] == ("unit_of", True)             # actor unit_of parent
    # Every relation is a distinct edge: no two say the same thing.
    assert len(set(ra.RELATIONS.values())) == len(ra.RELATIONS)
    from agents.common.relationships import RELATIONSHIP_ENDPOINTS

    for relationship_type, _ in ra.RELATIONS.values():
        assert ("actor", "actor") in RELATIONSHIP_ENDPOINTS[relationship_type]


def test_no_model_call_when_no_box_names_anyone():
    class Client:
        calls = 0

        def extract_with_tool(self, **kwargs):
            Client.calls += 1
            return {"organisations": []}

    assert ra.extract(Client(), actor_name="X", findings=[FINDINGS[3], FINDINGS[4]]) == []
    assert Client.calls == 0


def test_the_model_sees_only_checked_values_and_cannot_add_names():
    seen = {}

    class Client:
        def extract_with_tool(self, **kwargs):
            seen.update(kwargs)
            return {"organisations": [
                {"name": "Mohammed VI Polytechnic University", "box": "international_connection",
                 "relation": "partner"},
                {"name": "OCP Group", "box": "international_connection", "relation": "partner"},
            ]}

    kept = ra.extract(Client(), actor_name="Clean Co", findings=FINDINGS)
    assert [k["name"] for k in kept] == ["Mohammed VI Polytechnic University"]
    assert "Fake Partner" not in seen["user"]  # recent_activity is not a relation box
    assert "untrusted" in seen["system"]
