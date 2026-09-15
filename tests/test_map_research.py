"""Offline controlled-search integration and safety checks; no API credits."""
import json
import socket
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.map_agent.run_store import RunStore, RunContext, MapStopped, BudgetStopped
from src.map_agent.research import build_controlled_map, extract
from src.map_agent.search_backend import (ClaudeSearch, ResearchSources, availability,
                                          fetch_page, canonical_url, excerpt, plain_text)


class Block(SimpleNamespace):
    def model_dump(self, **kwargs):
        return vars(self)


URL = "https://example.edu/lab"
ACTOR = {"name": "Example Lab", "website": URL, "description": "Battery research",
         "sources": [{"url": URL, "supports": "Identity and research"}]}
PERSON = {"full_name": "Sam Example", "organization_name": "Example Lab", "title": "Director",
          "sources": [{"url": URL, "supports": "Current lab director"}]}


class ControlledTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = RunStore(Path(temp.name) / "runs.sqlite3")
        self.id = self.store.create("battery labs")
        self.store.claim(self.id, "running", "Research", ("draft",))
        self.run = RunContext(self.store, self.id)
        self.provider = Mock()
        self.provider.search.return_value = [{"url": URL, "text": "Example Lab battery research. Director Sam Example.",
                                              "kind": "search_snippet"}]
        self.fetcher = Mock(return_value={"url": URL, "text": "Example Lab battery research. Director Sam Example.", "kind": "page"})
        self.sources = ResearchSources(self.run, self.provider, self.fetcher)
        self.client = Mock()
        self.client.with_options.return_value = self.client
        self.client.messages.count_tokens.return_value = SimpleNamespace(input_tokens=100)
        self.client.messages.create.side_effect = self.response
        self.plan = {"tasks": [{"entity_type": "actor", "query": "US battery labs"}]}

    def response(self, **kwargs):
        data = json.loads(kwargs["messages"][0]["content"])
        entity = PERSON if data["target_organization"] else ACTOR
        return SimpleNamespace(id="fake", stop_reason="tool_use",
            usage=Block(input_tokens=100, output_tokens=20),
            content=[Block(type="tool_use", name="submit_entities", input={"entities": [entity]})])

    def build(self):
        return build_controlled_map("battery labs", self.plan, self.run, self.sources, self.client)

    def test_organizations_then_targeted_people_and_page_reuse(self):
        result = self.build()
        self.assertFalse(result["partial"])
        self.assertEqual(result["entities"]["actor"][0]["people"][0]["full_name"], "Sam Example")
        queries = [c.args[0] for c in self.provider.search.call_args_list]
        self.assertEqual(queries[0], "US battery labs")
        self.assertIn('site:example.edu "Example Lab"', queries[1])
        self.fetcher.assert_called_once_with(URL)
        self.assertEqual(self.client.messages.create.call_count, 2)
        self.assertAlmostEqual(self.store.get(self.id)["cost"]["estimated_usd"], .0108)
        self.build()  # A completed workflow has nothing to repeat.
        self.assertEqual(self.client.messages.create.call_count, 2)
        self.assertEqual(self.provider.search.call_count, 2)

    def test_existing_supported_people_skip_targeted_search(self):
        def response(**kwargs):
            reply = self.response(**kwargs)
            reply.content[0].input = {"entities": [{**ACTOR, "people": [PERSON]}]}
            return reply
        self.client.messages.create.side_effect = response
        result = self.build()
        self.assertEqual(self.provider.search.call_count, 1)
        self.assertEqual(self.client.messages.create.call_count, 1)
        self.assertEqual(result["counts"]["person"], 1)

    def test_budget_extension_resumes_without_repeating_search_or_page(self):
        prefill = self.store.reserve(self.id, "Planning", "fake", 1_960_000, {})
        self.store.settle(prefill, 1_960_000, {}, {})
        with self.assertRaises(BudgetStopped):
            self.build()
        stopped = self.store.get(self.id)
        self.assertEqual(stopped["status"], "budget_stopped")
        self.assertFalse(stopped["cost"]["can_resume"])
        self.assertTrue(stopped["result"]["partial"])
        self.client.messages.create.assert_not_called()
        self.store.approve_extension(self.id)
        self.assertTrue(self.store.get(self.id)["cost"]["can_resume"])
        self.store.resume(self.id)
        self.run = RunContext(self.store, self.id)
        self.sources = ResearchSources(self.run, self.provider, self.fetcher)
        result = self.build()
        self.assertFalse(result["partial"])
        self.assertEqual(self.provider.search.call_count, 2)  # One actor, one people; no replay.
        self.fetcher.assert_called_once()
        self.assertAlmostEqual(self.store.get(self.id)["cost"]["estimated_usd"], 1.9708)

    def test_crash_after_paid_response_replays_saved_response_not_api(self):
        original = self.store.checkpoint_workflow
        checkpoints = 0
        def crash(run_id, state, result, **kwargs):
            nonlocal checkpoints
            checkpoints += 1
            if checkpoints == 2:
                raise RuntimeError("simulated crash after extraction before cursor save")
            return original(run_id, state, result, **kwargs)
        with patch.object(self.store, "checkpoint_workflow", side_effect=crash):
            with self.assertRaises(RuntimeError):
                self.build()
        self.store.recover()
        self.assertTrue(self.store.get(self.id)["cost"]["can_resume"])
        self.store.resume(self.id)
        self.run = RunContext(self.store, self.id)
        self.sources = ResearchSources(self.run, self.provider, self.fetcher)
        result = self.build()
        self.assertFalse(result["partial"])
        self.assertEqual(self.client.messages.create.call_count, 2)
        self.assertEqual(self.provider.search.call_count, 2)

    def test_unknown_search_charge_blocks_retry_and_continuation(self):
        self.provider.search.side_effect = TimeoutError("uncertain")
        with self.assertRaises(TimeoutError):
            self.build()
        self.assertEqual(self.store.get(self.id)["cost"]["reserved_usd"], .005)
        self.assertFalse(self.store.get(self.id)["cost"]["can_resume"])
        with self.assertRaises(MapStopped):
            self.store.resume(self.id)
        with self.assertRaises(MapStopped):
            self.sources.search("US battery labs")
        self.provider.search.assert_called_once()

    def test_superseded_worker_cannot_spend_finish_or_overwrite(self):
        self.store.checkpoint_workflow(self.id,
            {"version": 1, "phase": "organizations", "tasks": self.plan["tasks"]},
            {"partial": True}, attempt=self.run.attempt)
        old = self.run
        self.store.stop(self.id, status="budget_stopped")
        self.store.approve_extension(self.id)
        self.store.resume(self.id)
        new = RunContext(self.store, self.id)
        with self.assertRaises(MapStopped):
            old.check()
        with self.assertRaises(MapStopped):
            self.store.reserve(self.id, "Old worker", "fake", 1, {}, attempt=old.attempt)
        with self.assertRaises(MapStopped):
            self.store.checkpoint_workflow(self.id, {"version": 1, "phase": "done"},
                                           {"stale": True}, attempt=old.attempt)
        self.store.finish(self.id, attempt=old.attempt)
        saved = self.store.get(self.id)
        self.assertEqual(saved["status"], "running")
        self.assertNotEqual(saved["result"], {"stale": True})
        new.check()

    def test_stop_during_extraction_retains_late_evidence_and_skips_people(self):
        def response(**kwargs):
            self.store.stop(self.id)
            return self.response(**kwargs)
        self.client.messages.create.side_effect = response
        with self.assertRaises(MapStopped):
            self.build()
        saved = self.store.get(self.id)
        self.assertEqual(saved["result"]["counts"]["actor"], 1)
        self.assertEqual(saved["status"], "cancelled")
        self.assertFalse(saved["cost"]["can_resume"])
        self.provider.search.assert_called_once()

    def test_search_cache_normalizes_whitespace_and_case(self):
        self.sources.search("  US   battery labs ")
        self.sources.search("us battery labs")
        self.provider.search.assert_called_once()

    def test_failed_page_is_cached_and_coverage_gap_is_visible(self):
        self.fetcher.side_effect = TimeoutError()
        result = self.build()
        self.fetcher.assert_called_once()
        self.assertTrue(any("Page unavailable" in gap for gap in result["coverage_gaps"]))
        self.assertEqual(result["entities"]["actor"][0]["sources"][0]["evidence_type"], "search_snippet")

    def test_invented_source_and_wrong_affiliation_are_rejected(self):
        def response(**kwargs):
            reply = self.response(**kwargs)
            reply.content[0].input = {"entities": [{**PERSON, "organization_name": "Unrelated Lab"},
                {**PERSON, "sources": [{"url": "https://invented.example/profile"}]}]}
            return reply
        self.client.messages.create.side_effect = response
        rows, gap = extract(self.run, "battery labs", self.plan["tasks"][0], self.provider.search.return_value,
                            client=self.client, target={"name": "Example Lab"})
        self.assertEqual(rows, [])
        self.assertIn("2 records", gap)

    def test_no_results_are_not_reported_as_exhaustive(self):
        self.provider.search.return_value = []
        result = self.build()
        self.assertTrue(result["coverage_gaps"])
        self.assertIn("not an exhaustive census", result["coverage_note"])
        self.client.messages.create.assert_not_called()


