import unittest
from unittest.mock import MagicMock, patch

import psycopg

from src import db


class DatabaseConnectionTests(unittest.TestCase):
    def test_readonly_connection_retries_and_keeps_guards(self):
        connection = MagicMock()
        with (
            patch.object(db, "CONNECT_RETRY_WAITS", (0, 0, 0)),
            patch.object(db, "stable_hostaddr", return_value=None),
            patch.object(db, "DATABASE_URL", "postgresql://example.invalid/db"),
            patch.object(
                db.psycopg,
                "connect",
                side_effect=[psycopg.OperationalError("temporary"), connection],
            ) as connect,
        ):
            self.assertIs(db.get_readonly_connection(), connection)

        self.assertEqual(connect.call_count, 2)
        for call in connect.call_args_list:
            self.assertEqual(call.kwargs["connect_timeout"], 10)
            self.assertEqual(call.kwargs["options"], "-c statement_timeout=8000")
        self.assertTrue(connection.read_only)

    def test_persistent_connection_failure_is_not_hidden(self):
        with (
            patch.object(db, "CONNECT_RETRY_WAITS", (0, 0, 0)),
            patch.object(db, "stable_hostaddr", return_value=None),
            patch.object(db, "DATABASE_URL", "postgresql://example.invalid/db"),
            patch.object(
                db.psycopg,
                "connect",
                side_effect=psycopg.OperationalError("still unavailable"),
            ) as connect,
            self.assertRaises(psycopg.OperationalError),
        ):
            db.get_readonly_connection()

        self.assertEqual(connect.call_count, 3)

    def test_a_dns_blip_uses_the_address_that_last_resolved(self):
        url = "postgresql://u:p@pooler.example.com:6543/postgres"
        db._last_good_hostaddr.clear()
        with patch.object(db.socket, "getaddrinfo",
                          return_value=[(2, 1, 6, "", ("18.214.78.123", 6543))]):
            self.assertEqual(db.stable_hostaddr(url), "18.214.78.123")
        with patch.object(db.socket, "getaddrinfo", side_effect=OSError("getaddrinfo failed")):
            self.assertEqual(db.stable_hostaddr(url), "18.214.78.123")
        # Nothing to resolve: a local or literal address, or keyword conninfo.
        self.assertIsNone(db.stable_hostaddr("postgresql://u@127.0.0.1:55432/x"))
        self.assertIsNone(db.stable_hostaddr("host=localhost dbname=x"))

    def test_the_remembered_address_is_passed_and_the_host_name_kept(self):
        connection = MagicMock()
        with (
            patch.object(db, "CONNECT_RETRY_WAITS", (0, 0, 0)),
            patch.object(db, "stable_hostaddr", return_value="18.214.78.123"),
            patch.object(db.psycopg, "connect", return_value=connection) as connect,
        ):
            db.connect_resilient("postgresql://u:p@pooler.example.com:6543/postgres", connect_timeout=10)
        self.assertEqual(connect.call_args.args[0], "postgresql://u:p@pooler.example.com:6543/postgres")
        self.assertEqual(connect.call_args.kwargs["hostaddr"], "18.214.78.123")


if __name__ == "__main__":
    unittest.main()
