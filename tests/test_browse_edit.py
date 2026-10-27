"""Browse editing is screens only for now: Browse must stay read-only, and the
event detail page reads the extra columns it shows."""
import inspect
import re
import unittest
from pathlib import Path

from src import browse

PAGE = Path(__file__).resolve().parents[1] / "frontend" / "index.html"


class BrowseEditTests(unittest.TestCase):
    def test_browse_never_writes_to_the_database(self):
        source = inspect.getsource(browse)
        self.assertIsNone(re.search(r"\b(INSERT|UPDATE|DELETE|ALTER|DROP)\b", source))
        self.assertIn("get_readonly_connection", source)

    def test_the_event_detail_reads_the_columns_it_shows(self):
        sql = inspect.getsource(browse.load_events)
        for column in ("website", "recurring_pattern", "description", "record_status"):
            self.assertIn(column, sql)

    def test_save_is_off_and_says_so_until_the_backend_writers_exist(self):
        page = PAGE.read_text(encoding="utf-8")
        self.assertIn('disabled=${true} title="Saving is not connected yet"', page)
        self.assertIn("Saving isn't connected yet: edits here are not stored.", page)
        for kind in ('kind="actor"', 'kind="event"', 'kind="person"'):
            self.assertIn(kind, page)


if __name__ == "__main__":
    unittest.main()
