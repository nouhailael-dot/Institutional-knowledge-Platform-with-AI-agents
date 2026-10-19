"""Maps about organizations, people or events: planning, research, display data, export."""
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.map_agent import planner, select
from src.map_agent.entity_schemas import submit_entities_tool
from src.map_agent.research import _date_status, _um6p_ocp_check, build_controlled_map
from src.map_agent.run_store import RunContext, RunStore
from src.map_agent.search_backend import ResearchSources


class Block(SimpleNamespace):
    def model_dump(self, **kwargs):
        return vars(self)


def reply(tool, data):
    return SimpleNamespace(id="fake", stop_reason="tool_use",
                           usage=Block(input_tokens=100, output_tokens=20),
                           content=[Block(type="tool_use", name=tool, input=data)])


PLAN_TEXT = SimpleNamespace(content=[Block(type="text", text="Organizations, people or events?")])


class PlannerTests(unittest.TestCase):
    def chat(self, plan, result=None):
        with patch.object(planner, "paid_message", return_value=plan):
            return planner.map_chat([{"role": "user", "content": "phosphogypsum"}], result=result)

    def test_the_plan_must_name_one_map_type(self):
        schema = planner._SUBMIT_PLAN["input_schema"]
        self.assertIn("map_type", schema["required"])
        self.assertEqual(schema["properties"]["map_type"]["enum"], ["organizations", "people", "events"])

    def test_tasks_of_another_type_are_dropped(self):
        out = self.chat(reply("submit_plan", {
            "map_type": "people", "summary": "Experts.", "requirements": {},
            "tasks": [{"entity_type": "person", "query": "phosphogypsum experts", "focus": ""},
                      {"entity_type": "actor", "query": "phosphogypsum labs", "focus": ""}]}))
        self.assertEqual(out["map_type"], "people")
        self.assertEqual([t["entity_type"] for t in out["tasks"]], ["person"])

    def test_a_built_map_keeps_its_type(self):
        built = {"map_type": "people", "entities": {"person": [{"full_name": "Sam Example"}]}}
        out = self.chat(reply("submit_plan", {
            "map_type": "organizations", "summary": "Labs.", "requirements": {},
            "tasks": [{"entity_type": "actor", "query": "phosphogypsum labs", "focus": ""}]}), built)
        self.assertEqual(out["status"], "reply")
        self.assertIn("covers people", out["message"])

    def test_asking_which_type_is_a_reply_not_a_plan(self):
        self.assertEqual(self.chat(PLAN_TEXT)["status"], "reply")
        self.assertIn("Ask which single type the map should be about ONLY when",
                      " ".join(planner._SYSTEM.split()))

    def test_named_types_are_planned_without_asking(self):
        rule = " ".join(planner._SYSTEM.split())
        self.assertIn('"Find experts on X in Y" is a people map; plan it immediately.', rule)
        for word in ("experts", "researchers", "conferences", "workshops", "universities"):
            self.assertIn(word, rule)


class DateAndEvidenceTests(unittest.TestCase):
    def test_the_planner_is_told_todays_date_and_to_search_current_years(self):
        with patch.object(planner, "paid_message", return_value=PLAN_TEXT) as call:
            planner.map_chat([{"role": "user", "content": "conferences next year"}])
        system = call.call_args.kwargs["system"]
        self.assertIn(f"TODAY'S DATE is {date.today().isoformat()}", system)
        self.assertIn(f"{date.today().year} or {date.today().year + 1}", system)

    def test_old_affiliation_evidence_is_marked_unconfirmed(self):
        from src.map_agent.research import _affiliation_note
        today = date(2026, 10, 16)
        cases = {"2017": "Shown in 2017 — unconfirmed, may have changed", "2024": "Shown in 2024",
                 "2023": "Shown in 2023", "": "Source undated"}
        for year, note in cases.items():
            person = {"affiliation_evidence_year": year}
            _affiliation_note(person, today)
            self.assertEqual(person["affiliation_note"], note, year)

    def test_selection_sees_and_is_told_about_both_rules(self):
        self.assertIn('"date unconfirmed" does not meet a requirement about when', select._SYSTEM)
        self.assertIn('affiliation is marked "unconfirmed"', select._SYSTEM)
        person = {"_entity_type": "person", "full_name": "A",
                  "affiliation_note": "Shown in 2017 — unconfirmed, may have changed"}
        event = {"_entity_type": "event", "name": "B", "date_status": "date unconfirmed"}
        self.assertIn("unconfirmed, may have changed", select._render(person, 1))
        self.assertIn("date unconfirmed", select._render(event, 2))


