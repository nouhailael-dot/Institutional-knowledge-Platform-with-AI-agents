"""The Phase 1 export's cleaning rules: one spelling per value, nothing invented."""

from scripts.export_phase1_dataset import aggregate_reason, build_rows, fact_text, https, site_key


def _row(**over):
    row = {"actor_id": "a1", "name": "Prairie Water Lab", "alt_names": None,
           "website": "www.prairiewater.org/", "website_domain": None,
           "actor_category": "research_center", "category": "Research Center",
           "category_type_code": None, "category_type": None, "category_note": None,
           "city": "Wichita", "state_code": "KS", "state_name": "Kansas", "region_code": "midwest",
           "region": "Midwest", "country": "USA", "latitude": None, "longitude": None,
           "description": "Details should be verified from primary sources.", "status": "verified",
           "source_origin": "imported_phase1", "updated_at": None,
           "primary_technical_focus": "Irrigation sensors.", "technical_approach": None,
           "current_activities": None, "technology_ip_notes": None, "key_constraints": None,
           "funding_summary": "Academic funding profile.", "primary_lifecycle_role": "operator"}
    row.update(over)
    return row


def test_websites_and_sites_are_normalized():
    assert https("www.x.org") == "https://www.x.org"
    assert https("http://x.org/a") == "https://x.org/a"
    assert site_key("http://www.X.org/about/") == ("x.org", "x.org/about")


def test_not_found_and_empty_facts_stay_empty():
    assert fact_text({"value": "Not found"}) == ""
    assert fact_text(["a", {"text": "b"}]) == "a; b"


def test_aggregate_rows_are_set_apart_with_their_reason():
    assert "aggregate" in aggregate_reason(_row(description="Aggregate category for AI actors"))
    assert aggregate_reason(_row()) is None


def test_one_spelling_placeholders_and_templates_left_empty_and_noted():
    rows = [_row(actor_id=f"a{i}", name=f"Lab {i}", website=f"https://lab{i}.org") for i in range(3)]
    kept, excluded = build_rows(rows, {"a0": [("WATER", "Water", True)]}, {}, {})
    first = kept[0]
    assert excluded == []
    assert first["country"] == "United States" and first["state"] == "Kansas"
    assert first["description"] == "" and first["funding_summary"] == ""
    assert first["sector"] == "Water" and first["primary_lifecycle_role"] == ""
    assert "placeholder" in first["notes"] and "Generic" in first["notes"]
    assert "not a lifecycle stage" in first["notes"]
    assert kept[1]["sector"] == "" and "Sector not yet assigned" in kept[1]["notes"]


def test_two_records_with_the_same_page_are_flagged_and_several_sectors_none_promoted():
    rows = [_row(actor_id="a", name="CAISO", website="https://www.caiso.com/"),
            _row(actor_id="b", name="California ISO", website="caiso.com")]
    sectors = {"a": [("ENERGY", "Energy Transition", False), ("AI", "Artificial Intelligence", False)]}
    kept, _ = build_rows(rows, sectors, {}, {})
    assert "same website as: California ISO" in kept[0]["notes"]
    assert kept[0]["sector"] == "Artificial Intelligence; Energy Transition"
    assert "Main sector to choose" in kept[0]["notes"]


def test_a_website_field_with_several_addresses_keeps_the_first_and_is_flagged():
    rows = [_row(website="https://www.arizona.edu College of Engineering: https://engineering.arizona.edu")]
    kept, _ = build_rows(rows, {}, {}, {})
    assert kept[0]["website"] == "https://www.arizona.edu"
    assert "several addresses" in kept[0]["notes"]
