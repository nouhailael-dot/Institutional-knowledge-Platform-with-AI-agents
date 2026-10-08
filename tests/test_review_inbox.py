"""Review read-model policy: preserved history, current runs, usable identities."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.review.store import ReviewStore, ReviewValidationError
from src.review.postgres_source import PostgresReviewSource


def candidate(key, *, name="Example Labs", run=None, finished=100, kind="search_candidate",
              intent="weekly", environment="operational", mode="live", **metadata):
    return {
        "source_key": key, "source_run_id": run or "discovery:" + key,
        "source_index": key, "entity_type": "actor",
        "payload": {"name": name, "website": "https://example.edu"},
        "created_at": finished,
        "agent_metadata": {
            "source_table": kind, "source_environment": environment,
            "review_run_source": "open_web_search", "review_run_intent": intent,
            "review_run_entity_type": "actor", "review_run_mode": mode,
            "review_run_status": "attention", "review_run_started_at": finished - 10,
            "review_run_finished_at": finished, **metadata,
        },
    }


class ReviewInboxTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = ReviewStore(Path(temporary.name) / "review.sqlite3")

    def put(self, *rows):
        self.store.sync_external_candidates(list(rows))

    def ids(self, **filters):
        return {row["source_index"] for row in self.store.list(**filters)["candidates"]}

    def test_latest_weekly_run_uses_run_completion_not_candidate_timestamp(self):
        old = candidate("old", finished=100)
        old["created_at"] = 999
        self.put(old, candidate("new", finished=200))
        self.assertEqual(self.ids(), {"new"})

    def test_previous_weekly_run_is_accessible_in_history_and_all_actionable(self):
        self.put(candidate("old", finished=100), candidate("new", finished=200))
        self.assertEqual(self.ids(inbox="history"), {"old"})
        self.assertEqual(self.ids(inbox="actionable"), {"old", "new"})

    def test_manual_and_build_map_runs_survive_later_weekly_run(self):
        self.put(candidate("manual", intent="manual"),
                 candidate("map", run="map-123", kind="build_the_map", intent=""),
                 candidate("new", finished=200))
        self.assertEqual(self.ids(), {"manual", "map", "new"})

    def test_explicit_test_and_dry_run_are_diagnostics_not_current(self):
        self.put(candidate("fixture", environment="test"), candidate("dry", mode="dry_run"),
                 candidate("live", finished=50))
        self.assertEqual(self.ids(), {"live"})
        self.assertEqual(self.ids(inbox="development"), {"fixture", "dry"})

    def test_null_actor_name_is_incomplete(self):
        self.put(candidate("null", name=None))
        self.assertEqual(self.ids(), set())
        self.assertEqual(self.ids(inbox="incomplete"), {"null"})

    def test_empty_and_whitespace_actor_names_are_incomplete(self):
        self.put(candidate("empty", name=""), candidate("spaces", name="  \t "))
        self.assertEqual(self.ids(inbox="incomplete"), {"empty", "spaces"})

    def test_uuid_run_id_and_generic_names_are_incomplete(self):
        self.put(candidate("uuid", name="577bd0bd-263a-43a7-90f8-373f7cab65ae"),
                 candidate("run", name="discovery:577bd0bd-263a-43a7-90f8-373f7cab65ae"),
                 candidate("unknown", name="unknown actor"))
        self.assertEqual(self.ids(inbox="incomplete"), {"uuid", "run", "unknown"})

    def test_named_actor_without_category_type_remains_current(self):
        self.put(candidate("unenriched"))
        self.assertEqual(self.ids(), {"unenriched"})

    def test_named_actor_without_geography_remains_current(self):
        row = candidate("no-geo")
        row["payload"].update(location_city=None, country=None)
        self.put(row)
        self.assertEqual(self.ids(), {"no-geo"})

    def test_history_is_retrievable_by_stable_id(self):
        self.put(candidate("old"), candidate("new", finished=200))
        old = self.store.list(inbox="history")["candidates"][0]
        self.assertEqual(self.store.get(old["candidate_id"])["original_payload"]["name"], "Example Labs")

    def test_filtering_never_deletes_or_changes_preserved_records(self):
        self.put(candidate("old"), candidate("new", finished=200), candidate("test", environment="test"))
        with self.store.connect() as db:
            before = [tuple(row) for row in db.execute("SELECT * FROM review_candidate ORDER BY candidate_id")]
        for inbox in ("current", "history", "all", "incomplete", "development"):
            self.store.list(inbox=inbox)
        with self.store.connect() as db:
            after = [tuple(row) for row in db.execute("SELECT * FROM review_candidate ORDER BY candidate_id")]
        self.assertEqual(before, after)

    def test_counts_obey_inbox_entity_search_and_run_filters(self):
        self.put(candidate("old", name="Old Lab"), candidate("new", name="New Lab", finished=200),
                 candidate("dev", environment="test"))
        current = self.store.list(search="New", entity_type="actor")
        self.assertEqual(current["counts"]["pending_review"], 1)
        self.assertEqual(current["inbox_counts"]["all"], 1)
        self.assertEqual(self.store.list(inbox="history")["counts"]["pending_review"], 1)
        self.assertEqual(self.store.list(inbox="all")["counts"]["pending_review"], 3)
        self.assertEqual(self.store.list(source_run_id="discovery:old")["counts"]["pending_review"], 0)

    def test_run_labels_use_real_metadata_without_uuid_or_invented_schedule(self):
        self.put(candidate("577bd0bd-263a-43a7-90f8-373f7cab65ae", intent=""))
        row = self.store.list()["candidates"][0]
        self.assertIn("Actor Discovery", row["run_label"])
        self.assertNotIn("577bd", row["run_label"])
        self.assertNotIn("Weekly", row["run_label"])

    def test_repeated_v2_issue_collapses_but_other_topics_and_issues_do_not(self):
        base = dict(kind="review_item", entity_id="actor-one", topic_id="ai", review_kind="verify_actor")
        self.put(candidate("old", **base), candidate("new", finished=200, **base),
                 candidate("hub", kind="review_item", entity_id="actor-one", topic_id="ai", review_kind="hub_assignment"),
                 candidate("water", kind="review_item", entity_id="actor-one", topic_id="water", review_kind="verify_actor"))
        self.assertEqual(self.ids(), {"new", "hub", "water"})
        self.assertEqual(self.ids(inbox="history"), {"old"})

    def test_review_evidence_category_location_and_hub_contract_are_preserved(self):
        row = candidate("v2-real", kind="review_item", facts=[{"fact_type": "light_pull"}, {"fact_type": "deep_pull"}],
                        relationships=[{"relationship_type": "parent"}], hub_assignments=[{"topic_id": "ai"}])
        row["payload"].update(actor_category="company", category_type="startup", location_city="Boston")
        self.put(row)
        saved = self.store.list()["candidates"][0]
        self.assertEqual(saved["original_payload"], row["payload"])
        for field in ("facts", "relationships", "hub_assignments"):
            self.assertEqual(saved["agent_metadata"][field], row["agent_metadata"][field])

    def test_unfinished_run_cannot_displace_completed_run(self):
        self.put(candidate("complete"), candidate("running", finished=200, review_run_status="running"))
        self.assertEqual(self.ids(), {"complete"})

    def test_missing_run_timestamps_do_not_use_new_candidate_timestamp_to_displace_runs(self):
        self.put(candidate("complete"), candidate("unknown", finished=999, review_run_finished_at=None))
        self.assertEqual(self.ids(), {"complete", "unknown"})

    def test_shared_domain_does_not_collapse_distinct_actors(self):
        self.put(candidate("school", run="discovery:one", name="School of Medicine"),
                 candidate("lab", run="discovery:one", name="University Laboratory"))
        self.assertEqual(self.ids(), {"school", "lab"})

    def test_latest_selection_is_independent_for_actor_and_event(self):
        event = candidate("event", finished=50, review_run_entity_type="event")
        event["entity_type"] = "event"
        self.put(candidate("actor", finished=200), event)
        self.assertEqual(self.ids(), {"actor", "event"})

    def test_source_metadata_preserves_run_dates_and_never_repairs_actor_from_page_title(self):
        source = PostgresReviewSource("postgresql://localhost/ghus_v2_integration_test")
        row = source._from_search_candidate({
            "candidate_id": "candidate", "run_id": "run", "entity_type": "actor",
            "record_preview": {"name": None}, "title": "Home | unrelated headline",
            "run_finished_at": 123, "run_started_at": 100, "run_mode": "live",
            "run_status": "attention", "run_source_name": "open_web_search",
        })
        self.assertIsNone(row["payload"]["name"])
        self.assertEqual(row["agent_metadata"]["source_environment"], "test")
        self.assertEqual(row["agent_metadata"]["review_run_finished_at"], 123)

    def test_invalid_inbox_is_rejected(self):
        with self.assertRaisesRegex(ReviewValidationError, "Unsupported review inbox"):
            self.store.list(inbox="invented")

    def test_api_default_and_explicit_audit_history_filters(self):
        from backend import app as backend
        from fastapi.testclient import TestClient
        self.put(candidate("old"), candidate("new", finished=200), candidate("test", environment="test"))
        with patch.object(backend, "_sync_review_candidates", return_value=[]), \
                patch.object(backend, "map_store", return_value=MagicMock()), \
                patch.object(backend, "review_store", return_value=self.store), \
                patch.object(backend, "review_admission_bridge", return_value=MagicMock(configured=False)), \
                TestClient(backend.app) as client:
            current = client.get("/api/review/candidates").json()
            audit = client.get("/api/review/candidates", params={"inbox": "all", "status": "all"}).json()
            history = client.get("/api/review/candidates", params={"inbox": "history"}).json()
        self.assertEqual({row["source_index"] for row in current["candidates"]}, {"new"})
        self.assertEqual(audit["counts"]["pending_review"], 3)
        self.assertEqual({row["source_index"] for row in history["candidates"]}, {"old"})


if __name__ == "__main__":
    unittest.main()
