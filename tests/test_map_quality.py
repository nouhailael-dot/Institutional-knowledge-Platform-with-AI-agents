"""Fixes from a test map on 29 Oct 2026 ("organizations and experts in
sustainable mining ... Northeast"): one of four searches named labs outside the
Northeast, the plan promised researchers it did not search for, generic
engineering programs were accepted, UM6P was unknown, and the page said the
map had reached its budget at $0.95 of $2. No paid calls."""
import unittest
from pathlib import Path

from src.map_agent import planner, select

PAGE = Path(__file__).resolve().parents[1] / "frontend" / "index.html"
flat = lambda text: " ".join(text.split())


class PlannerRuleTests(unittest.TestCase):
    def test_every_query_stays_inside_the_named_area(self):
        rule = flat(planner._SYSTEM)
        self.assertIn("EVERY query stays inside it", rule)
        self.assertIn("never name organizations, labs or places outside it", rule)

    def test_an_organization_search_does_not_promise_people(self):
        rule = flat(planner._SYSTEM)
        self.assertIn("Your summary describes only what THIS search looks for", rule)

    def test_the_planner_knows_who_it_works_for(self):
        rule = flat(planner._SYSTEM)
        self.assertIn("UM6P (Université Mohammed VI Polytechnique, Morocco)", rule)
        self.assertIn("never ask what they are", rule)


class SelectionRuleTests(unittest.TestCase):
    def test_a_general_field_is_not_a_topic_match(self):
        rule = flat(select._SYSTEM)
        self.assertIn("matches the topic only when its own fields show work on that topic", rule)


class BudgetMessageTests(unittest.TestCase):
    def test_the_extra_dollar_is_offered_only_near_or_at_the_budget(self):
        page = PAGE.read_text(encoding="utf-8")
        self.assertIn('runStatus==="budget_stopped"||cost.estimated_usd>=cost.budget_usd*0.8', page)
        self.assertNotIn("cost.can_extend&&html`<div>This map has reached its budget.", page)


if __name__ == "__main__":
    unittest.main()


class FirstMessageTests(unittest.TestCase):
    """The first message of a new map always gets questions first (29 Oct 2026)."""

    def call(self, messages, result=None):
        from types import SimpleNamespace
        from unittest.mock import patch
        reply = SimpleNamespace(content=[SimpleNamespace(type="text", text="Which region should I cover?")])
        with patch.object(planner, "paid_message", return_value=reply) as paid:
            out = planner.map_chat(messages, result=result)
        return out, paid.call_args.kwargs

    def test_the_first_message_can_only_be_answered_with_questions(self):
        out, kwargs = self.call([{"role": "user", "content": "Research centers on phosphate in Florida"}])
        self.assertNotIn("tools", kwargs)
        self.assertIn("FIRST MESSAGE RULE", kwargs["system"])
        self.assertEqual(out, {"status": "reply", "message": "Which region should I cover?"})

    def test_after_an_answer_it_plans_as_usual(self):
        _, kwargs = self.call([{"role": "user", "content": "Partners on phosphate"},
                               {"role": "assistant", "content": "Which region?"},
                               {"role": "user", "content": "Florida, research centers"}])
        self.assertEqual(kwargs["tools"][0]["name"], "submit_plan")
        self.assertNotIn("FIRST MESSAGE RULE", kwargs["system"])

    def test_a_follow_up_on_a_built_map_is_unchanged(self):
        built = {"map_type": "organizations", "entities": {"actor": [{"name": "FIPR Institute"}]}}
        _, kwargs = self.call([{"role": "user", "content": "Which of these are in Florida?"}], result=built)
        self.assertEqual(kwargs["tools"][0]["name"], "submit_plan")
        self.assertNotIn("FIRST MESSAGE RULE", kwargs["system"])
