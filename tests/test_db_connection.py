import unittest
from unittest.mock import MagicMock, patch

import psycopg

from src import db


class DatabaseConnectionTests(unittest.TestCase):
    def test_readonly_connection_retries_once_and_keeps_guards(self):
        connection = MagicMock()
        with (
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
            patch.object(db, "DATABASE_URL", "postgresql://example.invalid/db"),
            patch.object(
                db.psycopg,
                "connect",
                side_effect=psycopg.OperationalError("still unavailable"),
            ) as connect,
            self.assertRaises(psycopg.OperationalError),
        ):
            db.get_readonly_connection()

        self.assertEqual(connect.call_count, 2)


if __name__ == "__main__":
    unittest.main()
