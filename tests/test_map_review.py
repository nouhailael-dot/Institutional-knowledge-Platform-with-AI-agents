"""Park and Reject in a saved map, and Ask finding parked organizations."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.map_agent import parked, review
from src.map_agent.run_store import MapStopped, RunStore

LAB = {"_entity_type": "actor", "name": "Example Lab", "website": "https://example.edu/lab",
       "description": "Battery research", "actor_type": "University / Academic Institution"}
OTHER = {"_entity_type": "actor", "name": "Other Co", "website": "https://other.example"}


class SavedMap:
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = RunStore(Path(temp.name) / "runs.sqlite3")
        self.id = self.store.create("battery labs")
        self.store.claim(self.id, "running", "Research", ("draft",))
        self.store.checkpoint_workflow(
            self.id, {"version": 1, "phase": "done", "found": [dict(LAB), dict(OTHER)]},
            {"entities": {"actor": [dict(LAB), dict(OTHER)], "person": [], "event": []},
             "counts": {"actor": 2}})
        self.store.finish(self.id, "done")

    def act(self, action, name="Example Lab", website="https://example.edu/lab"):
        self.store.edit_result(self.id, lambda r, w: review.apply(r, w, name, website, action))
        return self.store.get(self.id)["result"], self.store.cached(self.id, "workflow")


class ReviewTests(SavedMap, unittest.TestCase):
    def test_park_marks_the_result_and_the_saved_research(self):
        result, workflow = self.act("park")
        self.assertEqual(result["entities"]["actor"][0]["_review"], "parked")
        self.assertEqual(workflow["found"][0]["_review"], "parked")
        result, workflow = self.act("unpark")
        self.assertNotIn("_review", result["entities"]["actor"][0])
        self.assertNotIn("_review", workflow["found"][0])

    def test_reject_removes_it_from_both_and_remembers_it_for_this_map(self):
        result, workflow = self.act("reject")
        self.assertEqual([a["name"] for a in result["entities"]["actor"]], ["Other Co"])
        self.assertEqual(result["counts"]["actor"], 1)
        self.assertEqual([e["name"] for e in workflow["found"]], ["Other Co"])
        self.assertEqual(workflow["rejected"], ["actor|example lab"])

    def test_an_organization_not_in_the_map_is_reported(self):
        with self.assertRaises(LookupError):
            self.act("park", name="Missing Lab")

    def test_no_change_while_the_map_is_running(self):
        self.store.update(self.id, status="running")
        with self.assertRaises(MapStopped):
            self.act("reject")
        self.assertEqual(len(self.store.get(self.id)["result"]["entities"]["actor"]), 2)

    def test_parked_organizations_are_listed_across_maps(self):
        self.act("park")
        self.assertEqual([(d, a["name"]) for _, d, a in self.store.parked_records()],
                         [("battery labs", "Example Lab")])


PERSON = {"_entity_type": "person", "full_name": "Sam Example", "title": "Professor",
          "organization_name": "Dept. of Chemistry", "expertise": "battery chemistry"}
EVENT = {"_entity_type": "event", "name": "Battery Summit 2027", "website": "https://summit.example",
         "next_date": "2027-03-01", "description": "Battery conference"}


class PeopleAndEventReviewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = RunStore(Path(temp.name) / "runs.sqlite3")
        self.id = self.store.create("battery people and events")
        self.store.claim(self.id, "running", "Research", ("draft",))
        self.store.checkpoint_workflow(
            self.id, {"version": 1, "phase": "done", "found": [dict(PERSON), dict(EVENT)]},
            {"entities": {"actor": [], "person": [dict(PERSON)], "event": [dict(EVENT)]},
             "counts": {"actor": 0, "person": 1, "event": 1}})
        self.store.finish(self.id, "done")

    def act(self, kind, name, website, action):
        self.store.edit_result(self.id, lambda r, w: review.apply(r, w, name, website, action, kind))
        return self.store.get(self.id)["result"], self.store.cached(self.id, "workflow")

    def test_a_person_can_be_parked_and_unparked(self):
        result, workflow = self.act("person", "Sam Example", None, "park")
        self.assertEqual(result["entities"]["person"][0]["_review"], "parked")
        self.assertEqual(workflow["found"][0]["_review"], "parked")
        result, _ = self.act("person", "Sam Example", None, "unpark")
        self.assertNotIn("_review", result["entities"]["person"][0])

    def test_an_event_can_be_rejected(self):
        result, workflow = self.act("event", "Battery Summit 2027", "https://summit.example", "reject")
        self.assertEqual(result["entities"]["event"], [])
        self.assertEqual(result["counts"]["event"], 0)
        self.assertEqual([e["_entity_type"] for e in workflow["found"]], ["person"])
        self.assertEqual(workflow["rejected"], ["event|battery summit 2027"])

    def test_the_kind_must_match(self):
        with self.assertRaises(LookupError):
            self.act("actor", "Sam Example", None, "park")

    def test_parked_people_and_events_are_listed_and_searchable(self):
        self.act("person", "Sam Example", None, "park")
        self.act("event", "Battery Summit 2027", "https://summit.example", "park")
        kinds = sorted(r["_entity_type"] for _, _, r in self.store.parked_records())
        self.assertEqual(kinds, ["event", "person"])
        with patch.object(parked, "embed_texts", side_effect=ParkedSearchTests.fake_embed):
            rows = parked.search("battery experts", self.store)
        self.assertEqual({(r["name"], r["entity_type"]) for r in rows},
                         {("Sam Example", "person"), ("Battery Summit 2027", "event")})
        self.assertTrue(all(r["parked"] for r in rows))


class ParkedSearchTests(SavedMap, unittest.TestCase):
    @staticmethod
    def fake_embed(texts, input_type):
        # Battery text sits near a battery question; anything else sits far away.
        return [[1.0, 0.0] if "battery" in t.casefold() else [0.0, 1.0] for t in texts]

    def test_close_parked_organizations_are_returned_and_embedded_once(self):
        self.act("park")
        self.act("park", name="Other Co", website="https://other.example")
        with patch.object(parked, "embed_texts", side_effect=self.fake_embed) as embed:
            rows = parked.search("battery research labs", self.store)
            again = parked.search("battery research labs", self.store)
        self.assertEqual([r["name"] for r in rows], ["Example Lab"])
        self.assertTrue(rows[0]["parked"])
        self.assertEqual(rows[0]["map"], "battery labs")
        self.assertEqual(again, rows)
        # First search embeds both parked docs and the question; the second only the question.
        self.assertEqual([len(c.args[0]) for c in embed.call_args_list], [2, 1, 1])

    def test_names_already_answered_from_the_database_are_skipped(self):
        self.act("park")
        with patch.object(parked, "embed_texts", side_effect=self.fake_embed):
            self.assertEqual(parked.search("battery", self.store, skip_names=["example lab"]), [])

    def test_nothing_parked_makes_no_embedding_call(self):
        with patch.object(parked, "embed_texts") as embed:
            self.assertEqual(parked.search("battery", self.store), [])
        embed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
