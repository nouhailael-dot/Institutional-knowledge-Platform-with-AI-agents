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


class SaveTests(unittest.TestCase):
    def picks(self):
        other = {**ORG, "name": "Mosaic Company", "website": "https://mosaicco.com"}
        no_type = {**ORG, "name": "New Lab", "website": "https://newlab.example", "category_type": "Not classified"}
        return [("actor", ORG, "Mining"), ("actor", other, "Mining"), ("actor", no_type, "Mining"),
                ("event", EVENT, "Mining")]

    def test_the_check_writes_nothing_and_says_what_would_happen(self):
        service = FakeService(statuses={"Mosaic Company": "existing"})
        out = save.check(service, self.picks())
        self.assertEqual([r["outcome"] for r in out], [DIRECTORY, REVIEW, REVIEW, REVIEW])
        self.assertIn("category type", out[2]["reason"])
        self.assertIn("Events and people", out[3]["reason"])
        self.assertEqual(service.confirmed, [])

    def test_saving_admits_new_organizations_verified_and_sends_the_rest_to_review(self):
        service = FakeService(statuses={"Mosaic Company": "existing"}, held={"Mosaic Company", "New Lab"})
        out = save.save(service, self.picks(), uploader="Nouhaila El Hail", map_name="phosphate in Florida")
        self.assertEqual([r["outcome"] for r in out], [DIRECTORY, REVIEW, REVIEW, REVIEW])
        actor_call = next(kw for pid, kw in service.confirmed if pid == "p-actor")
        event_call = next(kw for pid, kw in service.confirmed if pid == "p-event")
        self.assertEqual((actor_call["admission"], event_call["admission"]), ("verified", "review"))
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
