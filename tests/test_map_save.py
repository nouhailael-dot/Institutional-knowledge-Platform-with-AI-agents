"""Verify -> the database through the Data Feed (asked for on 28 Oct 2026).
No database and no writes: the Data Feed service is a stand-in."""
import unittest

from src.map_agent import review, save
from src.map_agent.save import DIRECTORY, NOT_SAVED, REVIEW


class FakeService:
    """Answers like DataFeedService: one preview per record type, then confirm."""

    def __init__(self, statuses=None, held=()):
        self.statuses, self.held, self.sent, self.confirmed = statuses or {}, set(held), [], []

    def validate_manual(self, record_type, records, method="manual"):
        assert method == "map"
        self.sent.append((record_type, records))
        rows = []
        for n, record in enumerate(records, 1):
            status = self.statuses.get(record.get("name"), "new")
            rows.append({"row_number": n, "status": status, "payload": record,
                         "errors": ["Row 1: Sector is required"] if status == "invalid" else []})
        return {"preview_id": f"p-{record_type}", "rows": rows}

    def confirm(self, preview_id, **kwargs):
        self.confirmed.append((preview_id, kwargs))
        record_type = preview_id[2:]
        rows = [r for t, recs in self.sent if t == record_type for r in recs]
        return {"rows": [{"row_number": n, "outcome": "staged"} for n in range(1, len(rows) + 1)],
                # The directory admission's refusals: a possible duplicate is not added twice.
                "not_stored": [{"row_number": n, "outcome": "possible_duplicate",
                                "reason": "It may already be in the directory."}
                               for n, r in enumerate(rows, 1) if r["name"] in self.held],
                "held_for_review": [{"row_number": n, "reason": "It may already be on the map."}
                                    for n, r in enumerate(rows, 1) if r["name"] in self.held]}


ORG = {"_entity_type": "actor", "name": "FIPR Institute", "website": "https://fipr.floridapoly.edu",
       "actor_type": "Research Center / Institute / Laboratory", "category_type": "Applied Research Institute",
       "description": "Researches phosphate mining and processing.", "location_city": "Bartow",
       "state": "Florida", "country": "United States",
       "sources": [{"url": "https://fipr.floridapoly.edu/about"}]}
EVENT = {"_entity_type": "event", "name": "Tailings and Mine Waste 2026", "event_type": "International conference",
         "next_date": "2026-11-08", "end_date": "2026-11-11", "event_format": "In-person",
         "location": "Westminster, Colorado, United States", "recurring_pattern": "Every two years",
         "sources": [{"url": "https://tmw.example.org"}]}


class RecordTests(unittest.TestCase):
    def test_an_organization_card_becomes_a_data_feed_record(self):
        record = save.to_record("actor", ORG, "Mining")
        self.assertEqual(record["primary_sector"], "Mining")
        self.assertEqual(record["actor_category"], "Research Center / Institute / Laboratory")
        self.assertEqual((record["city"], record["state_code"]), ("Bartow", "Florida"))
        self.assertEqual(record["source_url"], "https://fipr.floridapoly.edu/about")

    def test_event_values_are_mapped_to_the_data_feed_lists_never_guessed(self):
        record = save.to_record("event", EVENT, "Mining")
        self.assertEqual((record["start_date"], record["end_date"]), ("11/08/2026", "11/11/2026"))
        self.assertEqual(record["event_type"], "conference")
        self.assertEqual(record["event_format"], "In person")
        self.assertEqual(record["recurring_pattern"], "Recurring")
        self.assertEqual((record["city"], record["state_code"]), ("Westminster", "Colorado"))
        vague = save.to_record("event", {**EVENT, "next_date": "2026-02", "event_type": "UN event",
                                         "event_format": "Not found", "location": "Online"}, "")
        for field in ("start_date", "event_type", "event_format", "city", "state_code", "sectors"):
            self.assertNotIn(field, vague)

    def test_a_person_never_carries_a_biography(self):
        person = {"full_name": "Ana Ruiz", "title": "Professor", "organization_name": "FIPR Institute",
                  "bio": "Ana grew up in…", "sources": [{"url": "https://fipr.floridapoly.edu/ana"}]}
        record = save.to_record("person", person, "Mining")
        self.assertNotIn("bio", record)
        self.assertEqual(record["affiliation"], "FIPR Institute")
        self.assertEqual((record["first_name"], record["last_name"]), ("Ana", "Ruiz"))


UNIVERSITY = {**ORG, "name": "University of Florida", "website": "https://www.ufl.edu",
              "actor_type": "University / Academic Institution", "category_type": "Main Institution",
              "funding_summary": "USDA NIFA grant, $1.2M, 2026, phosphate recovery.",
              "international_connections": "Partnership with UM6P on soil science.",
              "match_explanation": "Runs a phosphate research programme.",
              "category_details": [
                  {"key": "land_grant_designation", "label": "Land-grant", "value": "1862 land-grant"},
                  {"key": "main_funders", "label": "Funders", "value": "USDA"},
                  {"key": "other", "label": "Campus size", "value": "2,000 acres"}]}


