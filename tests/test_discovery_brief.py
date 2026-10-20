"""Build the Map -> Discovery: the proposed request keeps only what the user asked for."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import app
from src.map_agent import discovery_brief
from src.map_agent.run_store import RunStore

SECTORS = {"Mining": "MINING", "Water": "WATER", "Energy Transition": "ENERGY"}
CONVERSATION = [{"role": "user", "content": "Map labs working on phosphogypsum reuse and "
                                            "rare earth recovery in Florida"},
                {"role": "assistant", "content": "Here is your map."}]


def reply(data):
    return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="propose_discovery", input=data)])


class ProposalTests(unittest.TestCase):
    def propose(self, data, messages=CONVERSATION):
        with patch.object(discovery_brief, "sectors", return_value=SECTORS), \
             patch.object(discovery_brief, "paid_message", return_value=reply(data)) as paid:
            out = discovery_brief.propose_discovery(messages, "", run=object())
        return out, paid

    def test_brief_names_sector_and_area_then_one_sub_topic_per_line(self):
        out, paid = self.propose({"sector": "Mining", "area": "Florida",
                                  "sub_topics": ["phosphogypsum reuse", "rare earth recovery"]})
        self.assertEqual(out["brief"], "Mining organizations in Florida.\n"
                                       "phosphogypsum reuse\nrare earth recovery")
        self.assertEqual((out["sector_code"], out["state_code"], out["region_code"]), ("MINING", "FL", None))
        self.assertEqual(paid.call_args.kwargs["model"], discovery_brief.MODEL)
        self.assertEqual(paid.call_args.args[2], "Discovery proposal")

    def test_sub_topics_must_use_the_users_words_and_stay_short(self):
        out, _ = self.propose({"sector": "Mining", "area": "", "sub_topics": [
            "phosphogypsum reuse",                       # the user's words: kept
            "gypsum stack valorization",                 # invented words: dropped
            "phosphogypsum reuse recovery rare earth",   # too long to ever match: dropped
            "Phosphogypsum Reuse",                       # duplicate: dropped
        ]})
        self.assertEqual(out["sub_topics"], ["phosphogypsum reuse"])

    def test_an_area_the_user_never_named_is_dropped(self):
        out, _ = self.propose({"sector": "Mining", "area": "Texas", "sub_topics": ["phosphogypsum"]})
        self.assertEqual(out["area"], "")
        self.assertTrue(out["brief"].startswith("Mining organizations in the United States."))
        self.assertIsNone(out["state_code"])

    def test_half_a_region_name_counts_as_naming_it(self):
        messages = [{"role": "user", "content": "water reuse startups in the Midwest"}]
        out, _ = self.propose({"sector": "Water", "area": "Midwest / Great Lakes",
                               "sub_topics": ["water reuse"]}, messages)
        self.assertEqual(out["region_code"], "midwest_great_lakes")
        self.assertTrue(out["brief"].startswith("Water organizations in the Midwest / Great Lakes."))

    def test_a_regions_adjective_names_it(self):
        # The wording of a real map that lost its area before this rule.
        messages = [{"role": "user", "content": "critical minerals/rare earth element recovery from "
                     "mine waste and by-products (e.g., phosphogypsum). Must be: University; "
                     "Located in the Southeastern United States."}]
        out, _ = self.propose({"sector": "Mining", "area": "Southeast",
                               "sub_topics": ["mine waste", "phosphogypsum"]}, messages)
        self.assertEqual(out["region_code"], "southeast")
        self.assertTrue(out["brief"].startswith("Mining organizations in the Southeast."))

    def test_a_state_must_be_named_as_a_whole_word(self):
        messages = [{"role": "user", "content": "water reuse in Virginia"}]
        out, _ = self.propose({"sector": "Water", "area": "West Virginia",
                               "sub_topics": ["water reuse"]}, messages)
        self.assertEqual(out["area"], "")

    # The next three come from live proposals on saved maps (20 Oct 2026).
    def test_organization_types_are_not_sub_topics(self):
        messages = [{"role": "user", "content": "universities and labs working on water treatment in "
                     "New York, membrane technology. Energy optimization research centers, AI research centers"}]
        out, _ = self.propose({"sector": "Water", "area": "New York", "sub_topics": [
            "membrane technology", "universities and labs", "energy optimization research centers",
            "AI research centers"]}, messages)
        self.assertEqual(out["sub_topics"], ["membrane technology", "energy optimization"])

    def test_a_sector_name_is_not_a_sub_topic(self):
        out = discovery_brief.clean_proposal(
            {"sector": "Water", "area": "", "sub_topics": ["wastewater reuse", "agriculture", "Water"]},
            "wastewater reuse technologies for agriculture", {**SECTORS, "Agriculture": "AGRI"})
        self.assertEqual(out["sub_topics"], ["wastewater reuse"])

    def test_nyc_names_new_york(self):
        messages = [{"role": "user", "content": "research centers working on AI in NYC"}]
        out, _ = self.propose({"sector": "", "area": "New York", "sub_topics": []}, messages)
        self.assertEqual(out["state_code"], "NY")

    def test_real_topics_that_contain_org_like_words_survive(self):
        text = "data center cooling and functional groups in polymer chemistry"
        out = discovery_brief.clean_proposal(
            {"sector": "", "area": "", "sub_topics": ["data center cooling", "functional groups"]},
            text, SECTORS)
        self.assertEqual(out["sub_topics"], ["data center cooling", "functional groups"])

    def test_an_unknown_sector_is_left_for_the_user(self):
        out, _ = self.propose({"sector": "Phosphates", "area": "Florida", "sub_topics": ["phosphogypsum"]})
        self.assertIsNone(out["sector_code"])
        self.assertTrue(out["brief"].startswith("Organizations in Florida."))

    def test_the_tool_offers_only_known_sectors_and_areas(self):
        tool = discovery_brief._tool(list(SECTORS))
        props = tool["input_schema"]["properties"]
        self.assertEqual(props["sector"]["enum"], [*SECTORS, ""])
        self.assertIn("Southeast", props["area"]["enum"])
        self.assertIn("Florida", props["area"]["enum"])


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = RunStore(Path(self.temp.name) / "test.sqlite3")
        self.client = TestClient(app)

    def map_with(self, result, status="done"):
        job = self.store.create("phosphogypsum in Florida")
        self.store.update(job, status=status, result=result, messages=CONVERSATION)
        return job

    def post(self, job):
        proposal = {"brief": "Mining organizations in Florida.\nphosphogypsum", "sector_code": "MINING"}
        with patch("backend.app.map_store", return_value=self.store), \
             patch("backend.app.require_research"), \
             patch("backend.app.propose_discovery", return_value=proposal) as propose:
            return self.client.post(f"/api/map/{job}/discovery-brief"), propose

    def test_an_organization_map_gets_a_proposal_and_keeps_its_status(self):
        job = self.map_with({"entities": {"actor": [{"name": "FIPR Institute"}]}})
        r, propose = self.post(job)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["sector_code"], "MINING")
        self.assertIn("cost", r.json())
        propose.assert_called_once()
        self.assertEqual(self.store.get(job)["status"], "done")

    def test_people_and_event_maps_are_refused_before_any_call(self):
        for kind, key in (("people", "person"), ("events", "event")):
            job = self.map_with({"map_type": kind, "entities": {key: [{"name": "x"}]}})
            r, propose = self.post(job)
            self.assertEqual(r.status_code, 400)
            propose.assert_not_called()

    def test_a_running_or_empty_map_is_refused(self):
        r, propose = self.post(self.map_with({"entities": {"actor": []}}))
        self.assertEqual(r.status_code, 400)
        r, propose = self.post(self.map_with({"entities": {"actor": [{"name": "x"}]}}, status="running"))
        self.assertEqual(r.status_code, 409)
        propose.assert_not_called()


if __name__ == "__main__":
    unittest.main()
