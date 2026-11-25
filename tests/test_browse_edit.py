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

    def test_save_goes_through_the_backend_writer(self):
        # 10 Nov 2026: Save sends the changed fields to /api/browse/<type>/<id>/edit,
        # which hands them to the backend's approved writer.
        page = PAGE.read_text(encoding="utf-8")
        self.assertNotIn("Saving isn't connected yet", page)
        self.assertIn("/edit`,{method:\"POST\"", page)
        for kind in ('kind="actor"', 'kind="event"', 'kind="person"', 'kind="hub"'):
            self.assertIn(kind, page)

    def test_the_edit_form_reads_every_field_it_shows(self):
        # Every field the database holds is editable (27 Oct 2026).
        sql = inspect.getsource(browse.load_actors)
        for column in ("primary_technical_focus", "technical_approach", "current_activities",
                       "funding_summary", "alt_names", "region_code", "ghus_notes"):
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

    def test_no_page_or_ask_query_names_a_column_migration_750_deletes(self):
        # 24 Nov 2026: the columns made for the first import that no agent collects
        # are deleted (migration 750); a query naming one would fail once it is applied.
        import re
        from src import assemble, router
        gone = ("estimated_trl", "technology_ip_notes", "key_constraints",
                "primary_lifecycle_role", "identity_summary", "profile_summary",
                "technical_summary", "lifecycle_summary")
        sources = {"browse.load_actors": inspect.getsource(browse.load_actors),
                   "assemble.assemble_actors": inspect.getsource(assemble.assemble_actors),
                   "router schema": router.SCHEMA if hasattr(router, "SCHEMA") else
                   Path("src/router.py").read_text(encoding="utf-8")}
        for where, text in sources.items():
            code = "\n".join(line for line in text.splitlines()
                             if not line.strip().startswith(("#", "--")))
            for column in gone:
                self.assertIsNone(re.search(rf"\b(a\.|to_jsonb\(a\)->>'){column}\b", code),
                                  f"{where} still reads {column}")
                self.assertNotIn(f" {column} ", code.replace(",", " ").replace("(", " "),
                                 f"{where} still names {column}")
        page = PAGE.read_text(encoding="utf-8")
        for column in gone[:4]:
            self.assertNotIn(column, page)

    def test_trl_is_gone_from_browse(self):
        page = PAGE.read_text(encoding="utf-8")
        start, end = page.index("Ecosystem directory (Browse)"), page.index("function Sel(")
        self.assertNotIn("trl", page[start:end].lower())


if __name__ == "__main__":
    unittest.main()
