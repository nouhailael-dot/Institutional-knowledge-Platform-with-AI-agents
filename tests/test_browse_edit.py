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
        for kind in ('kind="actor"', 'kind="event"', 'kind="person"', 'kind="hub"'):
            self.assertIn(kind, page)

    def test_the_edit_form_reads_every_field_it_shows(self):
        # Every field the database holds is editable (27 Oct 2026).
        sql = inspect.getsource(browse.load_actors)
        for column in ("primary_technical_focus", "technical_approach", "current_activities",
                       "technology_ip_notes", "key_constraints", "funding_summary",
                       "primary_lifecycle_role", "alt_names", "region_code", "ghus_notes"):
            self.assertIn(column, sql)
        sql = inspect.getsource(browse.load_events)
        for column in ("start_date", "end_date", "thematic_focus", "expected_attendance",
                       "access_type", "sponsoring_orgs", "source_origin", "host_actor_id"):
            self.assertIn(column, sql)

    def test_every_tab_has_an_owner_that_reads_not_recorded_until_logins(self):
        self.assertIsNone(browse.OWNER_NOT_RECORDED)
        for loader in (browse.load_actors, browse.load_hubs, browse.load_events, browse.load_people):
            self.assertIn('OWNER_NOT_RECORDED', inspect.getsource(loader))
        page = PAGE.read_text(encoding="utf-8")
        self.assertIn('const OWNER_NONE="Not recorded";', page)

    def test_trl_is_gone_from_browse(self):
        page = PAGE.read_text(encoding="utf-8")
        start, end = page.index("Ecosystem directory (Browse)"), page.index("function Sel(")
        self.assertNotIn("trl", page[start:end].lower())


if __name__ == "__main__":
    unittest.main()
