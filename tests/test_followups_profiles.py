"""A separate list per follow-up, and people's profile links (asked for on
20 Oct 2026). No paid calls: search and the model are stubbed."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from src.map_agent import research, select
from src.map_agent.run_store import RunContext, RunStore

URL = "https://example.edu/people"


class Block(SimpleNamespace):
    def model_dump(self, **kwargs):
        return vars(self)


def reply(tool, data):
    return SimpleNamespace(id="fake", stop_reason="tool_use",
                           usage=Block(input_tokens=100, output_tokens=20),
                           content=[Block(type="tool_use", name=tool, input=data)])


def person(name, org="University of Florida"):
    return {"full_name": name, "organization_name": org, "title": "Professor",
            "sources": [{"url": URL, "supports": "Role"}]}


class FollowUpTests(unittest.TestCase):
    """A people map, then a follow-up: the newcomer gets its own list."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        store = RunStore(Path(temp.name) / "runs.sqlite3")
        self.run_id = store.create("phosphogypsum experts")
        self.store = store
        self.client = Mock()
        self.client.with_options.return_value = self.client
        self.client.messages.count_tokens.return_value = SimpleNamespace(input_tokens=100)
        self.people = [person("Sam Example"), person("Ana Other")]
        self.client.messages.create.side_effect = self.respond

    def respond(self, **kwargs):
        if kwargs["tools"][0]["name"] == "submit_selection":
            return reply("submit_selection", {"selected": [{"id": 1, "why": "Expert"}], "excluded": []})
        return reply("submit_entities", {"entities": self.people})

    def build(self, description, plan):
        self.store.claim(self.run_id, "running", "Research", ("draft", "done"))
        run = RunContext(self.store, self.run_id)
        provider = Mock()
        provider.search.return_value = [{"url": URL, "text": "Faculty list", "kind": "search_snippet"}]
        fetcher = Mock(return_value={"url": URL, "text": "Faculty list", "kind": "page"})
        sources = research.ResearchSources(run, provider, fetcher, robots=lambda url: True)
        with patch.object(select, "_get_client", return_value=self.client):
            result = research.build_controlled_map(description, plan, run, sources, self.client)
        self.store.finish(self.run_id, attempt=run.attempt)
        return result

    def test_a_follow_up_keeps_its_own_list_and_the_original_is_untouched(self):
        first = self.build("phosphogypsum experts", {
            "map_type": "people", "requirements": {"hard_filters": ["expert"]},
            "tasks": [{"entity_type": "person", "query": "phosphogypsum experts"}]})
        self.assertEqual(first["rounds"], ["phosphogypsum experts"])
        self.assertNotIn("_found_by", first["entities"]["person"][0])   # one list: no label
        # The follow-up finds one person already on the map and one new one.
        self.people = [person("Sam Example"), person("Lee Newcomer", "Texas A&M University")]
        second = self.build("what about Texas?", {
            "map_type": "people", "requirements": {"hard_filters": ["expert"]},
            "tasks": [{"entity_type": "person", "query": "phosphogypsum experts Texas"}]})
        self.assertEqual(second["rounds"], ["phosphogypsum experts", "what about Texas?"])
        by_name = {p["full_name"]: p for p in second["entities"]["person"]}
        self.assertEqual(by_name["Sam Example"]["_round"], 1)            # found again: stays put
        self.assertEqual(by_name["Lee Newcomer"]["_round"], 2)
        self.assertEqual(by_name["Lee Newcomer"]["_found_by"], "Follow-up 1: what about Texas?")
        self.assertEqual(by_name["Ana Other"]["_found_by"], "Original request")

    def test_each_search_is_placed_after_the_message_that_started_it(self):
        # The page reads like a chat (28 Oct 2026): results sit after their message,
        # and a follow-up can name what it found again.
        plan = {"map_type": "people", "requirements": {"hard_filters": ["expert"]},
                "tasks": [{"entity_type": "person", "query": "phosphogypsum experts"}]}
        first = self.build("phosphogypsum experts", {**plan, "after_message": 4})
        self.assertEqual(first["round_after"], [4])
        self.people = [person("Sam Example"), person("Lee Newcomer", "Texas A&M University")]
        second = self.build("what about Texas?", {**plan, "after_message": 8,
                            "tasks": [{"entity_type": "person", "query": "phosphogypsum experts Texas"}]})
        self.assertEqual(second["round_after"], [4, 8])
        by_name = {p["full_name"]: p for p in second["entities"]["person"]}
        self.assertEqual(by_name["Sam Example"]["_seen_in"], [1, 2])
        self.assertEqual(by_name["Ana Other"]["_seen_in"], [1])
        self.assertEqual(by_name["Lee Newcomer"]["_seen_in"], [2])

    def test_a_map_saved_without_positions_keeps_its_results_together(self):
        plan = {"map_type": "people", "requirements": {"hard_filters": ["expert"]},
                "tasks": [{"entity_type": "person", "query": "phosphogypsum experts"}]}
        self.build("phosphogypsum experts", plan)
        state = self.store.cached(self.run_id, "workflow")
        state.pop("round_after")                     # as saved before 28 Oct 2026
        self.store.checkpoint_workflow(self.run_id, state, research._visible(state))
        second = self.build("what about Texas?", {**plan, "after_message": 6})
        self.assertEqual(second["round_after"], [None, 6])