def checked(record_type, record):
    """The real Data Feed check of one map record, as the service runs it."""
    from src.datafeed import contract, reference, validate
    by_key = {f.key: f for f in contract.fields(record_type)}
    record = {k: v for k, v in record.items() if k != "map_facts"}
    assert not set(record) - set(by_key), set(record) - set(by_key)
    values = {by_key[k].header: str(v) for k, v in record.items()}
    return validate.RowChecker(record_type, reference.vocabularies(None)).check(1, values)


class EventPlaceTests(unittest.TestCase):
    """25 Nov 2026: the venue was dropped and "…, New York, NY" read 1301 6th Ave as the city."""

    def test_the_venue_is_what_comes_before_the_city(self):
        record = save.to_record("event", {**EVENT, "location": "Oregon Convention Center, Portland, Oregon"}, "")
        self.assertEqual((record["venue"], record["city"], record["state_code"]),
                         ("Oregon Convention Center", "Portland", "Oregon"))

    def test_the_state_is_read_from_the_end(self):
        parts = save._place_parts("The Paramount Club, 1301 6th Ave, New York, NY, 10019")
        self.assertEqual(parts, ("The Paramount Club, 1301 6th Ave", "New York", "NY", "USA"))

    def test_a_place_with_no_venue_has_none(self):
        record = save.to_record("event", EVENT, "")
        self.assertNotIn("venue", record)
        self.assertEqual(record["city"], "Westminster")


class CategoryFactTests(unittest.TestCase):
    """24 Nov 2026: a map fills the template's own columns, as the update agent does."""

    def test_a_keyed_category_fact_fills_its_own_column(self):
        record = save.to_record("actor", UNIVERSITY, "Agriculture")
        self.assertEqual(record["land_grant_designation"], "1862 land-grant")
        details = record["map_facts"]["category_details"]
        self.assertEqual([d["label"] for d in details], ["Funders", "Campus size"])
        result = checked("actor", record)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["payload"]["light_pull_values"]["land_grant_designation"],
                         "1862 land-grant")

    def test_a_fact_keyed_for_another_category_stays_a_detail(self):
        record = save.to_record("actor", UNIVERSITY, "Agriculture")
        self.assertNotIn("main_funders", record)       # a research-centre fact
        from src.map_agent.actor_profile import normalize_actor_profile
        card = {**UNIVERSITY, "category_details": [dict(d) for d in UNIVERSITY["category_details"]]}
        normalize_actor_profile(card, set())
        self.assertEqual([d["key"] for d in card["category_details"]],
                         ["land_grant_designation", "other", "other"])

    def test_funding_international_and_why_matched_use_the_shared_names(self):
        record = save.to_record("actor", UNIVERSITY, "Agriculture")
        self.assertEqual(record["funding_summary"], UNIVERSITY["funding_summary"])
        self.assertNotIn("funding_signal", record)
        self.assertEqual(record["international_connection"], UNIVERSITY["international_connections"])
        facts = record["map_facts"]
        self.assertEqual(facts["why_matched"], UNIVERSITY["match_explanation"])
        self.assertNotIn("match_explanation", facts)
        self.assertNotIn("international_connections", facts)

    def test_a_startup_saves_with_its_published_stage_and_says_when_it_is_missing(self):
        startup = {**ORG, "name": "Soil Sense", "actor_type": "Startup / Emerging Technology Company",
                   "category_type": "Independent", "category_details": [
                       {"key": "development_stage", "label": "Stage", "value": "Pilot deployment"}]}
        self.assertEqual(checked("actor", save.to_record("actor", startup, "Agriculture"))["errors"], [])
        bare = checked("actor", save.to_record("actor", {**startup, "category_details": []}, "Agriculture"))
        self.assertTrue(any("development stage" in e for e in bare["errors"]))

    def test_a_card_from_before_the_keys_saves_as_it_did(self):
        old = {**UNIVERSITY, "category_details": [{"label": "Land-grant", "value": "1862 land-grant"}]}
        record = save.to_record("actor", old, "Agriculture")
        self.assertNotIn("land_grant_designation", record)
        self.assertEqual(record["map_facts"]["category_details"], old["category_details"])