class FetchSafetyTests(unittest.TestCase):
    def test_claude_search_extracts_and_replays_citations_without_second_call(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        store = RunStore(Path(temp.name) / "search.sqlite3")
        job_id = store.create()
        store.claim(job_id, "running", "Research", ("draft",))
        run = RunContext(store, job_id)
        client = Mock()
        client.with_options.return_value = client
        client.messages.count_tokens.return_value = SimpleNamespace(input_tokens=100)
        citation = {"type": "web_search_result_location", "url": URL,
                    "title": "Example Lab", "cited_text": "Official battery research laboratory."}
        client.messages.create.return_value = SimpleNamespace(id="search", stop_reason="end_turn",
            usage=Block(input_tokens=6000, output_tokens=200,
                        server_tool_use={"web_search_requests": 1}),
            content=[Block(type="text", text="Result", citations=[citation])])
        search = ClaudeSearch(run, client)
        first = search.search("US battery labs")
        second = search.search("US battery labs")
        self.assertEqual(first, second)
        self.assertEqual(first[0]["url"], URL)
        self.assertIn("Official battery", first[0]["text"])
        client.messages.create.assert_called_once()
        tool = client.messages.create.call_args.kwargs["tools"][0]
        self.assertEqual(tool["max_uses"], 1)
        self.assertEqual(tool["allowed_callers"], ["direct"])
        client.messages.count_tokens.assert_not_called()

    def test_private_loopback_link_local_and_mixed_dns_are_blocked(self):
        for ips in (["127.0.0.1"], ["10.0.0.1"], ["169.254.169.254"], ["::1"], ["93.184.216.34", "192.168.1.1"]):
            addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80)) for ip in ips]
            with self.subTest(ips=ips), patch("socket.getaddrinfo", return_value=addresses), patch("socket.socket") as sock:
                with self.assertRaises(ValueError):
                    fetch_page("http://example.org/page")
                sock.assert_not_called()

    def test_non_http_credentials_and_unusual_ports_are_rejected(self):
        for url in ("file:///etc/passwd", "http://user:pass@example.org", "http://example.org:8080", "http://example.org/\r\nX:bad"):
            with self.assertRaises(ValueError):
                canonical_url(url)

    def test_public_ip_is_pinned_and_redirects_are_not_followed(self):
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]
        with patch("socket.getaddrinfo", return_value=addresses) as dns, patch("socket.socket") as sock, \
             patch("http.client.HTTPConnection") as connection:
            response = connection.return_value.getresponse.return_value
            response.status = 302
            with self.assertRaises(ValueError):
                fetch_page("http://example.org/page")
            dns.assert_called_once()
            sock.return_value.connect.assert_called_once_with(("93.184.216.34", 80))
            connection.return_value.request.assert_called_once()

    def test_extracts_bounded_text_without_executing_page_instructions(self):
        self.assertEqual(plain_text("<script>secret()</script><p>Lab research</p>"), "Lab research")
        result = excerpt({"text": "Intro "*5000 + "battery faculty "*5000}, "battery faculty")
        self.assertLessEqual(len(result["text"]), 3500)

    def test_live_research_is_off_without_explicit_configuration(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(availability()[0])
        with patch.dict("os.environ", {"MAP_RESEARCH_ENABLED": "1", "MAP_SEARCH_PROVIDER": "claude"}, clear=True):
            self.assertFalse(availability()[0])
        with patch.dict("os.environ", {"MAP_RESEARCH_ENABLED": "1", "MAP_SEARCH_PROVIDER": "claude",
                                       "ANTHROPIC_API_KEY": "configured"}, clear=True):
            self.assertTrue(availability()[0])


if __name__ == "__main__":
    unittest.main()
