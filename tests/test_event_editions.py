"""Events: the newest edition, a default time window, and upcoming-first order
(asked for on 20 Oct 2026). No paid calls: search and extraction are stubbed."""
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from src.map_agent import research, select
from src.map_agent.run_store import RunContext, RunStore

TODAY = date.today()


def event(name, when=None, status="past", frequency="Annual", **extra):
    return {"_entity_type": "event", "name": name, "date_status": status,
            "next_date": when.isoformat() if when else "", "recurring_pattern": frequency, **extra}


class EditionTests(unittest.TestCase):
    def run_checks(self, found, rows_for):
        state = {"found": found, "gaps": [], "description": "critical minerals conferences"}
        run = MagicMock()
        with patch.object(research, "_collect", return_value=[{"url": "https://example.org"}]) as collect, \
             patch.object(research, "extract", side_effect=lambda run, req, task, ev, client=None:
                          (rows_for(task["query"]), "")):
            list(research.check_event_editions(state, run, sources=MagicMock()))
        return state, collect

    def test_only_past_recurring_unchecked_events_are_searched(self):
        self.assertTrue(research._needs_edition_check(event("TechConnect World 2025", TODAY - timedelta(days=100))))
        self.assertFalse(research._needs_edition_check(event("Inaugural Workshop", TODAY, frequency="One-time")))
        self.assertFalse(research._needs_edition_check(event("FETC 2027", TODAY + timedelta(days=90), status="upcoming")))
        self.assertFalse(research._needs_edition_check(event("Old", TODAY, _edition_checked=True)))

    def test_a_newer_edition_replaces_the_card_and_keeps_the_old_date(self):
        old = event("TechConnect World 2025", date(2025, 6, 9), location="Austin, TX",
                    sources=[{"url": "https://techconnect.org/2025"}])
        newer = {"name": "TechConnect World Innovation Conference 2026", "next_date": "2026-06-08",
                 "date_status": "upcoming", "location": "Washington, DC",
                 "sources": [{"url": "https://techconnect.org/2026"}]}
        state, collect = self.run_checks([old], lambda q: [newer])
        self.assertIn('"TechConnect World"', collect.call_args.args[1])
        self.assertEqual((old["next_date"], old["date_status"], old["location"]),
                         ("2026-06-08", "upcoming", "Washington, DC"))
        self.assertEqual(old["previous_edition"], "2025-06-09")
        self.assertEqual(len(old["sources"]), 2)
        self.assertTrue(old["_edition_checked"])

    def test_no_newer_edition_leaves_the_card_and_says_so(self):
        old = event("Tailings and Mine Waste 2025", date(2025, 11, 2))
        state, _ = self.run_checks([old], lambda q: [{"name": "Some Other Event", "next_date": "2026-05-01"}])
        self.assertEqual(old["next_date"], "2025-11-02")
        self.assertIn("No newer edition found for Tailings and Mine Waste 2025", state["gaps"][0])

    def test_at_most_five_checks_per_map(self):
        found = [event(f"Conference {chr(65 + i)} Mining 2025", date(2025, 3, 1)) for i in range(8)]
        state, collect = self.run_checks(found, lambda q: [])
        self.assertEqual(collect.call_count, research.EDITION_CHECKS)
        self.assertEqual(state["edition_index"], 5)