class SaveTests(unittest.TestCase):
    def picks(self):
        other = {**ORG, "name": "Mosaic Company", "website": "https://mosaicco.com"}
        no_type = {**ORG, "name": "New Lab", "website": "https://newlab.example", "category_type": "Not classified"}
        return [("actor", ORG, "Mining"), ("actor", other, "Mining"), ("actor", no_type, "Mining"),
                ("event", EVENT, "Mining")]

    def test_the_check_writes_nothing_and_says_what_would_happen(self):
        service = FakeService(statuses={"Mosaic Company": "existing"})
        out = save.check(service, self.picks())
        # 12 Nov 2026 (GHUS): a map is reviewed on its own page; nothing it saves
        # goes to Review Results. A match updates the directory's record.
        self.assertEqual([r["outcome"] for r in out], [DIRECTORY, DIRECTORY, DIRECTORY, DIRECTORY])
        self.assertIn("already in the directory", out[1]["reason"])
        self.assertNotIn("Review", " ".join(r["reason"] for r in out))
        self.assertEqual(service.confirmed, [])

    def test_saving_stores_every_record_in_the_directory_and_none_in_review(self):
        service = FakeService(statuses={"Mosaic Company": "existing"}, held={"New Lab"})
        out = save.save(service, self.picks(), uploader="Nouhaila El Hail", map_name="phosphate in Florida")
        # A possible duplicate is not added twice; its card says why. Nothing goes to Review.
        self.assertEqual([r["outcome"] for r in out], [DIRECTORY, DIRECTORY, NOT_SAVED, DIRECTORY])
        self.assertIn("may already be in the directory", out[2]["reason"])
        actor_call = next(kw for pid, kw in service.confirmed if pid == "p-actor")
        event_call = next(kw for pid, kw in service.confirmed if pid == "p-event")
        self.assertEqual((actor_call["admission"], event_call["admission"]), ("directory", "directory"))
        self.assertIs(event_call["ai_enrichment"], False)
        self.assertEqual(actor_call["uploaded_by"], "Nouhaila El Hail")
        self.assertEqual(actor_call["import_name"], "Explore and Map: phosphate in Florida")

    def test_a_record_that_needs_correction_is_not_sent(self):
        service = FakeService(statuses={"FIPR Institute": "invalid"})
        out = save.save(service, [("actor", ORG, "")], uploader="N", map_name="m")
        self.assertEqual(out[0]["outcome"], NOT_SAVED)
        self.assertIn("Sector is required", out[0]["reason"])
        self.assertEqual(service.confirmed, [])


class ReadyMarkTests(unittest.TestCase):
    def maps(self):
        card = {"name": "FIPR Institute", "website": "https://fipr.floridapoly.edu"}
        found = {**card, "_entity_type": "actor"}
        return {"entities": {"actor": [card]}}, {"found": [found]}

    def test_verify_marks_ready_and_saving_clears_the_mark(self):
        result, workflow = self.maps()
        review.apply(result, workflow, "FIPR Institute", "https://fipr.floridapoly.edu", "ready")
        self.assertEqual(result["entities"]["actor"][0]["_review"], "ready")
        self.assertEqual(workflow["found"][0]["_review"], "ready")
        review.mark_saved(result, workflow, "FIPR Institute", "https://fipr.floridapoly.edu", "actor",
                          {"outcome": "directory", "by": "N"})
        card = result["entities"]["actor"][0]
        self.assertNotIn("_review", card)
        self.assertEqual(card["_db_save"]["outcome"], "directory")
        with self.assertRaises(LookupError):
            review.apply(result, workflow, "FIPR Institute", "https://fipr.floridapoly.edu", "ready")

    def test_a_card_that_was_not_saved_stays_ready(self):
        result, workflow = self.maps()
        review.apply(result, workflow, "FIPR Institute", "https://fipr.floridapoly.edu", "ready")
        review.mark_saved(result, workflow, "FIPR Institute", "https://fipr.floridapoly.edu", "actor",
                          {"outcome": "not_saved", "by": "N"})
        self.assertEqual(result["entities"]["actor"][0]["_review"], "ready")




class ResponseTests(unittest.TestCase):
    def test_the_saved_outcome_survives_the_json_response(self):
        # FastAPI's encoder drops keys starting with "_sa"; "_saved" vanished
        # from every response while it was stored correctly (28 Oct 2026).
        from fastapi.encoders import jsonable_encoder
        card = {"name": "FIPR Institute", "_db_save": {"outcome": "review"}}
        self.assertEqual(jsonable_encoder(card)["_db_save"], {"outcome": "review"})
        self.assertNotIn("_saved", jsonable_encoder({"_saved": 1}))


class SetupTests(unittest.TestCase):
    def test_saving_says_what_is_missing_when_this_computer_is_not_set_up(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from fastapi import HTTPException
        import backend.app as app
        unconfigured = SimpleNamespace(bridge=SimpleNamespace(configured=False))
        with patch("backend.datafeed_routes.datafeed_service", return_value=unconfigured):
            with self.assertRaises(HTTPException) as raised:
                app._save_service()
        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("DATAFEED_DATABASE_URL", raised.exception.detail)


if __name__ == "__main__":
    unittest.main()
