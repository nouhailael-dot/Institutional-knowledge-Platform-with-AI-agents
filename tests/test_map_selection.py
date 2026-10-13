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

    def run_with_limit(self, response, limit):
        reqs = {**REQS, "result_limit": limit}
        entities = candidates()
        with patch.object(select, "paid_message", return_value=response):
            select.apply_request(entities, "water accelerators", reqs, run=object())
        return entities

    def test_a_limit_cut_is_not_reported_as_a_mismatch(self):
        entities = self.run_with_limit(tool_response([{"id": 1, "why": "fits"}], []), limit=1)
        self.assertTrue(entities[1]["_beyond_limit"])
        self.assertEqual(entities[1]["_why_not"], "Not among the top 1 you asked for.")

    def test_the_model_can_mark_a_limit_cut_explicitly(self):
        entities = self.run_with_limit(tool_response(
            [{"id": 1, "why": "fits"}, {"id": 2, "why": "fits"}],
            [{"id": 3, "reason": "fits, but sixth", "fits": True}]), limit=5)
        self.assertTrue(entities[2]["_beyond_limit"])

    def test_a_real_mismatch_keeps_its_reason_even_when_the_limit_is_reached(self):
        entities = self.run_with_limit(tool_response(
            [{"id": 1, "why": "fits"}], [{"id": 2, "reason": "company, not an accelerator"}]), limit=1)
        self.assertFalse(entities[1]["_beyond_limit"])
        self.assertEqual(entities[1]["_why_not"], "company, not an accelerator")
        self.assertTrue(entities[2]["_beyond_limit"])

    def test_a_reason_written_under_why_is_still_kept(self):
        # Observed live: the model used "why" for an excluded item.
        entities, _, _ = self.run_select(tool_response(
            [{"id": 1, "why": "fits"}], [{"id": 2, "why": "company, not an accelerator"}]))
        self.assertEqual(entities[1]["_why_not"], "company, not an accelerator")

    def test_without_a_limit_an_unlisted_candidate_is_not_called_a_limit_cut(self):
        entities, _, _ = self.run_select(tool_response([{"id": 1, "why": "fits"}], []))
        self.assertFalse(entities[1]["_beyond_limit"])
        self.assertEqual(entities[1]["_why_not"], "No reason given.")

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


class HandoffTests(unittest.TestCase):
    """The Ask -> Build the Map condenser may only take filters from the user."""

    def test_database_answers_are_marked_as_context_and_a_stronger_model_is_used(self):
        from src import generate
        captured = {}
        def create(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="submit_handoff",
                input={"in_scope": True, "topic": "brackish groundwater desalination"})])
        client = SimpleNamespace(messages=SimpleNamespace(create=create))
        history = [{"q": "What about New Mexico?", "a": "The Texas hub has two labs.",
                    "sources": ["Texas A&M Water Programs"]}]
        with patch.object(generate, "_get_client", return_value=client):
            generate.ask_handoff(history)
        convo = captured["messages"][0]["content"]
        self.assertIn("USER: What about New Mexico?", convo)
        self.assertIn("DATABASE ANSWER (context only, never a filter): The Texas hub", convo)
        self.assertEqual(captured["model"], generate.HANDOFF_MODEL)
        self.assertIn("ONLY from what the USER wrote", captured["system"])


class FollowUpTests(unittest.TestCase):
    """A follow-up on a built map judges only its newcomers, against itself."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from src.map_agent.run_store import RunStore, RunContext
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = RunStore(Path(temp.name) / "runs.sqlite3")
        self.id = self.store.create("universities in New York")
        self.store.claim(self.id, "running", "Research", ("draft",))
        self.run = RunContext(self.store, self.id)

    def build(self, description, query, rows, select_fn):
        from src.map_agent import research
        rows = [{**row, "_entity_type": "actor"} for row in rows]   # as extract() tags them
        plan = {"tasks": [{"entity_type": "actor", "query": query}],
                "requirements": {"hard_filters": [description], "preferences": [], "result_limit": 0}}
        with patch.object(research, "_collect", return_value=[{"url": "u", "text": "t"}]), \
             patch.object(research, "extract", return_value=(rows, "")) as extract, \
             patch.object(research, "apply_request", side_effect=select_fn) as selection:
            research.build_controlled_map(description, plan, self.run)
        return extract, selection

    @staticmethod
    def rank_all(entities, request, requirements, run=None):
        for i, e in enumerate(entities, 1):
            select._mark(e, True, rank=i, why="fits")
        return {"selected": entities, "rest": [], "note": "", "outcome": select.APPLIED}

    @staticmethod
    def reject_all(entities, request, requirements, run=None):
        for e in entities:
            select._mark(e, False, why_not="not a national laboratory")
        return {"selected": [], "rest": entities, "note": "", "outcome": select.NONE_MATCHED}

    def test_earlier_results_keep_their_judgement(self):
        universities = [{"name": "Columbia Energy Lab"}, {"name": "NYU Grid Lab"}]
        self.build("universities in New York", "NY university energy labs", universities, self.rank_all)

        extract, selection = self.build("also national labs", "national labs building energy",
                                        [{"name": "Brookhaven National Laboratory"}], self.reject_all)

        judged = [e["name"] for e in selection.call_args.args[0]]
        self.assertEqual(judged, ["Brookhaven National Laboratory"])
        self.assertEqual(selection.call_args.args[1], "also national labs")
        self.assertEqual(extract.call_args.args[1], "also national labs")

        found = {e["name"]: e for e in self.store.cached(self.id, "workflow")["found"]}
        self.assertTrue(found["Columbia Energy Lab"]["_selected"])
        self.assertEqual(found["NYU Grid Lab"]["_rank"], 2)
        self.assertFalse(found["Brookhaven National Laboratory"]["_selected"])

    def test_follow_up_matches_rank_after_earlier_ones(self):
        self.build("universities in New York", "q1", [{"name": "A Lab"}, {"name": "B Lab"}], self.rank_all)
        self.build("also national labs", "q2", [{"name": "C National Lab"}], self.rank_all)
        state = self.store.cached(self.id, "workflow")
        ranks = {e["name"]: e["_rank"] for e in state["found"]}
        self.assertEqual(ranks, {"A Lab": 1, "B Lab": 2, "C National Lab": 3})
        self.assertEqual(state["description"], "universities in New York")
        self.assertIn("1 of the 1 found by your follow-up", state["selection_note"])


if __name__ == "__main__":
    unittest.main()
