import os
import unittest
from unittest.mock import patch

from backend import app as backend


class ReviewDemoSafetyTests(unittest.TestCase):
    def test_demo_is_off_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(backend._local_review_demo_enabled())

    def test_demo_accepts_only_project_demo_database(self):
        path = backend.ROOT / ".demo" / "review.sqlite3"
        with patch.dict(os.environ, {
            "REVIEW_DEMO_MODE": "1",
            "REVIEW_STORE_DB": str(path),
            "DATABASE_URL": "",
        }, clear=True):
            self.assertTrue(backend._local_review_demo_enabled())

    def test_demo_refuses_live_database_configuration(self):
        with patch.dict(os.environ, {
            "REVIEW_DEMO_MODE": "1",
            "REVIEW_STORE_DB": str(backend.ROOT / ".demo" / "review.sqlite3"),
            "DATABASE_URL": "postgresql://live.example/database",
        }, clear=True):
            with self.assertRaisesRegex(RuntimeError, "DATABASE_URL"):
                backend._local_review_demo_enabled()

    def test_demo_refuses_review_store_outside_demo_folder(self):
        with patch.dict(os.environ, {
            "REVIEW_DEMO_MODE": "1",
            "REVIEW_STORE_DB": str(backend.ROOT / ".review" / "review.sqlite3"),
            "DATABASE_URL": "",
        }, clear=True):
            with self.assertRaisesRegex(RuntimeError, "restricted"):
                backend._local_review_demo_enabled()


if __name__ == "__main__":
    unittest.main()
