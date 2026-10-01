"""No-network checks for billing math, race conditions, cancellation and recovery."""
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.map_agent.costs import paid_message, usage_cost
from src.map_agent.pipeline import build_map
from src.map_agent.run_store import BudgetStopped, MapStopped, RunContext, RunStore


class Dump:
    def __init__(self, **data):
        self.__dict__.update(data)

    def model_dump(self, **kwargs):
        return self.__dict__


def response(usage=None):
    return SimpleNamespace(
        id="fake-response", stop_reason="end_turn", content=[Dump(type="text", text="Sample evidence")],
        usage=Dump(**(usage if usage is not None else {"input_tokens": 100, "output_tokens": 20})))


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = RunStore(Path(self.temp.name) / "jobs.sqlite3")
        self.id = self.store.create("Example research", budget=1_000_000)
        self.store.claim(self.id, "running", "Research", ("draft",))
        self.run = RunContext(self.store, self.id)
        self.client = Mock()
        self.client.with_options.return_value = self.client
        self.client.messages.count_tokens.return_value = SimpleNamespace(input_tokens=100)
        self.client.messages.create.return_value = response()
        self.kwargs = dict(model="claude-sonnet-5", max_tokens=100,
                           messages=[{"role": "user", "content": "Example"}])

    def test_usage_math_includes_cache_buckets_and_search(self):
        usage = {"input_tokens": 1000, "output_tokens": 200,
                 "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 300,
                 "cache_creation": {"ephemeral_5m_input_tokens": 100, "ephemeral_1h_input_tokens": 200},
                 "server_tool_use": {"web_search_requests": 2, "web_fetch_requests": 3}}
        self.assertEqual(usage_cost("claude-sonnet-5", usage), 25250)
        self.assertEqual(usage_cost("claude-haiku-4-5-20251001", usage), 22625)

    def test_missing_usage_is_not_zero(self):
        for usage in (None, {}, {"input_tokens": 4}, {"input_tokens": 4, "output_tokens": None}):
            with self.assertRaises(ValueError):
                usage_cost("claude-sonnet-5", usage)

    def test_new_budget_defaults_to_two_without_changing_legacy_runs(self):
        new_id = self.store.create()
        self.assertEqual(self.store.get(new_id)["cost"]["budget_usd"], 2)
        self.assertEqual(self.store.get(self.id)["cost"]["budget_usd"], 1)
        for invalid in (0, -1, 3_000_000, 1.5, True):
            with self.assertRaises(ValueError):
                self.store.create(budget=invalid)

    def test_extension_is_atomic_recorded_and_never_starts_work(self):
        job_id = self.store.create()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(self.store.approve_extension, [job_id, job_id]))
        saved = RunStore(self.store.path).get(job_id)
        self.assertEqual(saved["cost"]["budget_usd"], 3)
        self.assertFalse(saved["cost"]["can_extend"])
        self.assertEqual(saved["status"], "draft")
        self.assertEqual(saved["cost"]["calls"], [])
        with self.store.connect() as db:
            approvals = db.execute("SELECT * FROM budget_approvals").fetchall()
        self.assertEqual(len(approvals), 1)
        self.assertEqual(approvals[0]["previous_budget"], 2_000_000)
        self.assertEqual(approvals[0]["approved_budget"], 3_000_000)

    def test_extension_preserves_budget_stop_results_and_spending(self):
        job_id = self.store.create()
        self.store.claim(job_id, "running", "Research", ("draft",))
        call = self.store.reserve(job_id, "Discovery", "fake", 2_000_000, {})
        self.store.settle(call, 2_000_000, {}, {})
        self.store.update(job_id, result={"partial": True, "entities": {"actor": []}})
        with self.assertRaises(BudgetStopped):
            self.store.reserve(job_id, "Selection", "fake", 1, {})
        self.assertTrue(self.store.get(job_id)["cost"]["can_extend"])
        self.store.approve_extension(job_id)
        saved = self.store.get(job_id)
        self.assertEqual(saved["cost"]["remaining_usd"], 1)
        self.assertEqual(saved["cost"]["estimated_usd"], 2)
        self.assertEqual(saved["status"], "budget_stopped")
        self.assertTrue(saved["result"]["partial"])
        with self.assertRaises(MapStopped):
            self.store.check(job_id)

    def test_extension_cannot_clear_unsafe_or_manual_stops(self):
        for state in ("active", "pending", "unknown", "overrun", "manual", "interrupted", "legacy"):
            with self.subTest(state=state):
                job_id = self.store.create(budget=1_000_000 if state == "legacy" else 2_000_000)
                if state in ("active", "pending", "unknown", "overrun"):
                    self.store.claim(job_id, "running", "Research", ("draft",))
                if state in ("pending", "unknown", "overrun"):
                    call = self.store.reserve(job_id, "Discovery", "fake", 100, {})
                    if state == "pending":
                        self.store.stop(job_id, status="budget_stopped")
                    else:
                        self.store.settle(call, None if state == "unknown" else 101, {}, {})
                if state in ("manual", "interrupted"):
                    self.store.stop(job_id, status="cancelled" if state == "manual" else "interrupted")
                self.assertFalse(self.store.get(job_id)["cost"]["can_extend"])
                with self.assertRaises(MapStopped):
                    self.store.approve_extension(job_id)

    def test_three_dollar_approved_budget_still_enforces_reservations(self):
        job_id = self.store.create()
        self.store.approve_extension(job_id)
        self.store.claim(job_id, "running", "Research", ("draft",))
        self.store.reserve(job_id, "Discovery", "fake", 3_000_000, {})
        with self.assertRaises(BudgetStopped):
            self.store.reserve(job_id, "Selection", "fake", 1, {})

    def test_concurrent_reservations_share_one_allowance(self):
        gate = Barrier(2)
        def reserve():
            gate.wait()
            try:
                self.store.reserve(self.id, "Discovery", "test", 600000, {})
                return True
            except MapStopped:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            accepted = list(pool.map(lambda _: reserve(), range(2)))
        self.assertEqual(sum(accepted), 1)
        self.assertEqual(self.store.get(self.id)["cost"]["reserved_usd"], .6)

    def test_exact_budget_boundary_and_one_micro_over(self):
        self.store.reserve(self.id, "Discovery", "test", 1000000, {})
        with self.assertRaises(BudgetStopped):
            self.store.reserve(self.id, "Discovery", "test", 1, {})
        self.assertEqual(self.store.get(self.id)["status"], "budget_stopped")

    def test_known_usage_releases_unused_reservation_and_survives_reopen(self):
        paid_message(self.client, self.run, "Selection", **self.kwargs)
        saved = RunStore(self.store.path).get(self.id)
        self.assertEqual(saved["cost"]["estimated_usd"], .0004)
        self.assertEqual(saved["cost"]["reserved_usd"], 0)
        self.assertEqual(saved["cost"]["by_stage"], {"Selection": .0004})
        self.assertEqual(saved["cost"]["calls"][0]["pricing"]["date"], "2026-09-13")
        self.client.with_options.assert_called_once_with(max_retries=0, timeout=90.0)

    def test_budget_refusal_makes_no_paid_request(self):
        self.client.messages.count_tokens.return_value = SimpleNamespace(input_tokens=1000000)
        with self.assertRaises(BudgetStopped):
            paid_message(self.client, self.run, "Selection", **self.kwargs)
        self.client.messages.create.assert_not_called()

    def test_web_loops_are_blocked_before_counting_or_spending(self):
        with self.assertRaises(BudgetStopped):
            paid_message(self.client, self.run, "Discovery", **self.kwargs,
                         tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 1}])
        self.client.with_options.assert_not_called()
        self.assertEqual(self.store.get(self.id)["cost"]["estimated_usd"], 0)

    def test_one_direct_claude_search_is_allowed_and_charged(self):
        self.client.messages.create.return_value = response({"input_tokens": 6000, "output_tokens": 200,
                                                              "server_tool_use": {"web_search_requests": 1}})
        paid_message(self.client, self.run, "Web search", **self.kwargs,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 1,
                    "allowed_callers": ["direct"]}])
        self.client.messages.create.assert_called_once()
        self.client.messages.count_tokens.assert_not_called()
        self.assertEqual(self.store.get(self.id)["cost"]["estimated_usd"], .024)

    def test_unbounded_or_mixed_claude_search_is_blocked(self):
        unsafe = [
            [{"type": "web_search_20250305", "name": "web_search"}],
            [{"type": "web_search_20250305", "name": "web_search", "max_uses": 2,
              "allowed_callers": ["direct"]}],
            [{"type": "web_search_20250305", "name": "web_search", "max_uses": 1,
              "allowed_callers": ["direct"]}, {"name": "custom", "input_schema": {}}],
        ]
        for tools in unsafe:
            new_id = self.store.create("unsafe", budget=1_000_000)
            self.store.claim(new_id, "running", "Research", ("draft",))
            with self.subTest(tools=tools), self.assertRaises(BudgetStopped):
                paid_message(self.client, RunContext(self.store, new_id), "Web search",
                             **self.kwargs, tools=tools)

    def test_timeout_retains_allowance_and_blocks_retry(self):
        self.client.messages.create.side_effect = TimeoutError("network uncertainty")
        with self.assertRaises(TimeoutError):
            paid_message(self.client, self.run, "Selection", **self.kwargs)
        data = self.store.get(self.id)
        self.assertFalse(data["cost"]["usage_complete"])
        self.assertGreater(data["cost"]["reserved_usd"], 0)
        with self.assertRaises(MapStopped):
            paid_message(self.client, self.run, "Selection", **self.kwargs)
        self.assertEqual(self.client.messages.create.call_count, 1)

    def test_missing_response_usage_still_saves_evidence_and_blocks_more_work(self):
        self.client.messages.create.return_value = response({"input_tokens": 100})
        result = paid_message(self.client, self.run, "Selection", **self.kwargs)
        self.assertEqual(result.content[0].text, "Sample evidence")
        with self.store.connect() as db:
            saved = json.loads(db.execute("SELECT response FROM calls").fetchone()[0])
        self.assertEqual(saved["content"][0]["text"], "Sample evidence")
        with self.assertRaises(MapStopped):
            self.run.check()

    def test_stop_inflight_records_late_usage_without_restarting(self):
        def complete(**kwargs):
            self.store.stop(self.id)
            return response()
        self.client.messages.create.side_effect = complete
        paid_message(self.client, self.run, "Selection", **self.kwargs)
        self.run.checkpoint({"entities": {"actor": [{"name": "Example Lab"}]}})
        self.store.finish(self.id)
        data = self.store.get(self.id)
        self.assertEqual(data["status"], "cancelled")
        self.assertEqual(data["cost"]["estimated_usd"], .0004)
        self.assertEqual(data["result"]["entities"]["actor"][0]["name"], "Example Lab")
        with self.assertRaises(MapStopped):
            paid_message(self.client, self.run, "Selection", **self.kwargs)

    def test_recovery_never_resubmits_uncertain_request(self):
        self.run.checkpoint({"entities": {"actor": [{"name": "Saved Lab"}]}})
        self.store.reserve(self.id, "Discovery", "test", 400000, {})
        other = RunStore(self.store.path)
        other.recover()
        data = other.get(self.id)
        self.assertEqual(data["status"], "interrupted")
        self.assertEqual(data["cost"]["reserved_usd"], .4)
        self.assertFalse(data["cost"]["usage_complete"])
        self.assertEqual(data["result"]["entities"]["actor"][0]["name"], "Saved Lab")

    def test_duplicate_work_is_rejected(self):
        with self.assertRaises(MapStopped):
            self.store.claim(self.id, "running", "Research", ("draft", "ready"))

    def test_selection_failure_keeps_discovery_and_sources(self):
        entity = {"_entity_type": "actor", "name": "Saved Lab",
                  "sources": [{"url": "https://example.org", "supports": "Research"}]}
        plan = {"tasks": [{"entity_type": "actor", "query": "test"}],
                "requirements": {"hard_filters": ["California"]}}
        with patch("src.map_agent.research._collect", return_value=[]), \
             patch("src.map_agent.research.extract", return_value=([entity], "")), \
             patch("src.map_agent.research.apply_request", side_effect=BudgetStopped("No allowance")):
            with self.assertRaises(BudgetStopped):
                build_map("test", plan=plan, run=self.run)
        saved = self.store.get(self.id)["result"]
        self.assertTrue(saved["partial"])
        self.assertEqual(saved["entities"]["actor"][0]["sources"], entity["sources"])

    def test_stop_after_discovery_preserves_people_and_skips_selection(self):
        def discover(*args, **kwargs):
            self.store.stop(self.id)
            return ([{"_entity_type": "actor", "name": "Saved Lab",
                      "people": [{"full_name": "Sam Example", "title": "Director"}]}], "")
        with patch("src.map_agent.research._collect", return_value=[]), \
             patch("src.map_agent.research.extract", side_effect=discover), \
             patch("src.map_agent.research.apply_request") as selection:
            with self.assertRaises(MapStopped):
                build_map("test", plan={"tasks": [{"entity_type": "actor", "query": "test"}]}, run=self.run)
        selection.assert_not_called()
        self.assertEqual(self.store.get(self.id)["result"]["entities"]["actor"][0]["people"][0]["full_name"], "Sam Example")

    def test_over_reservation_usage_is_visible_and_blocks_subsequent_calls(self):
        self.client.messages.create.return_value = response({"input_tokens": 300000, "output_tokens": 50000})
        paid_message(self.client, self.run, "Selection", **self.kwargs)
        data = self.store.get(self.id)
        self.assertEqual(data["cost"]["estimated_usd"], 1.1)
        self.assertEqual(data["cost"]["remaining_usd"], 0)
        with self.assertRaises(MapStopped):
            self.run.check()

    def test_no_run_or_unpriced_model_cannot_spend(self):
        with self.assertRaises(BudgetStopped):
            paid_message(self.client, None, "Selection", **self.kwargs)
        with self.assertRaises(BudgetStopped):
            paid_message(self.client, self.run, "Selection", **{**self.kwargs, "model": "unknown"})
        self.client.with_options.assert_not_called()


class ApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from backend import app as backend
        self.backend = backend
        availability = patch.object(backend, "research_availability", return_value=(True, ""))
        availability.start()
        self.addCleanup(availability.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = RunStore(Path(self.temp.name) / "api.sqlite3")
        patcher = patch.object(backend, "map_store", return_value=self.store)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(backend.app)
        self.addCleanup(self.client.close)

    def test_planning_and_research_use_same_job_budget(self):
        job_id = self.client.post("/api/map/session").json()["job_id"]
        def chat(messages, text, run):
            client = Mock()
            client.with_options.return_value = client
            client.messages.count_tokens.return_value = SimpleNamespace(input_tokens=100)
            client.messages.create.return_value = response()
            paid_message(client, run, "Planning", model="claude-haiku-4-5-20251001",
                         max_tokens=100, messages=messages)
            return {"status": "plan", "summary": "Test plan", "tasks": [{"query": "sample", "entity_type": "actor"}]}
        with patch.object(self.backend, "map_chat", side_effect=chat):
            planned = self.client.post("/api/map/chat", json={"job_id": job_id,
                "messages": [{"role": "user", "content": "Sample"}]}).json()
        self.assertEqual(planned["job_id"], job_id)
        with patch.object(self.backend._MAP_POOL, "submit") as submit:
            request = {"job_id": job_id, "description": "Sample"}
            self.assertEqual(self.client.post("/api/map", json=request).status_code, 200)
            self.assertEqual(self.client.post("/api/map", json=request).status_code, 409)
            submit.assert_called_once()
        result = self.client.get("/api/map/"+job_id).json()
        self.assertEqual(result["cost"]["estimated_usd"], .0002)
        self.assertEqual(result["cost"]["budget_usd"], 2)
        self.assertEqual(self.client.post("/api/map/"+job_id+"/stop").json()["status"], "cancelled")
        self.assertEqual(self.client.get("/api/maps").json()["maps"][0]["id"], job_id)

    def test_map_document_upload_does_not_embed(self):
        job_id = self.client.post("/api/map/session").json()["job_id"]
        with patch.object(self.backend, "build_store", side_effect=AssertionError("Embeddings must not run")):
            r = self.client.post("/api/map/upload", data={"job_id": job_id}, files={"file": ("test.txt", b"Map context", "text/plain")})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.store.get(job_id)["doc_text"], "Map context")

    def test_verify_without_job_id_cannot_bypass_tracking(self):
        with patch.object(self.backend, "verify") as verify:
            r = self.client.post("/api/map/verify", json={"request": "Test", "entities": [{"name": "Example"}]})
            self.assertEqual(r.status_code, 400)
            verify.assert_not_called()

    def test_unknown_map_stop_returns_404(self):
        self.assertEqual(self.client.post("/api/map/missing/stop").status_code, 404)

    def test_extension_requires_approval_and_never_submits_research(self):
        job_id = self.client.post("/api/map/session").json()["job_id"]
        url = "/api/map/" + job_id + "/budget-extension"
        with patch.object(self.backend._MAP_POOL, "submit") as submit:
            self.assertEqual(self.client.post(url, json={}).status_code, 400)
            self.assertEqual(self.store.get(job_id)["cost"]["budget_usd"], 2)
            for _ in range(2):
                r = self.client.post(url, json={"approve": True})
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json()["cost"]["budget_usd"], 3)
                self.assertEqual(r.json()["status"], "draft")
            submit.assert_not_called()
        with patch.object(self.backend, "research_availability", return_value=(False, "Test disabled")):
            self.assertFalse(self.client.get("/api/maps").json()["research_available"])

    def test_extension_rejects_unknown_and_active_maps(self):
        self.assertEqual(self.client.post("/api/map/missing/budget-extension",
                                         json={"approve": True}).status_code, 404)
        job_id = self.store.create()
        self.store.claim(job_id, "running", "Research", ("draft",))
        self.assertEqual(self.client.post("/api/map/"+job_id+"/budget-extension",
                                         json={"approve": True}).status_code, 409)

    def test_live_endpoints_are_closed_when_configuration_is_off(self):
        with patch.object(self.backend, "research_availability", return_value=(False, "Controlled test is off")):
            chat = self.client.post("/api/map/chat", json={"messages": [{"role": "user", "content": "Test"}]})
            start = self.client.post("/api/map", json={"description": "Test", "plan": {"tasks": [{"query": "q", "entity_type": "actor"}]}})
            resume = self.client.post("/api/map/missing/resume", json={"approve": True})
        self.assertEqual([chat.status_code, start.status_code, resume.status_code], [503, 503, 503])
        self.assertEqual(chat.json()["detail"], "Controlled test is off")

    def test_resume_requires_approval_and_submits_one_saved_worker(self):
        job_id = self.store.create("Test")
        self.store.claim(job_id, "running", "Research", ("draft",))
        self.store.checkpoint_workflow(job_id,
            {"version": 1, "phase": "organizations", "tasks": [{"query": "q", "entity_type": "actor"}]},
            {"partial": True}, attempt=self.store.get(job_id)["attempt"])
        self.store.stop(job_id, status="budget_stopped")
        url = "/api/map/" + job_id + "/resume"
        self.assertEqual(self.client.post(url, json={}).status_code, 400)
        with patch.object(self.backend._MAP_POOL, "submit") as submit:
            response = self.client.post(url, json={"approve": True})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "running")
            submit.assert_called_once()
            self.assertEqual(self.client.post(url, json={"approve": True}).status_code, 409)


if __name__ == "__main__":
    unittest.main()
