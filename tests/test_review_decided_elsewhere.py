"""A check decided somewhere else leaves Review (SAFE, 25 Nov 2026).

SAFE's "Awaiting Verification" check was approved in the database when SAFE was
verified, but Review kept its own copy pending. Review now folds away its copy of
every check the database no longer has waiting.

Runs on a local copy of production (V2_TEST_DATABASE_URL, a *_test database).
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

import pytest

DB = os.environ.get("V2_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB, reason="V2_TEST_DATABASE_URL is required")


@pytest.fixture
def source():
    parts = urlsplit(DB.replace("postgresql+psycopg://", "postgresql://"))
    assert parts.hostname in {"127.0.0.1", "localhost"} and parts.path.rstrip("/").endswith("_test")
    from src.review.postgres_source import PostgresReviewSource

    return PostgresReviewSource(DB.replace("+psycopg", ""))


def _ids(source, status_clause: str) -> list[str]:
    with source.connect() as db:
        return [r["review_item_id"] for r in db.execute(
            "SELECT review_item_id::text AS review_item_id FROM review_item "
            f"WHERE {status_clause} LIMIT 50").fetchall()]


def test_decided_checks_are_retired_and_waiting_ones_still_listed(source):
    decided, waiting = _ids(source, "status <> 'pending'"), _ids(source, "status = 'pending'")
    if not decided or not waiting:
        pytest.skip("this copy needs both decided and waiting review items")
    candidates, _ = source.fetch_candidates()
    listed = {c["source_key"] for c in candidates}
    for review_id in decided:
        key = f"postgres:review_item:{review_id}"
        assert source.retired_keys.get(key) == "decided_elsewhere"
        assert key not in listed
    # Waiting checks are never treated as decided (they may be hidden for another reason).
    for review_id in waiting:
        assert source.retired_keys.get(f"postgres:review_item:{review_id}") != "decided_elsewhere"


def test_review_folds_away_its_pending_copy_of_a_decided_check(source, tmp_path):
    from src.review.store import ReviewStore, _external_candidate_id

    decided = _ids(source, "status <> 'pending'")
    if not decided:
        pytest.skip("this copy has no decided review items")
    key = f"postgres:review_item:{decided[0]}"
    store = ReviewStore(tmp_path / "review.sqlite3")
    # The copy Review took while the check was still waiting.
    store.sync_external_candidates([{
        "source_key": key, "source_run_id": "v2-review:unscoped", "entity_type": "actor",
        "payload": {"name": "SAFE"}, "source_description": "Architecture V2 verify_actor review",
    }])
    assert store.get(_external_candidate_id(key))["folded_into"] is None
    candidates, _ = source.fetch_candidates()
    store.sync_external_candidates(candidates, retired=source.retired_keys)
    row = store.get(_external_candidate_id(key))
    assert row["folded_into"] == "decided_elsewhere" and row["status"] == "pending_review"
