"""Offline review workflow tests. No network, model, or live database access."""

import json
import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.map_agent.run_store import RunStore
from src.review import (
    AdmissionBridgeError,
    DuplicateRisk,
    PostgresReviewSource,
    PostgresReviewSourceError,
    ReadOnlyRunStore,
    ReviewConflict,
    ReviewNotConfigured,
    ReviewStore,
    ReviewValidationError,
)


SOURCES = [{
    "url": "https://example.org/profile",
    "supports": "Identity and current work",
    "evidence_type": "page",
}]


def result_bundle(actor_name="Example Lab"):
    fixture = Path(__file__).parent / "fixtures" / "review_map_result.json"
    result = json.loads(fixture.read_text(encoding="utf-8"))
    result["entities"]["actor"][0]["name"] = actor_name
    result["entities"]["actor"][0]["people"][0]["organization_name"] = actor_name
    result["entities"]["person"][0]["organization_name"] = actor_name
    return deepcopy(result)


def discovery_candidate(entity_type="actor", source_id="candidate-1"):
    names = {"actor": "Review Lab", "person": "Ada Reviewer", "event": "Review Summit"}
    payload = {"name": names[entity_type], "website": "https://example.org/profile"}
    if entity_type == "event":
        payload.update({"start_date": "2026-10-10", "city": "Boston"})
    if entity_type == "person":
        payload.update({"affiliation": "Example University", "role": "Professor"})
    return {
        "source_key": f"postgres:search_candidate:{source_id}",
        "source_run_id": "discovery:run-1",
        "source_index": source_id,
        "source_description": "Open-web discovery · run-1",
        "entity_type": entity_type,
        "payload": payload,
        "evidence": [{"url": "https://example.org/profile", "supports": "Rubric source"}],
        "agent_metadata": {
            "source_table": "search_candidate", "source_candidate_id": source_id,
            "score_band": "review", "rubric_score": 0.55,
        },
        "duplicate_state": "not_checked",
        "created_at": 1_700_000_000.0,
    }


class ReviewStoreTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.runs = RunStore(self.root / "runs.sqlite3")
        self.store = ReviewStore(self.root / "review.sqlite3", enable_test_canonical=True)
        self.run_id = self.runs.create("Map battery innovation")
        self.runs.update(self.run_id, status="done", stage="Complete", result=result_bundle())
        self.assertEqual(self.store.sync_run_store(self.runs), 3)

    def candidates(self, entity_type=None):
        return self.store.list(status="all", entity_type=entity_type)["candidates"]

    def candidate(self, entity_type):
        return self.candidates(entity_type)[0]

    def test_candidates_derive_from_saved_results_with_stable_ids_and_no_duplicates(self):
        first = self.candidates()
        self.assertEqual({row["entity_type"] for row in first}, {"actor", "person", "event"})
        self.assertEqual(len(first), 3)
        # The nested organization-first person is not enqueued a second time.
        self.assertEqual(len(self.candidates("person")), 1)
        self.assertEqual(self.store.sync_run_store(self.runs), 0)
        self.assertEqual([row["candidate_id"] for row in first],
                         [row["candidate_id"] for row in self.candidates()])
        actor = self.candidate("actor")
        self.assertEqual(actor["source_run_id"], self.run_id)
        self.assertEqual(actor["evidence"][0]["supports"], "Identity and current work")
        self.assertEqual(actor["agent_metadata"]["_judge"]["relevance_score"], 0.95)
        self.assertIn("coverage_gaps", actor["agent_metadata"])
        self.assertEqual(actor["reviewed_payload"]["actor_category"], "research institute")
        self.assertEqual(actor["reviewed_payload"]["actor_type"], "research institute")
        for field in ("actor_category", "category_type", "location_city", "state", "region", "country"):
            self.assertIn(field, actor["editable_fields"])

    def test_untrusted_non_http_evidence_links_are_not_exposed(self):
        unsafe = result_bundle("Unsafe Link Lab")
        unsafe["entities"]["actor"][0]["sources"].append({
            "url": "javascript:alert(1)", "supports": "Untrusted",
        })
        run_id = self.runs.create("Unsafe evidence map")
        self.runs.update(run_id, status="done", stage="Complete", result={
            **unsafe, "entities": {"actor": unsafe["entities"]["actor"], "person": [], "event": []},
        })
        self.store.sync_run_store(self.runs)
        actor = [row for row in self.candidates("actor") if row["source_run_id"] == run_id][0]
        self.assertEqual([item["url"] for item in actor["evidence"]], [SOURCES[0]["url"]])

    def test_actor_person_and_event_canonical_mapping(self):
        expected = {"actor": "name", "person": "name", "event": "name"}
        for entity_type, name_field in expected.items():
            with self.subTest(entity_type=entity_type):
                row = self.candidate(entity_type)
                decided = self.store.approve(
                    row["candidate_id"], reviewer="reviewer@example.org",
                    idempotency_key=f"approve-{entity_type}", confirmed=True,
                )
                self.assertEqual(decided["status"], "approved")
                canonical = self.store.canonical_rows(entity_type)
                self.assertEqual(len(canonical), 1)
                self.assertEqual(canonical[0]["payload"][name_field],
                                 decided["reviewed_payload"][name_field])
                self.assertNotIn("_judge", canonical[0]["payload"])
                self.assertNotIn("sources", canonical[0]["payload"])

    def test_future_results_wait_for_a_terminal_run_then_sync_once(self):
        run_id = self.runs.create("Future agent run")
        self.runs.update(run_id, status="running", stage="Researching", result=result_bundle())
        self.assertEqual(self.store.sync_run_store(self.runs), 0)
        self.assertFalse(any(row["source_run_id"] == run_id for row in self.candidates()))

        self.runs.update(run_id, status="done", stage="Complete")
        self.assertEqual(self.store.sync_run_store(self.runs), 3)
        imported = [row for row in self.candidates() if row["source_run_id"] == run_id]
        self.assertEqual({row["entity_type"] for row in imported}, {"actor", "person", "event"})
        self.assertEqual(self.store.sync_run_store(self.runs), 0)

    def test_external_run_store_is_imported_without_writing_the_source_file(self):
        source_path = self.root / "original-runs.sqlite3"
        original = RunStore(source_path)
        run_id = original.create("Original-platform future run")
        original.update(run_id, status="done", stage="Complete", result=result_bundle())
        before = source_path.read_bytes()

        read_only = ReadOnlyRunStore(source_path)
        self.assertEqual(self.store.sync_run_store(read_only), 3)
        self.assertEqual(source_path.read_bytes(), before)
        with read_only.connect() as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("UPDATE runs SET description='forbidden'")
        imported = [row for row in self.candidates() if row["source_run_id"] == run_id]
        self.assertEqual({row["entity_type"] for row in imported}, {"actor", "person", "event"})
        self.assertEqual(original.get(run_id)["description"], "Original-platform future run")

    def test_postgres_candidates_copy_locally_with_stable_ids_and_rubric_metadata(self):
        candidates = [
            discovery_candidate("actor", "pg-actor"),
            discovery_candidate("person", "pg-person"),
            discovery_candidate("event", "pg-event"),
        ]
        self.assertEqual(self.store.sync_external_candidates(candidates), 3)
        first = [
            row for row in self.candidates()
            if row["source_run_id"] == "discovery:run-1"
        ]
        self.assertEqual({row["entity_type"] for row in first}, {"actor", "person", "event"})
        self.assertEqual(self.store.sync_external_candidates(candidates), 0)
        second = [
            row for row in self.candidates()
            if row["source_run_id"] == "discovery:run-1"
        ]
        self.assertEqual(
            [row["candidate_id"] for row in first],
            [row["candidate_id"] for row in second],
        )
        event = next(row for row in second if row["entity_type"] == "event")
        self.assertIn("next_date", event["editable_fields"])
        self.assertEqual(event["reviewed_payload"]["location"], "Boston")
        self.assertEqual(event["agent_metadata"]["rubric_score"], 0.55)

    def test_postgres_refresh_never_overwrites_review_edits_or_decisions(self):
        candidate = discovery_candidate("actor", "pg-refresh")
        self.store.sync_external_candidates([candidate])
        row = next(
            item for item in self.candidates("actor")
            if item["source_run_id"] == "discovery:run-1"
        )
        self.store.update(row["candidate_id"], {"name": "Human-corrected Lab"})
        candidate["payload"]["name"] = "Agent changed the name"
        candidate["agent_metadata"]["rubric_score"] = 0.61
        self.store.sync_external_candidates([candidate])
        refreshed = self.store.get(row["candidate_id"])
        self.assertEqual(refreshed["original_payload"]["name"], "Review Lab")
        self.assertEqual(refreshed["reviewed_payload"]["name"], "Human-corrected Lab")
        self.assertEqual(refreshed["agent_metadata"]["rubric_score"], 0.61)

    def test_rejection_is_atomic_durable_and_never_reaches_canonical_tables(self):
        actor = self.candidate("actor")
        decided = self.store.reject(
            actor["candidate_id"], reviewer="Reviewer One",
            rejection_reason="The organization is outside the requested geography.",
            idempotency_key="reject-actor", notes="Checked the cited page.", confirmed=True,
        )
        self.assertEqual(decided["status"], "rejected_by_reviewer")
        self.assertEqual(decided["rejection_reason"],
                         "The organization is outside the requested geography.")
        rejection = self.store.rejection(actor["candidate_id"])
        self.assertEqual(rejection["status"], "rejected_by_reviewer")
        self.assertEqual(rejection["source_run_id"], self.run_id)
        self.assertEqual(rejection["original_payload"]["name"], "Example Lab")
        self.assertEqual(rejection["evidence"][0]["url"], SOURCES[0]["url"])
        for entity_type in ("actor", "person", "event"):
            self.assertEqual(self.store.canonical_rows(entity_type), [])

    def test_rejection_reason_reviewer_and_confirmation_are_required(self):
        candidate_id = self.candidate("event")["candidate_id"]
        for kwargs in (
            {"reviewer": "", "rejection_reason": "Reason", "confirmed": True},
            {"reviewer": "R", "rejection_reason": "", "confirmed": True},
            {"reviewer": "R", "rejection_reason": "Reason", "confirmed": False},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ReviewValidationError):
                self.store.reject(candidate_id, idempotency_key=str(kwargs), **kwargs)
        self.assertEqual(self.store.get(candidate_id)["status"], "pending_review")

    def test_retry_is_idempotent_and_double_decisions_conflict(self):
        actor = self.candidate("actor")
        first = self.store.approve(
            actor["candidate_id"], reviewer="R", idempotency_key="same", confirmed=True,
        )
        retried = self.store.approve(
            actor["candidate_id"], reviewer="R", idempotency_key="same", confirmed=True,
        )
        self.assertEqual(first["canonical_entity_id"], retried["canonical_entity_id"])
        self.assertEqual(len(self.store.canonical_rows("actor")), 1)
        with self.assertRaises(ReviewConflict):
            self.store.reject(
                actor["candidate_id"], reviewer="R", rejection_reason="Changed mind",
                idempotency_key="different", confirmed=True,
            )

    def test_concurrent_decision_protection(self):
        event_id = self.candidate("event")["candidate_id"]

        def decide(key):
            try:
                return self.store.approve(
                    event_id, reviewer="Concurrent reviewer", idempotency_key=key,
                    confirmed=True,
                )["status"]
            except ReviewConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(decide, ("concurrent-a", "concurrent-b")))
        self.assertEqual(outcomes.count("approved"), 1)
        self.assertEqual(outcomes.count("conflict"), 1)
        self.assertEqual(len(self.store.canonical_rows("event")), 1)

    def test_canonical_failure_rolls_back_the_review_decision(self):
        person_id = self.candidate("person")["candidate_id"]
        with patch.object(self.store, "_insert_canonical", side_effect=RuntimeError("insert failed")):
            with self.assertRaisesRegex(RuntimeError, "insert failed"):
                self.store.approve(
                    person_id, reviewer="R", idempotency_key="rollback", confirmed=True,
                )
        self.assertEqual(self.store.get(person_id)["status"], "pending_review")
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM review_decision").fetchone()[0], 0)

    def test_duplicate_protection_blocks_ambiguous_approval(self):
        first = self.candidate("actor")
        self.store.approve(first["candidate_id"], reviewer="R", idempotency_key="first", confirmed=True)
        second_run = self.runs.create("Another map")
        duplicate = result_bundle()
        duplicate["entities"] = {"actor": [duplicate["entities"]["actor"][0]], "person": [], "event": []}
        self.runs.update(second_run, status="done", stage="Complete", result=duplicate)
        self.store.sync_run_store(self.runs)
        second = [row for row in self.candidates("actor") if row["source_run_id"] == second_run][0]
        with self.assertRaises(DuplicateRisk) as raised:
            self.store.approve(
                second["candidate_id"], reviewer="R", idempotency_key="duplicate", confirmed=True,
            )
        self.assertEqual(raised.exception.matches[0]["name"], "Example Lab")
        self.assertEqual(self.store.get(second["candidate_id"])["status"], "pending_review")

    def test_field_allowlist_and_validation(self):
        actor_id = self.candidate("actor")["candidate_id"]
        with self.assertRaisesRegex(ReviewValidationError, "Unsupported reviewed fields"):
            self.store.update(actor_id, {"source_id": "attacker-controlled"})
        with self.assertRaisesRegex(ReviewValidationError, "estimated_trl"):
            self.store.update(actor_id, {"estimated_trl": 99})
        updated = self.store.update(actor_id, {"description": "Reviewed description", "estimated_trl": 6})
        self.assertEqual(updated["reviewed_payload"]["description"], "Reviewed description")
        self.assertEqual(updated["reviewed_payload"]["estimated_trl"], 6)

    def test_admission_validation_requires_target_fixed_reason_and_model_lengths(self):
        candidate = discovery_candidate("actor", "admission-actor")
        self.store.sync_external_candidates([candidate])
        actor = next(row for row in self.candidates("actor")
                     if row["source_run_id"] == "discovery:run-1")
        base = dict(
            reviewer="Reviewer", idempotency_key="admission-check", confirmed=True,
        )
        with self.assertRaisesRegex(ReviewValidationError, "Select the existing"):
            self.store.admission_request(
                actor["candidate_id"], decision_kind="same_existing", **base,
            )
        with self.assertRaisesRegex(ReviewValidationError, "fixed rejection"):
            self.store.admission_request(
                actor["candidate_id"], decision_kind="reject",
                rejection_reason="Not relevant", **base,
            )
        with self.assertRaisesRegex(ReviewValidationError, "Other"):
            self.store.admission_request(
                actor["candidate_id"], decision_kind="reject",
                rejection_reason="Other", **base,
            )
        with self.assertRaisesRegex(ReviewValidationError, "255-character"):
            self.store.admission_request(
                actor["candidate_id"], decision_kind="new",
                edited_payload={**actor["reviewed_payload"], "name": "x" * 256}, **base,
            )

    def test_approval_fails_honestly_when_admission_is_not_configured(self):
        disabled = ReviewStore(self.root / "disabled.sqlite3")
        disabled.sync_run_store(self.runs)
        actor = disabled.list(entity_type="actor")["candidates"][0]
        with self.assertRaises(ReviewNotConfigured):
            disabled.approve(
                actor["candidate_id"], reviewer="R", idempotency_key="disabled", confirmed=True,
            )
        self.assertEqual(disabled.get(actor["candidate_id"])["status"], "pending_review")


class ReviewApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from backend import app as backend

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.runs = RunStore(root / "runs.sqlite3")
        run_id = self.runs.create("API map")
        self.runs.update(run_id, status="done", stage="Complete", result=result_bundle())
        self.store = ReviewStore(root / "review.sqlite3", enable_test_canonical=True)
        self.backend = backend
        run_patch = patch.object(backend, "map_store", return_value=self.runs)
        review_patch = patch.object(backend, "review_store", return_value=self.store)
        postgres_patch = patch.object(backend, "review_postgres_source", return_value=None)
        self.bridge = MagicMock()
        self.bridge.configured = True
        self.bridge.apply.return_value = {
            "status": "approved", "canonical_entity_id": "canonical-1",
            "promotion_action": "created",
        }
        bridge_patch = patch.object(backend, "review_admission_bridge", return_value=self.bridge)
        run_patch.start(); review_patch.start(); postgres_patch.start(); bridge_patch.start()
        backend._review_sync_last = 0.0
        backend._review_sync_store_key = None
        self.addCleanup(run_patch.stop); self.addCleanup(review_patch.stop)
        self.addCleanup(postgres_patch.stop); self.addCleanup(bridge_patch.stop)
        self.client = TestClient(backend.app)
        self.addCleanup(self.client.close)

    def list(self, **params):
        response = self.client.get("/api/review/candidates", params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_list_detail_filters_update_and_reject(self):
        listed = self.list()
        self.assertEqual(len(listed["candidates"]), 3)
        self.assertEqual(listed["counts"], {
            "pending_review": 3, "approved": 0, "rejected_by_reviewer": 0,
        })
        self.assertTrue(listed["admission_configured"])
        filtered = self.list(entity_type="event", search="summit")
        self.assertEqual(len(filtered["candidates"]), 1)
        candidate_id = filtered["candidates"][0]["candidate_id"]
        detail = self.client.get(f"/api/review/candidates/{candidate_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("event_type", detail.json()["editable_fields"])
        updated = self.client.patch(
            f"/api/review/candidates/{candidate_id}",
            json={"fields": {"description": "Reviewed event"}},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["reviewed_payload"]["description"], "Reviewed event")
        rejected = self.client.post(
            f"/api/review/candidates/{candidate_id}/reject",
            json={"reviewer": "API reviewer", "rejection_reason": "Not in scope",
                  "idempotency_key": "api-reject", "confirmed": True},
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(rejected.json()["status"], "rejected_by_reviewer")
        self.assertEqual(self.list(status="rejected_by_reviewer")["counts"]["rejected_by_reviewer"], 1)

    def test_future_agent_run_appears_on_the_next_review_request(self):
        run_id = self.runs.create("Future completed map")
        self.runs.update(run_id, status="done", stage="Complete", result=result_bundle())

        response = self.client.get("/api/review/candidates", params={"status": "all", "refresh": True})
        self.assertEqual(response.status_code, 200)
        imported = [
            row for row in response.json()["candidates"]
            if row["source_run_id"] == run_id
        ]
        self.assertEqual(len(imported), 3)
        self.assertEqual({row["entity_type"] for row in imported}, {"actor", "person", "event"})

    def test_future_original_platform_run_appears_via_read_only_source(self):
        source_path = self.store.path.parent / "original-platform-runs.sqlite3"
        original = RunStore(source_path)
        run_id = original.create("Original platform completed map")
        original.update(run_id, status="done", stage="Complete", result=result_bundle())
        before = source_path.read_bytes()

        with patch.dict(os.environ, {"REVIEW_SOURCE_RUN_DB": str(source_path)}):
            response = self.client.get("/api/review/candidates", params={"status": "all", "refresh": True})
        self.assertEqual(response.status_code, 200)
        imported = [
            row for row in response.json()["candidates"]
            if row["source_run_id"] == run_id
        ]
        self.assertEqual(len(imported), 3)
        self.assertEqual(source_path.read_bytes(), before)

    def test_postgres_discovery_candidates_appear_on_the_next_review_request(self):
        source = MagicMock()
        source.fetch_candidates.return_value = ([
            discovery_candidate("actor", "api-pg-actor"),
            discovery_candidate("person", "api-pg-person"),
            discovery_candidate("event", "api-pg-event"),
        ], [])
        with patch.object(self.backend, "review_postgres_source", return_value=source):
            response = self.client.get("/api/review/candidates", params={"status": "all", "refresh": True})
        self.assertEqual(response.status_code, 200)
        imported = [
            row for row in response.json()["candidates"]
            if row["source_run_id"] == "discovery:run-1"
        ]
        self.assertEqual(len(imported), 3)
        self.assertEqual(response.json()["sync_warnings"], [])

    def test_postgres_source_failure_is_visible_without_hiding_local_candidates(self):
        source = MagicMock()
        source.fetch_candidates.side_effect = PostgresReviewSourceError(
            "Unable to read the PostgreSQL review queues."
        )
        with patch.object(self.backend, "review_postgres_source", return_value=source):
            response = self.client.get("/api/review/candidates", params={"status": "all", "refresh": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["candidates"]), 3)
        self.assertEqual(response.json()["sync_warnings"], [
            "Unable to read the PostgreSQL review queues."
        ])

    def test_approve_response_retry_conflict_and_validation(self):
        actor = self.list(entity_type="actor")["candidates"][0]
        url = f"/api/review/candidates/{actor['candidate_id']}/approve"
        body = {"reviewer": "API reviewer", "idempotency_key": "api-approve",
                "confirmed": True, "edited_payload": actor["reviewed_payload"]}
        first = self.client.post(url, json=body)
        second = self.client.post(url, json=body)
        self.assertEqual([first.status_code, second.status_code], [200, 200])
        self.assertEqual(first.json()["canonical_entity_id"], second.json()["canonical_entity_id"])
        self.assertEqual(len(self.store.canonical_rows("actor")), 1)
        conflict = self.client.post(
            url.replace("/approve", "/reject"),
            json={"reviewer": "API reviewer", "rejection_reason": "No",
                  "idempotency_key": "another-key", "confirmed": True},
        )
        self.assertEqual(conflict.status_code, 409)
        pending = self.list(entity_type="person")["candidates"][0]
        invalid = self.client.patch(
            f"/api/review/candidates/{pending['candidate_id']}",
            json={"fields": {"table_name": "person"}},
        )
        self.assertEqual(invalid.status_code, 422)

    def test_unconfigured_admission_and_internal_errors_are_sanitized(self):
        disabled = ReviewStore(self.store.path.parent / "disabled.sqlite3")
        with patch.object(self.backend, "review_store", return_value=disabled):
            actor = self.list(entity_type="actor")["candidates"][0]
            response = self.client.post(
                f"/api/review/candidates/{actor['candidate_id']}/approve",
                json={"reviewer": "R", "idempotency_key": "disabled", "confirmed": True},
            )
        self.assertEqual(response.status_code, 503)
        self.assertIn("not configured", response.json()["detail"])

        actor = self.list(entity_type="actor")["candidates"][0]
        with patch.object(self.store, "_insert_canonical", side_effect=RuntimeError("secret database detail")):
            failed = self.client.post(
                f"/api/review/candidates/{actor['candidate_id']}/approve",
                json={"reviewer": "R", "idempotency_key": "failure", "confirmed": True},
            )
        self.assertEqual(failed.status_code, 500)
        self.assertNotIn("secret", failed.text)
        self.assertEqual(self.store.get(actor["candidate_id"])["status"], "pending_review")

    def test_failed_authoritative_admission_stays_pending_and_surfaces_error(self):
        self.store.sync_external_candidates([discovery_candidate("actor", "decision-failure")])
        actor = next(row for row in self.store.list(status="all", entity_type="actor")["candidates"]
                     if row["source_run_id"] == "discovery:run-1")
        self.bridge.apply.side_effect = AdmissionBridgeError("Dedicated writer refused the change.")
        response = self.client.post(
            f"/api/review/candidates/{actor['candidate_id']}/decision",
            json={
                "decision_kind": "new", "reviewer": "Reviewer", "confirmed": True,
                "idempotency_key": "failed-admission", "edited_payload": actor["reviewed_payload"],
            },
        )
        self.assertEqual(response.status_code, 503)
        stored = self.store.get(actor["candidate_id"])
        self.assertEqual(stored["status"], "pending_review")
        self.assertEqual(stored["admission_state"], "failed")
        self.assertIn("refused", stored["admission_error"])

    def test_successful_decision_records_only_after_authoritative_commit(self):
        self.store.sync_external_candidates([discovery_candidate("event", "decision-event")])
        event = next(row for row in self.store.list(status="all", entity_type="event")["candidates"]
                     if row["source_run_id"] == "discovery:run-1")
        response = self.client.post(
            f"/api/review/candidates/{event['candidate_id']}/decision",
            json={
                "decision_kind": "new", "reviewer": "Reviewer", "confirmed": True,
                "idempotency_key": "successful-admission",
                "edited_payload": event["reviewed_payload"],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "approved")
        self.assertEqual(response.json()["canonical_entity_id"], "canonical-1")

    def test_sync_is_throttled_until_explicit_refresh(self):
        source = MagicMock()
        source.fetch_candidates.return_value = ([], [])
        with patch.object(self.backend, "review_postgres_source", return_value=source):
            self.client.get("/api/review/candidates")
            self.client.get("/api/review/candidates")
            self.assertEqual(source.fetch_candidates.call_count, 1)
            self.client.get("/api/review/candidates", params={"refresh": True})
            self.assertEqual(source.fetch_candidates.call_count, 2)


class PostgresReviewSourceTests(unittest.TestCase):
    def setUp(self):
        self.source = PostgresReviewSource(
            "postgresql://reviewer:secret@example.invalid:5432/ghus"
        )

    def test_search_candidate_mapping_preserves_rubric_identity_and_evidence(self):
        row = {
            "candidate_id": "candidate-id", "run_id": "run-id", "entity_type": "person",
            "url": "https://example.org/ada", "created_at": 1_700_000_000,
            "score_band": "auto_high", "record_preview": {
                "name": "Ada Reviewer", "affiliation": "Example University",
            },
            "query": "researcher", "provider": "search", "title": "Ada",
            "triage_verdict": "accepted", "triage_reason": "relevant",
            "fit_score": 0.8, "duplicate_of": None,
            "rubric": {"actionable_role": {"present": True, "evidence": "Professor"}},
            "score_breakdown": {"actionable_role": 0.15},
            "qualification_paths": [], "identity_outcome": "unknown_affiliation",
            "rerank_position": 2, "rerank_reason": "Strong match",
            "run_mode": "dry_run", "run_status": "attention", "run_status_reason": "cap",
        }
        candidate = self.source._from_search_candidate(row)
        self.assertEqual(candidate["entity_type"], "person")
        self.assertEqual(candidate["payload"]["name"], "Ada Reviewer")
        self.assertEqual(candidate["evidence"][0]["url"], "https://example.org/ada")
        self.assertEqual(candidate["agent_metadata"]["identity_outcome"], "unknown_affiliation")
        self.assertEqual(candidate["agent_metadata"]["rubric_score"], 0.8)
        self.assertIn("dry_run", candidate["source_description"])

    def test_sqlalchemy_postgres_driver_scheme_is_normalized_for_psycopg(self):
        source = PostgresReviewSource(
            "postgresql+psycopg2://reviewer:secret@example.invalid:5432/ghus"
        )
        self.assertTrue(source.database_url.startswith("postgresql://"))
        self.assertNotIn("+psycopg2", source.database_url)

    def test_v2_verify_actor_review_maps_classification_location_facts_and_source(self):
        candidate = self.source._from_v2_review_item({
            "review_item_id": "review-id", "review_kind": "verify_actor",
            "entity_id": "actor-id", "topic_id": "topic-id", "priority": "normal",
            "payload": {"source_url": "https://example.org/discovery"},
            "created_at": 1_700_000_000, "name": "Example Labs",
            "actor_category": "company", "category_type": "corporate_rd_lab",
            "category_note": None, "actor_type": "company",
            "description": "Topic work", "website": "https://example.org",
            "location_city": "Boston", "state": "Massachusetts", "state_code": "MA",
            "region_code": "northeast", "country": "United States",
            "record_status": "parked", "actor_source_url": "https://example.org/discovery",
            "facts": [{"fact_key": "description", "layer": 1,
                       "confidence": "medium", "source_url": "https://example.org/fact"}],
        })
        self.assertEqual(candidate["payload"]["actor_category"], "company")
        self.assertEqual(candidate["payload"]["category_type"], "corporate_rd_lab")
        self.assertEqual(candidate["payload"]["location_city"], "Boston")
        self.assertEqual(candidate["payload"]["region"], "northeast")
        self.assertEqual(candidate["agent_metadata"]["record_status"], "parked")
        self.assertEqual(candidate["agent_metadata"]["facts"][0]["layer"], 1)
        self.assertEqual(
            {item["url"] for item in candidate["evidence"]},
            {"https://example.org/discovery", "https://example.org/fact"},
        )

    def test_local_v2_review_source_disables_tls_but_remains_read_only(self):
        source = PostgresReviewSource(
            "postgresql://ghus_test@127.0.0.1:55432/ghus_v2_integration_test"
        )
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = {"transaction_read_only": "on"}
        with patch("psycopg.connect", return_value=db) as connect:
            with source.connect():
                pass
        self.assertEqual(connect.call_args.kwargs["sslmode"], "disable")
        self.assertIn("default_transaction_read_only=on", connect.call_args.kwargs["options"])

    def test_queue_metadata_merges_into_matching_search_candidate(self):
        existing = discovery_candidate("event", "search-event")
        existing["match_key"] = ("event", "run-1", "https://example.org/profile")
        incoming = discovery_candidate("event", "queue-event")
        incoming["source_key"] = "postgres:event_review_queue:queue-event"
        incoming["match_key"] = existing["match_key"]
        incoming["agent_metadata"] = {"review_queue_id": "queue-event"}
        incoming["duplicate_state"] = "possible_duplicate"
        candidates = {existing["source_key"]: existing}
        self.source._merge_queue_candidate(candidates, incoming)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(existing["agent_metadata"]["review_queue_id"], "queue-event")
        self.assertEqual(existing["duplicate_state"], "possible_duplicate")

    def test_connection_forces_and_verifies_postgres_read_only_mode(self):
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = {"transaction_read_only": "on"}
        with patch("src.review.postgres_source._reachable_hostaddr", return_value=None), \
                patch("psycopg.connect", return_value=db) as connect:
            with self.source.connect() as connected:
                self.assertIs(connected, db)
        kwargs = connect.call_args.kwargs
        self.assertIn("default_transaction_read_only=on", kwargs["options"])
        self.assertEqual(kwargs["sslmode"], "require")
        self.assertEqual(db.execute.call_args_list[0].args[0], "SET TRANSACTION READ ONLY")
        self.assertEqual(db.execute.call_args_list[1].args[0], "SHOW transaction_read_only")
        db.rollback.assert_called_once()
        db.close.assert_called_once()

    def test_connection_fails_closed_if_server_is_not_read_only(self):
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = {"transaction_read_only": "off"}
        with patch("src.review.postgres_source._reachable_hostaddr", return_value=None), \
                patch("psycopg.connect", return_value=db):
            with self.assertRaisesRegex(PostgresReviewSourceError, "refused read-only"):
                with self.source.connect():
                    pass

    def test_resolved_public_ipv4_is_pinned_without_changing_hostname_tls(self):
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = {"transaction_read_only": "on"}
        with patch("src.review.postgres_source._reachable_hostaddr", return_value="203.0.113.9"), \
                patch("psycopg.connect", return_value=db) as connect:
            with self.source.connect():
                pass
        self.assertEqual(connect.call_args.kwargs["hostaddr"], "203.0.113.9")
        self.assertIn("example.invalid", connect.call_args.args[0])


@unittest.skipUnless(
    os.environ.get("V2_TEST_DATABASE_URL"),
    "V2_TEST_DATABASE_URL is required for the isolated V2 Review API proof",
)
class V2PostgresReviewApiIntegrationTests(unittest.TestCase):
    def test_generated_phase3_actor_appears_through_shared_review_api(self):
        from urllib.parse import urlsplit

        from fastapi.testclient import TestClient
        from backend import app as backend

        database_url = os.environ["V2_TEST_DATABASE_URL"]
        parsed = urlsplit(database_url.replace("postgresql+psycopg2", "postgresql", 1))
        self.assertIn(parsed.hostname, {"127.0.0.1", "localhost"})
        self.assertEqual(parsed.port, 55432)
        self.assertTrue(parsed.path.removeprefix("/").endswith("_test"))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runs = RunStore(root / "runs.sqlite3")
            review = ReviewStore(root / "review.sqlite3", enable_test_canonical=True)
            source = PostgresReviewSource(database_url)
            bridge = MagicMock(configured=False)
            with patch.object(backend, "map_store", return_value=runs), \
                    patch.object(backend, "review_store", return_value=review), \
                    patch.object(backend, "review_postgres_source", return_value=source), \
                    patch.object(backend, "review_admission_bridge", return_value=bridge):
                backend._review_sync_last = 0.0
                backend._review_sync_store_key = None
                with TestClient(backend.app) as client:
                    response = client.get(
                        "/api/review/candidates",
                        params={"status": "all", "entity_type": "actor", "refresh": True},
                    )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["sync_warnings"], [])
        generated = [
            candidate for candidate in response.json()["candidates"]
            if candidate.get("agent_metadata", {}).get("source_table") == "review_item"
            and str(candidate.get("reviewed_payload", {}).get("name", "")).startswith(
                "Functional New Actor "
            )
        ]
        self.assertTrue(generated, "the Phase 3 actor was not exposed by the shared Review API")
        candidate = generated[-1]
        payload = candidate["reviewed_payload"]
        self.assertEqual(candidate["agent_metadata"]["review_kind"], "verify_actor")
        self.assertEqual(payload["actor_category"], "company")
        self.assertEqual(payload["category_type"], "corporate_rd_center")
        self.assertEqual(payload["location_city"], "Boston")
        self.assertEqual(payload["state"], "MA")
        self.assertEqual(payload["region"], "northeast")
        self.assertEqual(payload["country"], "US")
        self.assertTrue(candidate["evidence"])


if __name__ == "__main__":
    unittest.main()
