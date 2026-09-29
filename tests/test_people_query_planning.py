"""Offline contracts for paid, bounded people-query planning."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from src.map_agent.people_research import plan_people_queries, people_queries
from src.map_agent.run_store import BudgetStopped


class QueryPlanningTests(unittest.TestCase):
    actor = {"name": "Example University", "website": "https://news.example.edu", "actor_type": "university"}

    def response(self, queries, stop="tool_use"):
        return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(
            type="tool_use", name="submit_people_queries", input={"queries": queries})])

    def test_full_context_and_tracked_call(self):
        queries = ["site:example.edu water faculty Africa", "Example University wastewater publications 2023"]
        run, client, gaps = object(), object(), []
        with patch("src.map_agent.people_research.paid_message", return_value=self.response(queries)) as paid:
            result = plan_people_queries(run, self.actor, "Water reuse", "Find people with Africa projects since 2023", gaps, client)
        self.assertEqual(result, queries)
        self.assertEqual(paid.call_args.args, (client, run, "People query planning"))
        payload = paid.call_args.kwargs
        self.assertTrue(payload["operation_key"].startswith("people-query-plan-v1:"))
        context = json.loads(payload["messages"][0]["content"])
        self.assertEqual(context["people_request"], "Find people with Africa projects since 2023")
        self.assertEqual(context["map_topic"], "Water reuse")
        self.assertEqual(payload["max_tokens"], 700)
        self.assertEqual(gaps, [])

    def test_invalid_plans_fall_back_once(self):
        for queries in ([], ["one"], ["same", "same"], ["x" * 351, "second"],
                        ["site:invented.edu faculty", "other"], [None, "other"]):
            with self.subTest(queries=queries):
                gaps = []
                with patch("src.map_agent.people_research.paid_message", return_value=self.response(queries)) as paid:
                    result = plan_people_queries(object(), self.actor, "Water", "Africa", gaps, object())
                self.assertEqual(result, people_queries(self.actor, "Africa", "Water"))
                paid.assert_called_once()
                self.assertTrue(gaps)

    def test_no_website_cannot_invent_domain(self):
        actor = {"name": "Example University"}
        with patch("src.map_agent.people_research.paid_message", return_value=self.response(["site:example.edu water", "other"])):
            self.assertEqual(plan_people_queries(object(), actor, "Water", "Africa", [], object()),
                             people_queries(actor, "Africa", "Water"))

    def test_budget_stop_propagates_without_fallback(self):
        with patch("src.map_agent.people_research.paid_message", side_effect=BudgetStopped("limit")), patch("src.map_agent.people_research.people_queries") as fallback:
            with self.assertRaises(BudgetStopped):
                plan_people_queries(object(), self.actor, "Water", "Africa", [], object())
            fallback.assert_not_called()

    def test_truncated_plan_falls_back(self):
        with patch("src.map_agent.people_research.paid_message", return_value=self.response(["one", "two"], "max_tokens")):
            gaps = []
            self.assertEqual(plan_people_queries(object(), self.actor, "Water", "Africa", gaps, object()),
                             people_queries(self.actor, "Africa", "Water"))
            self.assertTrue(gaps)
