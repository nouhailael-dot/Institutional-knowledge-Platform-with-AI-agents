"""The Data Feed's "Complete missing information": read only empty boxes, keep what GHUS gave."""

from __future__ import annotations

from agents.collection import light_pull_candidates as lp


def _found(value):
    return {"collection_state": "found", "value": value, "source_origin": "uploaded_document"}


def test_missing_boxes_skips_supplied_values_and_the_records_own_location():
    record = {"actor_category": "company", "city": "Wichita", "state_code": "KS",
              "data_feed": {"import_name": "x"},
              "light_pull_evidence": {"funding_signal": _found("USDA grant"),
                                      "recent_activity": {"collection_state": "not_found",
                                                          "value": None}}}
    wanted = lp.missing_boxes(record)
    assert "funding_signal" not in wanted          # GHUS supplied it
    assert "location" not in wanted                # the record states its city
    assert "why_matched" not in wanted             # no search topic behind a Data Feed record
    assert "recent_activity" in wanted             # read before, found nothing: read again
    assert {"ownership_and_size", "topic_business_segment_product",
            "mapped_geography_operations"} <= set(wanted)


def test_a_discovery_candidate_still_reads_location_and_why_matched():
    wanted = lp.missing_boxes({"actor_category": "startup"})
    assert wanted[:2] == ["location", "why_matched"]
    assert "published_stage_or_trl" in wanted


def test_keep_supplied_never_replaces_a_found_value():
    existing = {"funding_signal": _found("USDA grant"),
                "recent_activity": {"collection_state": "not_found", "value": None}}
    read = {"funding_signal": {"collection_state": "found", "value": "Other grant",
                               "source_origin": "newly_found"},
            "recent_activity": {"collection_state": "found", "value": {"date": "2026-01-01",
                                                                       "description": "x"}}}
    merged = lp.keep_supplied(existing, read)
    assert merged["funding_signal"]["value"] == "USDA grant"
    assert merged["recent_activity"]["collection_state"] == "found"


class _Session:
    def __init__(self, count, avg):
        self.row = (count, avg)

    def execute(self, *_args, **_kwargs):
        row = self.row

        class _Result:
            def one(self):
                return row
        return _Result()


def test_estimate_uses_what_earlier_reads_cost_and_skips_complete_records():
    targets = [
        {"candidate_id": "a", "record_preview": {"name": "A", "actor_category": "company",
                                                 "data_feed": {}}},
        {"candidate_id": "b", "record_preview": {"name": "B", "actor_category": "government",
                                                 "data_feed": {}, "city": "Austin",
                                                 "light_pull_evidence": {
            k: _found("x") for k in ("recent_activity", "funding_signal",
                                     "international_connection", "um6p_ocp_connection",
                                     "jurisdiction_parent_agency", "topic_mandate_program",
                                     "visible_funding_programs")}}},
    ]
    report = lp.estimate(_Session(17, 0.0423), targets, missing_only=True)
    assert [o["name"] for o in report["organisations"]] == ["A"]
    assert report["per_organisation_usd"] == 0.0423
    assert report["estimated_usd"] == 0.04
    assert "17 earlier reads" in report["basis"]
    fallback = lp.estimate(_Session(0, None), targets, missing_only=True)
    assert fallback["per_organisation_usd"] == lp.DEFAULT_COST_PER_ORGANISATION


def test_a_record_matched_to_an_existing_actor_is_not_read_again():
    record = {"actor_category": "company", "data_feed": {"match": {"kind": "existing"}}}
    assert lp.missing_boxes(record) == []
    record["data_feed"]["match"]["kind"] = "possible"
    assert lp.missing_boxes(record)
