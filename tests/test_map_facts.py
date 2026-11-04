"""Explore and Map: every field a card shows reaches the database (4 Nov 2026)."""

import pytest

from src.map_agent.save import map_facts, to_record


EVENT = {"name": "World Agri-Tech Summit", "event_type": "Summit", "next_date": "2027-03-09",
         "end_date": "2027-03-10", "event_format": "in-person", "audience": "Growers and investors",
         "previous_edition": "March 2026, San Francisco", "um6p_ocp_status": "Not found",
         "match_explanation": "The leading agtech investment summit in the US.",
         "sources": [{"url": "https://worldagritechusa.com"}], "profile_version": 2}
ACTOR = {"name": "Prairie Water Lab", "actor_type": "Research Center / Institute / Laboratory",
         "primary_technical_focus": "Irrigation sensors", "current_activities": "Pilot in Kansas",
         "category_details": [{"label": "Main funders", "value": "USDA"}],
         "actor_relationships": [{"organization_name": "K-State", "relationship": "unit of"}],
         "match_strength": "strong", "website": "https://prairiewaterlab.org"}


def test_every_card_field_the_record_does_not_carry_goes_to_map_facts():
    facts = map_facts("event", EVENT)
    assert facts == {"audience": "Growers and investors",
                     "previous_edition": "March 2026, San Francisco",
                     "match_explanation": "The leading agtech investment summit in the US."}
    record = to_record("event", EVENT, "AGRI")
    assert record["map_facts"] == facts and record["name"] == "World Agri-Tech Summit"
    actor = map_facts("actor", ACTOR)
    assert {"primary_technical_focus", "current_activities", "category_details",
            "actor_relationships", "match_strength"} <= set(actor)
    assert "name" not in actor and "website" not in actor


def test_the_data_feed_keeps_map_facts_from_explore_and_map_only(tmp_path):
    from src.datafeed.service import DataFeedError, DataFeedService

    service = DataFeedService(bridge=None, connect=None, preview_dir=tmp_path)
    record = {"name": "Water Summit", "event_type": "Summit", "start_date": "04/02/2027",
              "website": "https://ws.example.org", "map_facts": {"audience": "Utilities"}}
    preview = service.validate_manual("event", [record], method="map")
    assert preview["rows"][0]["payload"]["map_facts"] == {"audience": "Utilities"}
    with pytest.raises(DataFeedError, match="Unknown fields: map_facts"):
        service.validate_manual("event", [record], method="manual")
