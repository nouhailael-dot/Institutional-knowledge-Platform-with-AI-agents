"""Offline selection behaviour: outcomes, exclusion reasons, and replay keys."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.map_agent import select

REQS = {"hard_filters": ["accelerators"], "preferences": [], "result_limit": 0}


def tool_response(selected, excluded, stop_reason="tool_use"):
    block = SimpleNamespace(type="tool_use", name="submit_selection",
                            input={"selected": selected, "excluded": excluded})
    return SimpleNamespace(content=[block], stop_reason=stop_reason)


def thinking_only():
    return SimpleNamespace(content=[SimpleNamespace(type="thinking", name=None)],
                           stop_reason="max_tokens")


def candidates():
    return [{"name": "Accelerate H2O", "_entity_type": "actor"},
            {"name": "Fathom", "_entity_type": "actor"},
            {"name": "CleanTX", "_entity_type": "actor"}]


class SelectionTests(unittest.TestCase):
    def run_select(self, response, entities=None, request="water accelerators"):
        entities = entities or candidates()
        with patch.object(select, "paid_message", return_value=response) as paid:
            result = select.apply_request(entities, request, REQS, run=object())
        return entities, result, paid

    def test_excluded_candidates_carry_their_reason(self):
        entities, result, _ = self.run_select(tool_response(
            [{"id": 1, "why": "water accelerator in San Antonio"}],
            [{"id": 2, "reason": "company, not an accelerator"},
             {"id": 3, "reason": "industry association"}]))
        self.assertEqual(result["outcome"], select.APPLIED)
        self.assertEqual(entities[0]["_rank"], 1)
        self.assertEqual(entities[1]["_why_not"], "company, not an accelerator")
        self.assertFalse(entities[2]["_selected"])

    def test_a_candidate_the_model_forgot_is_still_marked(self):
        entities, _, _ = self.run_select(tool_response([{"id": 1, "why": "fits"}], []))
        self.assertEqual(entities[1]["_why_not"], "No reason given.")

    def test_nothing_matching_is_reported_not_disguised(self):
        entities, result, _ = self.run_select(tool_response(
            [], [{"id": i, "reason": "outside the region"} for i in (1, 2, 3)]))
        self.assertEqual(result["outcome"], select.NONE_MATCHED)
        self.assertTrue(all(e["_selected"] is False for e in entities))
        self.assertIn("None of the 3", result["note"])

    def test_running_out_of_tokens_fails_open_and_says_why(self):
        entities, result, _ = self.run_select(thinking_only())
        self.assertEqual(result["outcome"], select.FAILED)
        self.assertTrue(all(e["_selected"] is True and e["_rank"] is None for e in entities))
        self.assertIn("output limit", result["note"])

    def test_no_requirements_skips_the_call(self):
        with patch.object(select, "paid_message") as paid:
            result = select.apply_request(candidates(), "water", {}, run=object())
        paid.assert_not_called()
        self.assertEqual(result["outcome"], select.NO_REQUIREMENTS)

    def test_budget_and_effort_reach_the_api(self):
        _, _, paid = self.run_select(tool_response([{"id": 1, "why": "fits"}], []))
        kwargs = paid.call_args.kwargs
        self.assertEqual(kwargs["max_tokens"], select.MAX_TOKENS)
        self.assertGreaterEqual(select.MAX_TOKENS, 8000)
        self.assertEqual(kwargs["output_config"], {"effort": "medium"})

    def test_new_candidates_are_judged_again_not_replayed(self):
        _, _, first = self.run_select(tool_response([{"id": 1, "why": "fits"}], []))
        more = candidates() + [{"name": "Texas National Lab", "_entity_type": "actor"}]
        _, _, second = self.run_select(tool_response([{"id": 1, "why": "fits"}], []), more)
        _, _, again = self.run_select(tool_response([{"id": 1, "why": "fits"}], []))
        key = lambda paid: paid.call_args.kwargs["operation_key"]
        self.assertNotEqual(key(first), key(second))
        self.assertEqual(key(first), key(again))


if __name__ == "__main__":
    unittest.main()
