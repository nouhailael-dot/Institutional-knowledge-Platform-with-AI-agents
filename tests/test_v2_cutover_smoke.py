"""Live smoke tests of the shared surfaces against an isolated Architecture V2 copy.

Run only with V2_CLEAN_DATABASE_URL pointing at a local *_test database on port
55432 (for example the post-migration-500 rehearsal copy). The URL is forced
into src.db before anything connects, so the project .env is never used.
Optional V2_PREBACKFILL_DATABASE_URL repeats the reads on a pre-500 copy.
"""

from __future__ import annotations

import os
import unittest
from urllib.parse import urlsplit

# 965 canonical actors, 80 of them merged duplicates: 885 are live.
LIVE_ACTORS = 885
CLEAN_URL = os.environ.get("V2_CLEAN_DATABASE_URL", "").strip()
PRE_URL = os.environ.get("V2_PREBACKFILL_DATABASE_URL", "").strip()


def _local_test(url: str) -> bool:
    parsed = urlsplit(url)
    return (parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port == 55432
            and parsed.path.removeprefix("/").endswith("_test"))


class _Surfaces:
    url = ""

    def setUp(self):
        if not self.url or not _local_test(self.url):
            self.skipTest("a local *_test database URL on port 55432 is required")
        import src.db as db
        self._previous = db.DATABASE_URL
        db.DATABASE_URL = self.url
        os.environ["REVIEW_SOURCE_DATABASE_URL"] = self.url

    def tearDown(self):
        import src.db as db
        db.DATABASE_URL = self._previous
        os.environ.pop("REVIEW_SOURCE_DATABASE_URL", None)

    def test_browse_reads_actors_hubs_and_events(self):
        from src.browse import load_actors, load_events, load_hubs, verification_label
        actors = load_actors()
        self.assertEqual(len(actors), LIVE_ACTORS)
        self.assertEqual({a["verification_status"] for a in actors}, {"verified"})
        self.assertEqual(verification_label("verified"), "✅ Verified")
        self.assertGreater(sum(bool(a["city"]) for a in actors), 800)
        self.assertGreater(sum(a["trl"] is not None for a in actors), 60)
        self.assertEqual(len(load_hubs()), 49)
        self.assertEqual(len(load_events()), 356)

    def test_ask_documents_carry_facts_and_status_labels(self):
        from src.assemble import assemble_actors
        docs = assemble_actors()
        self.assertEqual(len(docs), LIVE_ACTORS)
        self.assertTrue(all("Record status: ✅ Verified" in d["doc_text"] for d in docs))
        self.assertGreater(
            sum("Primary technical focus:" in d["doc_text"] for d in docs), 800
        )

    def test_sql_router_reads_through_actor_read(self):
        from src.router import is_safe_select, run_sql
        sql = ("SELECT count(*) AS n, count(*) FILTER (WHERE status='verified') AS verified "
               "FROM actor_read WHERE merged_into_actor_id IS NULL")
        self.assertTrue(is_safe_select(sql))
        cols, rows = run_sql(sql)
        self.assertEqual(cols, ["n", "verified"])
        self.assertEqual(rows[0], (LIVE_ACTORS, LIVE_ACTORS))

    def test_review_loader_reads_v2_review_items(self):
        from src.review.postgres_source import PostgresReviewSource
        source = PostgresReviewSource.from_environment()
        candidates, warnings = source.fetch_candidates()
        self.assertEqual(warnings, [])
        v2_items = [c for c in candidates
                    if c["agent_metadata"].get("source_table") == "review_item"]
        for candidate in v2_items:
            self.assertIn(candidate["agent_metadata"]["record_status"], {"verified", "parked"})


class CleanSchemaSmoke(_Surfaces, unittest.TestCase):
    url = CLEAN_URL


class PreCutoverSchemaSmoke(_Surfaces, unittest.TestCase):
    url = PRE_URL


if __name__ == "__main__":
    unittest.main()
