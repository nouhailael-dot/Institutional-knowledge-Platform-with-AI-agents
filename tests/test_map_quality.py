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