class ProfileTests(unittest.TestCase):
    HITS = [{"url": "https://www.linkedin.com/in/timothy-townsend", "title": "Timothy Townsend - University of Florida"},
            {"url": "https://www.essie.ufl.edu/people/timothy-townsend/", "title": "Timothy Townsend | ESSIE",
             "text": "Professor, University of Florida"},
            {"url": "https://www.linkedin.com/in/tim-townsend-42", "title": "Timothy Townsend - Acme Corp"},
            {"url": "https://osti.gov/biblio/123", "title": "Rare earths recovery",
             "text": "Timothy Townsend, University of Florida"}]

    def test_the_organization_page_and_the_right_linkedin_are_kept(self):
        self.assertEqual(research.profile_links(self.HITS, "Timothy Townsend", "University of Florida"),
                         ("https://www.essie.ufl.edu/people/timothy-townsend/",
                          "https://www.linkedin.com/in/timothy-townsend"))

    def test_the_name_alone_is_never_enough(self):
        self.assertFalse(research.same_person({"title": "Timothy Townsend - Acme Corp"},
                                              "Timothy Townsend", "University of Florida"))
        self.assertFalse(research.same_person({"title": "Townsend lab, University of Florida"},
                                              "Timothy Townsend", "University of Florida"))
        self.assertFalse(research.same_person({"title": "Timothy Townsend, University of Florida"},
                                              "Townsend", "University of Florida"))   # one word: no
        self.assertTrue(research.same_person({"title": "José Núñez - Universidad de Texas"},
                                             "Jose Nunez", "University of Texas"))  # accents ignored

    def test_one_search_per_kept_person_at_most_eight(self):
        found = [{"_entity_type": "person", "full_name": f"Person {chr(65 + i)} Example",
                  "organization_name": "University of Florida", "_rank": i + 1} for i in range(10)]
        found.append({"_entity_type": "person", "full_name": "Left Out", "organization_name": "X",
                      "_selected": False})
        sources = MagicMock()
        sources.search.return_value = []
        state = {"found": found, "gaps": []}
        list(research.find_people_profiles(state, sources))
        self.assertEqual(sources.search.call_count, research.PROFILE_CHECKS)
        self.assertEqual(sources.search.call_args_list[0].args[0], '"Person A Example" University of Florida')
        self.assertIn("No profile page or LinkedIn confirmed for Person A Example", state["gaps"][0])

    def test_a_confirmed_link_is_stored(self):
        found = [{"_entity_type": "person", "full_name": "Timothy Townsend",
                  "organization_name": "University of Florida", "profile_url": "https://osti.gov/x"}]
        sources = MagicMock()
        sources.search.return_value = self.HITS
        list(research.find_people_profiles({"found": found, "gaps": []}, sources))
        self.assertEqual(found[0]["profile_url"], "https://www.essie.ufl.edu/people/timothy-townsend/")
        self.assertEqual(found[0]["linkedin_url"], "https://www.linkedin.com/in/timothy-townsend")


if __name__ == "__main__":
    unittest.main()
