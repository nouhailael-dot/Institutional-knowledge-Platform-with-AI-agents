"""The automatic follow-up checks ("Map checks") are off the platform (GHUS, 25 Nov 2026).

They stay in the database. Review neither lists new ones nor keeps its earlier
copies listed; organization-update items and request candidates are unaffected.
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


def _waiting_check(source) -> str | None:
    """A waiting check that belongs to no organization update."""
    with source.connect() as db:
        row = db.execute(
            "SELECT ri.review_item_id::text AS review_item_id FROM review_item ri "
            "WHERE ri.status = 'pending' AND ri.entity_type = 'actor' "
            "AND NOT (ri.payload ? 'update_run_id') LIMIT 1").fetchone()
    return row["review_item_id"] if row else None


def test_no_map_check_is_listed_and_each_is_retired(source):
    from src.review import postgres_source

    assert postgres_source.SHOW_MAP_CHECKS is False
    candidates, _ = source.fetch_candidates()
    assert not [c for c in candidates if str(c["source_run_id"]).startswith("v2-review:")]
    hidden = [k for k, why in source.retired_keys.items() if why == postgres_source.MAP_CHECKS_HIDDEN]
    if _waiting_check(source) is None:
        pytest.skip("this copy has no waiting follow-up checks")
    assert hidden and all(k.startswith("postgres:review_item:") for k in hidden)


def test_review_folds_away_the_copies_it_already_had(source, tmp_path):
    from src.review.store import ReviewStore, _external_candidate_id

    candidates, _ = source.fetch_candidates()
    hidden = [k for k, why in source.retired_keys.items() if why == "map_checks_hidden"]
    if not hidden:
        pytest.skip("this copy has no waiting follow-up checks")
    store = ReviewStore(tmp_path / "review.sqlite3")
    store.sync_external_candidates([{
        "source_key": hidden[0], "source_run_id": "v2-review:unscoped", "entity_type": "actor",
        "payload": {"name": "SAFE"}, "source_description": "Architecture V2 geocode review",
    }])
    store.sync_external_candidates(candidates, retired=source.retired_keys)
    row = store.get(_external_candidate_id(hidden[0]))
    assert row["folded_into"] == "map_checks_hidden" and row["status"] == "pending_review"


def test_organization_updates_and_requests_still_appear(source):
    candidates, _ = source.fetch_candidates()
    kinds = {str(c["source_run_id"]).split(":", 1)[0] for c in candidates}
    assert "v2-review" not in kinds
    assert kinds & {"discovery", "actor-update", "datafeed"} or not candidates
