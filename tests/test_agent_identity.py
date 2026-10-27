"""One identity for the agents that read websites, robots.txt in Build the Map,
and Discovery stopping before a paid run when the contact address is missing."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.discovery.bridge import DiscoveryBridge, DiscoveryBridgeError
from src.map_agent import search_backend, urlcheck
from src.map_agent.search_backend import ResearchSources

CONTACT = {"GHUS_AGENT_CONTACT_EMAIL": "team@example.org"}
UUID = "4474e15d-0d81-477a-af99-785a91ae7714"


class IdentityTests(unittest.TestCase):
    def test_page_reader_names_the_contact_when_set(self):
        with patch.dict("os.environ", CONTACT):
            self.assertEqual(search_backend.user_agent(), "UM6P-MapResearch/1.0 (team@example.org)")
        with patch.dict("os.environ", {"GHUS_AGENT_CONTACT_EMAIL": ""}):
            self.assertEqual(search_backend.user_agent(), "UM6P-MapResearch/1.0")

    def test_link_checker_uses_the_same_address(self):
        with patch.dict("os.environ", CONTACT):
            self.assertIn("+team@example.org", urlcheck._user_agent())
        with patch.dict("os.environ", {"GHUS_AGENT_CONTACT_EMAIL": ""}):
            self.assertEqual(urlcheck._user_agent(), urlcheck._UA)


class RobotsTests(unittest.TestCase):
    def setUp(self):
        search_backend._ROBOTS.clear()
        self.addCleanup(search_backend._ROBOTS.clear)

    def robots(self, status=200, body=b"", error=None):
        conn, sock = MagicMock(), MagicMock()
        sock.connect.side_effect = error
        conn.getresponse.return_value.status = status
        conn.getresponse.return_value.read.return_value = body
        return patch.object(search_backend, "_pinned_connection",
                            return_value=(conn, sock, ("93.184.216.34", 80), "example.org")), conn

    def test_an_explicit_disallow_refuses_and_one_read_serves_the_site(self):
        patcher, conn = self.robots(body=b"User-agent: *\nDisallow: /private\n")
        with patcher:
            self.assertFalse(search_backend.robots_allows("http://example.org/private/page"))
            self.assertTrue(search_backend.robots_allows("http://example.org/research"))
        conn.request.assert_called_once()
        self.assertEqual(conn.request.call_args.args[1], "/robots.txt")

    def test_a_rule_for_other_agents_only_does_not_refuse(self):
        patcher, _ = self.robots(body=b"User-agent: Googlebot\nDisallow: /\n")
        with patcher:
            self.assertTrue(search_backend.robots_allows("http://example.org/page"))

    def test_missing_or_unreachable_robots_counts_as_no_rule(self):
        for status, error in ((404, None), (500, None), (301, None), (200, OSError("timeout"))):
            search_backend._ROBOTS.clear()
            patcher, _ = self.robots(status=status, body=b"User-agent: *\nDisallow: /\n", error=error)
            with self.subTest(status=status, error=error), patcher:
                self.assertTrue(search_backend.robots_allows("http://example.org/page"))

    def test_a_refused_page_is_a_recorded_gap_and_never_fetched(self):
        run = MagicMock()
        run.store.cached.return_value = None
        fetcher = MagicMock()
        sources = ResearchSources(run, provider=MagicMock(), fetcher=fetcher, robots=lambda url: False)
        result = sources.page("http://example.org/page")
        self.assertIn("robots.txt", result["error"])
        self.assertEqual(result["text"], "")
        fetcher.assert_not_called()
        run.store.cache.assert_called_once()

    def test_an_injected_test_fetcher_skips_the_network_check(self):
        sources = ResearchSources(MagicMock(), provider=MagicMock(), fetcher=MagicMock())
        self.assertIsNone(sources.robots)
        self.assertIs(ResearchSources(MagicMock(), provider=MagicMock()).robots,
                      search_backend.robots_allows)


class DiscoveryContactTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / "agents" / "collection").mkdir(parents=True)
        (root / "agents" / "collection" / "discovery_requests.py").write_text("")
        self.start, self.run_command = MagicMock(), MagicMock()
        self.bridge = DiscoveryBridge(project_root=root, database_url="postgresql://local/test",
                                      run_command=self.run_command, start_process=self.start)

    def test_run_now_stops_before_any_search_without_an_address(self):
        with patch.dict("os.environ", {"GHUS_AGENT_CONTACT_EMAIL": ""}):
            with self.assertRaises(DiscoveryBridgeError) as raised:
                self.bridge.run_now(UUID)
        self.assertTrue(raised.exception.rejected)
        self.assertIn("GHUS_AGENT_CONTACT_EMAIL", str(raised.exception))
        self.start.assert_not_called()

    def test_run_now_starts_with_an_address(self):
        with patch.dict("os.environ", CONTACT):
            self.assertTrue(self.bridge.run_now(UUID)["started"])
        self.start.assert_called_once()

    def test_an_actor_check_reads_pages_so_it_needs_the_address_too(self):
        with patch.dict("os.environ", {"GHUS_AGENT_CONTACT_EMAIL": ""}):
            with self.assertRaises(DiscoveryBridgeError):
                self.bridge.check_update(UUID, {"scope": "general", "depth": "light"})
        self.run_command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
