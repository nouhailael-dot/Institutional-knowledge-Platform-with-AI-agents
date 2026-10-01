"""Offline quality-first follow-up contracts."""
import unittest
from unittest.mock import patch, Mock
import test_people_research as fixtures
from src.map_agent.people_research import research_people, people_queries, merge_people, _collect
from src.map_agent.run_store import RunContext


class FollowupTests(unittest.TestCase):
    setUp = fixtures.PeopleTests.setUp

    def person(self, complete=False):
        return {"full_name": "Example Person", "organization_name": "Example Lab", "_entity_type": "person",
                "sources": fixtures.ACTOR["sources"], "criteria_assessment": [
                    {"criterion": "Water treatment", "status": "supported"},
                    {"criterion": "Africa projects", "status": "supported" if complete else "not established"}]}

    def test_investigates_missing_criterion_and_stops_when_supported(self):
        child,_=self.store.create_people_task(self.parent,"actor","id","people",{})
        pages=[[{"url": f"https://example.edu/{i}", "text": "Example Person evidence", "kind":"page"}] for i in range(3)]
        with patch("src.map_agent.people_research._collect",side_effect=pages) as collect, patch("src.map_agent.people_research.extract",side_effect=[([self.person()],""),([self.person()],""),([self.person(True)],"")]) as extract:
            result=research_people(RunContext(self.store,child),fixtures.ACTOR,"Water","Water and Africa",sources=object())
        self.assertEqual(collect.call_count,3)
        self.assertIn('"Example Person"',collect.call_args.args[1])
        self.assertIn("Africa projects",collect.call_args.args[1])
        self.assertEqual(result["people"][0]["research_status"],"Supported on assessed criteria")
        self.assertIn("Investigate only Example Person",extract.call_args.args[1])

    def test_no_new_evidence_skips_paid_followup_extraction(self):
        child,_=self.store.create_people_task(self.parent,"actor","id","people",{})
        pages=[{"url":"https://example.edu/profile","text":"Example Person evidence","kind":"page"}]
        with patch("src.map_agent.people_research._collect",return_value=pages) as collect, patch("src.map_agent.people_research.extract",return_value=([self.person()],"")) as extract:
            result=research_people(RunContext(self.store,child),fixtures.ACTOR,"Water","Africa",sources=object())
        self.assertEqual(collect.call_count,3)
        self.assertEqual(extract.call_count,2)
        self.assertTrue(any("no new evidence" in g for g in result["coverage_gaps"]))

    def test_merge_preserves_supported_criteria_and_adds_new_evidence(self):
        merged=merge_people([self.person(True)],[self.person()])
        self.assertEqual(merged[0]["research_status"],"Supported on assessed criteria")
        self.assertEqual(len(merged[0]["sources"]),1)

    def test_queries_adapt_to_government_and_company(self):
        q=people_queries({"name":"Bureau","website":"https://usbr.gov","actor_type":"government agency"},"water")[0]
        self.assertIn("engineers",q)
        self.assertNotIn("faculty",q)
        self.assertIn("R&D",people_queries({"name":"Example","website":"https://example.com","actor_type":"company"},"water")[0])

    def test_profiles_are_read_before_generic_news(self):
        sources=Mock()
        sources.search.return_value=[{"url":"https://example.edu/news","text":"announcement"},
            {"url":"https://example.edu/staff/profile","text":"water project research"}]
        sources.page.side_effect=lambda url:{"url":url,"text":"read page","kind":"page"}
        _collect(sources,"water researcher",[],max_pages=1)
        sources.page.assert_called_once_with("https://example.edu/staff/profile")
