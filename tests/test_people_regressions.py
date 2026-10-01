"""Regressions for the malformed live response and over-broad people claims."""
import json
import unittest
from unittest.mock import patch
from src.map_agent.people_validation import entity_rows, ExtractionError, affiliation_matches, check_people_evidence
from src.map_agent.people_research import people_queries
import test_people_research as fixtures
ACTOR = fixtures.ACTOR
from src.map_agent.run_store import RunContext

TARGET = "University of Florida Water Institute / Center for African Studies"

class ParsingTests(unittest.TestCase):
    def test_live_nested_json_shape_and_empty_results(self):
        rows = [{"full_name": "Example"}]
        for payload in [{"entities": rows}, {"entities": json.dumps({"entities": rows})}, json.dumps({"entities": rows})]:
            self.assertEqual(entity_rows(payload), rows)
        self.assertEqual(entity_rows({"entities": []}), [])
        for payload in [{"entities": "broken"}, {"people": []}, {"entities": None}]:
            with self.assertRaises(ExtractionError): entity_rows(payload)

    def test_constituent_units_without_parent_or_guest_leakage(self):
        for name in ["University of Florida Water Institute", "University of Florida Center for African Studies", "Center for African Studies"]:
            self.assertTrue(affiliation_matches(name, TARGET),name)
        for name in ["University of Florida", "University of Florida (Department of Biology)", "University of Florida (Carter Conference panelist)", "Bowling Green State University"]:
            self.assertFalse(affiliation_matches(name, TARGET),name)

    def test_edu_scope_and_no_combined_exact_phrase(self):
        queries=people_queries({"name":TARGET,"website":"https://news.clas.ufl.edu/story"}, "Find researchers working on water treatment")
        self.assertIn("site:ufl.edu ",queries[0])
        self.assertNotIn("news.clas",queries[0])
        self.assertNotIn('"'+TARGET+'"',queries[0])
        self.assertIn("site:news.example.co.uk",people_queries({"name":"Lab","website":"https://news.example.co.uk"},"water")[0])

    def test_conference_does_not_establish_africa_projects(self):
        quote="She co-convened the African Waters conference in Florida."
        p={"sources":[{"url":"https://example.edu"}],"criteria_assessment":[{"criterion":"Projects in Africa","status":"supported","explanation":quote,"source_url":"https://example.edu","evidence_quote":quote}]}
        check_people_evidence(p,{"https://example.edu":{"text":quote}})
        self.assertEqual(p["criteria_assessment"][0]["status"],"not established")

    def test_generic_outreach_keeps_map_subject(self):
        actor = {"name": "Mississippi State University", "actor_type": "university"}
        for criteria in ("find potential researchers I can reach out to", "ind potential researchers I can reach out to"):
            queries = people_queries(actor, criteria, "wastewater reuse for agriculture")
            for query in queries:
                self.assertIn("wastewater reuse for agriculture", query)
                self.assertIn(actor["name"], query)
                self.assertNotIn("reach out", query)
                self.assertNotIn("site:", query)
        self.assertIn("published since 2023", people_queries(actor, "Find researchers published since 2023", "water treatment")[0])

    def test_missing_evidence_downgrades_and_real_quote_survives(self):
        quote="She led a pilot project in Morocco on wastewater treatment in 2025."
        row={"criterion":"Projects in Africa","status":"supported","source_url":"https://example.edu","evidence_quote":quote}
        p={"sources":[{"url":"https://example.edu"}],"criteria_assessment":[row,{"criterion":"Recent publications","status":"supported"}]}
        check_people_evidence(p,{"https://example.edu":{"text":quote}})
        self.assertEqual([r["status"] for r in p["criteria_assessment"]],["supported","not established"])

class FailureTests(unittest.TestCase):
    setUp = fixtures.PeopleTests.setUp
    def test_extraction_failure_is_partial_not_empty_success(self):
        from src.map_agent.people_research import research_people
        child,_=self.store.create_people_task(self.parent,"actor","id","people",{})
        with patch("src.map_agent.people_research._collect",return_value=[]), patch("src.map_agent.people_research.extract",side_effect=ExtractionError("bad records")):
            result=research_people(RunContext(self.store,child),ACTOR,"Water","Africa",sources=object())
        self.assertTrue(result["partial"])
        self.assertEqual(len(result["extraction_errors"]),2)
        self.assertFalse(any("No supported people" in g for g in result["coverage_gaps"]))

class OutputLimitTests(unittest.TestCase):
    def test_truncated_tool_input_reports_output_limit(self):
        from types import SimpleNamespace
        from src.map_agent.research import extract
        response = SimpleNamespace(stop_reason='max_tokens', content=[SimpleNamespace(
            type='tool_use', name='submit_entities', input={})])
        with patch('src.map_agent.research.paid_message', return_value=response) as paid:
            with self.assertRaisesRegex(ExtractionError, 'output limit before completing'):
                extract(object(), 'Find additional researchers', {'query':'faculty', 'entity_type':'person'},
                        [{'url':'https://example.edu/profile', 'text':'Profile evidence'}],
                        client=object(), target={'name':'Example Lab'})
        self.assertEqual(paid.call_args.kwargs['max_tokens'], 8192)
        self.assertTrue(paid.call_args.kwargs['operation_key'].startswith('extract-people-v2:'))
        paid.assert_called_once()