class PeopleQualityTests(unittest.TestCase):
    def test_only_spelled_out_full_names_are_kept(self):
        from src.map_agent.research import _full_name_ok
        for name in ("Haijun Liang", "David W. DePaoli", "Sicheng Li", "Timothy Townsend"):
            self.assertTrue(_full_name_ok(name), name)
        for name in ("Zhang (given name not specified in source)", "Dr. Zhang", "H. Liang", "Townsend"):
            self.assertFalse(_full_name_ok(name), name)

    def test_publications_and_news_are_not_profiles(self):
        from src.map_agent.research import _profile_ok
        not_profiles = {
            "Haijun Liang": "https://www.ornl.gov/publications/rare-earths-recovery-and-gypsum-upgrade-from-florida-phosphogypsum/",
            "Timothy Townsend": "https://techxplore.com/news/2023-07-era-florida-phosphates-rare-earth.html",
            "Sicheng Li": "https://pubs.acs.org/doi/10.1021/acs.iecr.1c03576"}
        for name, url in not_profiles.items():
            self.assertFalse(_profile_ok(url, name), url)
        profiles = {
            "Timothy Townsend": "https://www.essie.ufl.edu/people/name/timothy-townsend/",
            "Haijun Liang": "https://floridapoly.edu/faculty/liang",
            "Patrick Zhang": "https://orcid.org/0000-0002-1825-0097"}
        for name, url in profiles.items():
            self.assertTrue(_profile_ok(url, name), url)


class EventFieldTests(unittest.TestCase):
    def test_a_full_date_is_checked_against_today(self):
        today = date(2026, 10, 16)
        for raw, status in (("2026-12-01", "upcoming"), ("2025-05-01", "past"), ("", "date unconfirmed")):
            event = {"next_date": raw, "date_status": "upcoming"}
            _date_status(event, today)
            self.assertEqual(event["date_status"], status, raw)

    def test_a_partial_date_keeps_the_stated_status(self):
        event = {"next_date": "Spring 2027", "date_status": "upcoming"}
        _date_status(event, date(2026, 10, 16))
        self.assertEqual(event["date_status"], "upcoming")

    def test_a_um6p_ocp_connection_needs_a_supplied_source(self):
        url = "https://example.edu/news"
        kept = {"um6p_ocp_status": "found", "um6p_ocp_detail": "UM6P partner", "um6p_ocp_source": url}
        _um6p_ocp_check(kept, {url: {}})
        self.assertEqual(kept["um6p_ocp_status"], "found")
        invented = {"um6p_ocp_status": "found", "um6p_ocp_detail": "UM6P partner",
                    "um6p_ocp_source": "https://elsewhere.example"}
        _um6p_ocp_check(invented, {url: {}})
        self.assertEqual(invented["um6p_ocp_status"], "not found in what's been read")
        self.assertNotIn("um6p_ocp_detail", invented)


class SchemaTests(unittest.TestCase):
    def test_the_find_people_search_on_organization_cards_is_unchanged(self):
        tool = submit_entities_tool("person")
        item = tool["input_schema"]["properties"]["entities"]["items"]["properties"]
        self.assertIn("criteria_assessment", item)
        self.assertNotIn("expertise", item)
        self.assertIn("Best matching persons", tool["input_schema"]["properties"]["entities"]["description"])

    def test_people_maps_collect_the_light_pull(self):
        item = submit_entities_tool("map_person")["input_schema"]["properties"]["entities"]["items"]
        for field in ("full_name", "title", "organization_name", "organization_location", "expertise",
                      "profile_url", "work_evidence", "um6p_ocp_status", "email", "sources"):
            self.assertIn(field, item["properties"])
        self.assertIn("ONLY if the request explicitly asks", item["properties"]["email"]["description"])

    def test_events_follow_the_light_pull(self):
        props = submit_entities_tool("event")["input_schema"]["properties"]["entities"]["items"]["properties"]
        for field in ("sector", "organizer", "date_status", "match_explanation", "um6p_ocp_status"):
            self.assertIn(field, props)
        for dropped in ("sponsoring_orgs", "expected_attendance", "access_type"):
            self.assertNotIn(dropped, props)


URL = "https://example.edu/people"
PEOPLE = [{"full_name": "Sam Example", "title": "Professor", "organization_name": "Dept. of Chemistry",
           "organization_location": "Gainesville, FL", "expertise": "phosphogypsum",
           "sources": [{"url": URL, "supports": "Role"}]},
          {"full_name": "Ana Other", "title": "Director", "organization_name": "Other Lab",
           "organization_location": "Boston, MA", "sources": [{"url": URL, "supports": "Role"}]},
          {"full_name": "Zhang (given name not specified in source)", "organization_name": "University of Florida",
           "sources": [{"url": URL, "supports": "Role"}]}]


class PeopleMapTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = RunStore(Path(temp.name) / "runs.sqlite3")
        self.id = self.store.create("phosphogypsum experts")
        self.store.claim(self.id, "running", "Research", ("draft",))
        self.run = RunContext(self.store, self.id)
        provider = Mock()
        provider.search.return_value = [{"url": URL, "text": "Sam Example, professor of chemistry.",
                                         "kind": "search_snippet"}]
        fetcher = Mock(return_value={"url": URL, "text": "Sam Example, professor of chemistry.", "kind": "page"})
        self.sources = ResearchSources(self.run, provider, fetcher)
        self.client = Mock()
        self.client.with_options.return_value = self.client
        self.client.messages.count_tokens.return_value = SimpleNamespace(input_tokens=100)
        self.client.messages.create.side_effect = self.respond

    def respond(self, **kwargs):
        if kwargs["tools"][0]["name"] == "submit_selection":
            return reply("submit_selection", {"selected": [{"id": 1, "why": "Southeast expert"}],
                                              "excluded": [{"id": 2, "reason": "in Boston"}]})
        self.extraction = kwargs
        return reply("submit_entities", {"entities": PEOPLE})

    def build(self, plan):
        with patch.object(select, "_get_client", return_value=self.client):
            return build_controlled_map("phosphogypsum experts in the Southeast", plan, self.run,
                                        self.sources, self.client)

    def test_people_are_searched_directly_and_keep_their_own_selection(self):
        result = self.build({"map_type": "people", "requirements": {"hard_filters": ["Southeast US"]},
                             "tasks": [{"entity_type": "person", "query": "phosphogypsum experts"}]})
        self.assertEqual(result["map_type"], "people")
        people = {p["full_name"]: p for p in result["entities"]["person"]}
        self.assertTrue(people["Sam Example"]["_selected"])
        self.assertFalse(people["Ana Other"]["_selected"])
        self.assertEqual(people["Sam Example"]["organization_name"], "Dept. of Chemistry")
        self.assertEqual(result["entities"]["actor"], [])
        self.assertEqual(len(people), 2)
        self.assertTrue(any("did not give their full name" in g for g in result["coverage_gaps"]))
        tool = self.extraction["tools"][0]["input_schema"]["properties"]["entities"]["items"]
        self.assertIn("expertise", tool["properties"])
        self.assertIn("map of PEOPLE", self.extraction["system"])
        stages = {c["stage"] for c in self.store.get(self.id)["cost"]["calls"]}
        self.assertIn("People extraction", stages)
        self.assertNotIn("Event extraction", stages)

    def test_people_maps_export_their_people(self):
        from openpyxl import load_workbook
        from src.map_agent.export import to_xlsx
        result = self.build({"map_type": "people", "requirements": {"hard_filters": ["Southeast US"]},
                             "tasks": [{"entity_type": "person", "query": "phosphogypsum experts"}]})
        cells = [str(c.value) for sheet in load_workbook(io.BytesIO(to_xlsx(result)))
                 for row in sheet for c in row]
        self.assertIn("Sam Example", cells)
        self.assertNotIn("Ana Other", cells)
        self.assertIn("Expertise", cells)

    def test_an_organization_map_still_turns_people_searches_into_organizations(self):
        result = self.build({"map_type": "organizations", "requirements": {},
                             "tasks": [{"entity_type": "person", "query": "phosphogypsum labs"}]})
        self.assertEqual(result["map_type"], "organizations")
        self.assertEqual(self.store.cached(self.id, "workflow")["tasks"][0]["entity_type"], "actor")

    def test_a_plan_without_a_type_is_an_organization_map(self):
        result = self.build({"requirements": {}, "tasks": [{"entity_type": "actor", "query": "labs"}]})
        self.assertEqual(result["map_type"], "organizations")


class SelectionNoteTests(unittest.TestCase):
    def test_the_note_names_people_not_organizations(self):
        people = [{"_entity_type": "person", "full_name": "A"}, {"_entity_type": "person", "full_name": "B"}]
        none = reply("submit_selection", {"selected": [], "excluded": [{"id": 1, "reason": "x"}]})
        with patch.object(select, "paid_message", return_value=none):
            out = select.apply_request(people, "experts", {"hard_filters": ["Texas"]})
        self.assertIn("None of the 2 people matched", out["note"])


if __name__ == "__main__":
    unittest.main()
