"""Offline task, API and research tests. No real model/search calls."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.app import app
from src.map_agent.run_store import RunStore, RunContext, MapStopped
from src.map_agent.people_research import research_people, people_queries

ACTOR = {"name": "Example Lab", "website": "https://example.edu",
         "sources": [{"url": "https://example.edu/team"}], "_entity_type": "actor"}


class PeopleTests(unittest.TestCase):
    def setUp(self):
        planner = patch("src.map_agent.people_research.plan_people_queries",
                        side_effect=lambda run, actor, topic, criteria, gaps, client=None:
                            people_queries(actor, criteria, topic))
        planner.start()
        self.addCleanup(planner.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = RunStore(Path(self.temp.name)/"test.sqlite3")
        self.parent = self.store.create("Water")
        self.store.update(self.parent, status="done", result={"entities": {"actor": [ACTOR]}})
        self.client = TestClient(app)
        self.payload = {"actor_name": ACTOR["name"], "website": ACTOR["website"],
                        "criteria": "Researchers with Africa projects", "request_key": "unique", "approve": True}

    def test_requires_approval_and_uses_saved_actor(self):
        with patch("backend.app.map_store", return_value=self.store), patch("backend.app.require_research"), patch("backend.app._MAP_POOL.submit") as submit:
            for fields in [{"approve": False}, {"actor_name": "Invented"}, {"criteria": " "}]:
                r=self.client.post(f"/api/map/{self.parent}/people",json={**self.payload,**fields})
                self.assertEqual(r.status_code,400)
            submit.assert_not_called()

    def test_duplicate_requests_only_dispatch_once_and_budget_is_separate(self):
        with patch("backend.app.map_store", return_value=self.store), patch("backend.app.require_research"), patch("backend.app._MAP_POOL.submit") as submit:
            first=self.client.post(f"/api/map/{self.parent}/people",json=self.payload).json()
            second=self.client.post(f"/api/map/{self.parent}/people",json=self.payload).json()
            self.assertEqual(first["id"],second["id"])
            submit.assert_called_once()
            self.assertEqual(first["cost"]["budget_usd"],3)
            self.assertEqual(self.store.get(self.parent)["cost"]["budget_usd"],2)
            conflict=self.client.post(f"/api/map/{self.parent}/people",json={**self.payload,"request_key":"other"})
            self.assertEqual(conflict.status_code,409)
            history=self.client.get(f"/api/map/{self.parent}/people",params={"actor_name":ACTOR["name"],"website":ACTOR["website"]}).json()
            self.assertEqual(len(history["tasks"]),1)
            self.assertEqual(len(self.store.recent()),1)

    def test_mock_research_saves_people_criteria_and_evidence(self):
        child,_=self.store.create_people_task(self.parent,"actor","id","people",{})
        run=RunContext(self.store,child)
        person={"_entity_type":"person","full_name":"Researcher", "organization_name":ACTOR["name"],"sources":ACTOR["sources"]}
        with patch("src.map_agent.people_research._collect",return_value=[]), patch("src.map_agent.people_research.extract",return_value=([person],"Africa experience not established")) as extract:
            result=research_people(run,ACTOR,"Water","Africa projects",sources=object())
        self.assertEqual(len(result["people"]),1)
        self.assertFalse(result["partial"])
        self.assertIn("Africa projects",extract.call_args.args[1])
        self.assertEqual(self.store.get(child)["result"]["people"][0]["sources"],ACTOR["sources"])
        self.assertEqual(self.store.get(child)["cost"]["estimated_usd"],0)

    def test_stop_blocks_research(self):
        child,_=self.store.create_people_task(self.parent,"actor","id","people",{})
        self.store.stop(child)
        with patch("src.map_agent.people_research._collect") as collect:
            with self.assertRaises(MapStopped):
                research_people(RunContext(self.store,child),ACTOR,"Water","Africa",sources=object())
            collect.assert_not_called()

    def test_missing_or_unsupported_website_searches_by_saved_name(self):
        for website in (None, "", "https://unrelated.example"):
            with self.subTest(website=website):
                actor = {**ACTOR, "website": website,
                         "sources": [{"url": "https://reports.example/study"}]}
                child,_ = self.store.create_people_task(self.parent,"actor",str(website),"people",{})
                with patch("src.map_agent.people_research._collect", return_value=[]) as collect, patch("src.map_agent.people_research.extract", return_value=([], "")) as extract:
                    result = research_people(RunContext(self.store,child),actor,"Water","Researchers",sources=object())
                self.assertEqual(collect.call_count, 2)
                for call in collect.call_args_list:
                    self.assertIn(ACTOR["name"], call.args[1])
                    self.assertNotIn("site:", call.args[1])
                self.assertEqual(extract.call_args.kwargs["target"], {"name": ACTOR["name"], "website": ""})
                self.assertTrue(any("searched by organization name" in gap for gap in result["coverage_gaps"]))
                self.assertEqual(actor["website"], website)
                self.store.update(child, status="done")