class WindowTests(unittest.TestCase):
    def events(self):
        return [event("Upcoming", TODAY + timedelta(days=30), status="upcoming"),
                event("Recent", TODAY - timedelta(days=200)),
                event("Old", TODAY - timedelta(days=500)),
                event("Unknown", None, status="date unconfirmed")]

    def test_without_a_period_older_past_editions_are_left_out_with_a_reason(self):
        keep, old = research.window_split(self.events(), "EdTech conferences in the US", {})
        self.assertEqual([e["name"] for e in keep], ["Upcoming", "Recent", "Unknown"])
        self.assertEqual(old[0]["name"], "Old")
        self.assertFalse(old[0]["_selected"])
        self.assertEqual(old[0]["_why_not"], "Last edition more than 12 months ago.")

    def test_a_named_period_leaves_the_judgement_to_selection(self):
        for request, filters in (("conferences over the next 12 months", []),
                                 ("critical minerals events in 2026", []),
                                 ("EdTech conferences", ["Must be upcoming"])):
            with self.subTest(request=request):
                keep, old = research.window_split(self.events(), request, {"hard_filters": filters})
                self.assertEqual((len(keep), old), (4, []))

    def test_upcoming_first_then_unconfirmed_then_most_recent_past(self):
        found = [event("Past old", date(2025, 1, 1), _selected=True),
                 event("Soon", TODAY + timedelta(days=10), status="upcoming", _selected=True),
                 event("Left out", TODAY + timedelta(days=5), status="upcoming", _selected=False),
                 event("Later", TODAY + timedelta(days=200), status="upcoming", _selected=True),
                 event("No date", None, status="date unconfirmed", _selected=True),
                 event("Past recent", date(2026, 1, 1), _selected=True)]
        ordered = research.sort_events(found)
        self.assertEqual([e["name"] for e in ordered],
                         ["Soon", "Later", "No date", "Past recent", "Past old", "Left out"])
        self.assertEqual([e["_rank"] for e in ordered[:5]], [1, 2, 3, 4, 5])


URL = "https://techconnect.org/world"


class Block(SimpleNamespace):
    def model_dump(self, **kwargs):
        return vars(self)


def reply(tool, data):
    return SimpleNamespace(id="fake", stop_reason="tool_use",
                           usage=Block(input_tokens=100, output_tokens=20),
                           content=[Block(type="tool_use", name=tool, input=data)])


class EventMapTests(unittest.TestCase):
    """A whole events map: search finds the 2025 edition, the edition step finds 2026."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        store = RunStore(Path(temp.name) / "runs.sqlite3")
        run_id = store.create("critical minerals conferences")
        store.claim(run_id, "running", "Research", ("draft",))
        self.run = RunContext(store, run_id)
        self.provider = Mock()
        self.provider.search.return_value = [{"url": URL, "text": "TechConnect World", "kind": "search_snippet"}]
        fetcher = Mock(return_value={"url": URL, "text": "TechConnect World", "kind": "page"})
        self.sources = research.ResearchSources(self.run, self.provider, fetcher, robots=lambda url: True)
        self.client = Mock()
        self.client.with_options.return_value = self.client
        self.client.messages.count_tokens.return_value = SimpleNamespace(input_tokens=100)
        self.extractions = 0
        self.client.messages.create.side_effect = self.respond

    def respond(self, **kwargs):
        if kwargs["tools"][0]["name"] == "submit_selection":
            return reply("submit_selection", {"selected": [{"id": 1, "why": "Critical minerals"}], "excluded": []})
        self.extractions += 1
        edition = ({"name": "TechConnect World 2025", "next_date": "2025-06-09", "date_status": "past"}
                   if self.extractions == 1 else
                   {"name": "TechConnect World Innovation Conference 2026", "next_date": f"{TODAY.year + 1}-06-08"})
        return reply("submit_entities", {"entities": [{**edition, "recurring_pattern": "Annual",
                                                       "sources": [{"url": URL}]}]})

    def test_the_finished_map_shows_the_newest_edition(self):
        plan = {"map_type": "events", "requirements": {"hard_filters": ["critical minerals"]},
                "tasks": [{"entity_type": "event", "query": "critical minerals conference"}]}
        with patch.object(select, "_get_client", return_value=self.client), \
             patch.object(research, "event_sectors", return_value=None):
            result = research.build_controlled_map("critical minerals conferences in 2026 and 2027",
                                                   plan, self.run, self.sources, self.client)
        card = result["entities"]["event"][0]
        self.assertEqual(card["next_date"], f"{TODAY.year + 1}-06-08")
        self.assertEqual(card["date_status"], "upcoming")
        self.assertEqual(card["previous_edition"], "2025-06-09")
        queries = [c.args[0] for c in self.provider.search.call_args_list]
        self.assertTrue(any(q.startswith('"TechConnect World"') for q in queries))
        self.assertEqual(self.extractions, 2)


if __name__ == "__main__":
    unittest.main()
