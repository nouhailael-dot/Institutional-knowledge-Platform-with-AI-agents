"""A map stopped by hand can be continued or reopened, never silently restarted."""
import tempfile
import unittest
from pathlib import Path

from src.map_agent.run_store import MapStopped, RunStore


class StoppedMapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = RunStore(Path(self.temp.name) / "runs.sqlite3")
        self.id = self.store.create("Example research")

    def stop_during_research(self, phase="organizations"):
        self.store.claim(self.id, "running", "Research", ("draft",))
        self.store.checkpoint_workflow(self.id, {"version": 1, "phase": phase}, {"entities": {}})
        call = self.store.reserve(self.id, "Discovery", "fake", 100, {})
        self.store.settle(call, 50, {}, {})
        self.store.stop(self.id)

    def test_research_stopped_by_hand_can_be_continued(self):
        self.stop_during_research()
        cost = self.store.get(self.id)["cost"]
        self.assertTrue(cost["can_resume"])
        self.assertFalse(cost["can_reopen"])
        self.store.resume(self.id)
        self.assertEqual(self.store.get(self.id)["status"], "running")

    def test_a_request_still_in_flight_blocks_both(self):
        self.store.claim(self.id, "running", "Research", ("draft",))
        self.store.checkpoint_workflow(self.id, {"version": 1, "phase": "organizations"}, {"entities": {}})
        self.store.reserve(self.id, "Discovery", "fake", 100, {})
        self.store.stop(self.id)
        cost = self.store.get(self.id)["cost"]
        self.assertFalse(cost["can_resume"])
        self.assertFalse(cost["can_reopen"])
        with self.assertRaises(MapStopped):
            self.store.reopen(self.id)

    def test_stopped_while_planning_reopens_to_the_conversation(self):
        self.store.update(self.id, messages=[{"role": "user", "content": "water labs"}])
        self.store.claim(self.id, "planning", "Planning", ("draft",))
        self.store.stop(self.id)
        cost = self.store.get(self.id)["cost"]
        self.assertFalse(cost["can_resume"])
        self.assertTrue(cost["can_reopen"])
        self.store.reopen(self.id)
        saved = self.store.get(self.id)
        self.assertEqual((saved["status"], saved["cancelled"]), ("awaiting_reply", 0))

    def test_stopped_with_a_saved_plan_reopens_ready_to_start(self):
        self.store.update(self.id, plan={"tasks": [{"query": "water labs"}]})
        self.store.claim(self.id, "planning", "Planning", ("draft",))
        self.store.stop(self.id)
        self.store.reopen(self.id)
        self.assertEqual(self.store.get(self.id)["status"], "ready")

    def test_a_finished_map_stopped_during_a_follow_up_chat_reopens_as_done(self):
        self.stop_during_research(phase="done")
        self.store.update(self.id, result={"entities": {"actor": [{"name": "Example"}]}})
        self.assertFalse(self.store.get(self.id)["cost"]["can_resume"])
        self.store.reopen(self.id)
        self.assertEqual(self.store.get(self.id)["status"], "done")

    def test_reopening_starts_no_work(self):
        self.store.claim(self.id, "planning", "Planning", ("draft",))
        self.store.stop(self.id)
        before = self.store.get(self.id)
        self.store.reopen(self.id)
        after = self.store.get(self.id)
        self.assertEqual(after["attempt"], before["attempt"])
        self.assertEqual(after["cost"]["calls"], before["cost"]["calls"])


if __name__ == "__main__":
    unittest.main()
