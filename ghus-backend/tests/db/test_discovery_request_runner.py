"""Discovery requests end to end on the isolated test database.

The search itself is replaced by a stub - this proves the bookkeeping: a
request is created, is due, runs, leaves an append-only run record, moves to
its next date, and closes when its period ends. It never touches production.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from agents.collection import subscription_store as store
from agents.collection.subscription_runner import run_due_requests
from agents.collection.subscriptions import SubscriptionError

# Run records are append-only, so these tests leave rows behind by design. They
# therefore run only against a disposable database made for them, e.g.
#   CREATE DATABASE ghus_v2_requests_test TEMPLATE ghus_v2_cutover_test;  + 550
# never against a demo or shared one.
URL = os.environ.get("V2_REQUESTS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not URL or "127.0.0.1:55432" not in URL or not URL.endswith("_requests_test"),
    reason="V2_REQUESTS_TEST_DATABASE_URL (a disposable *_requests_test database) is required",
)
TODAY = date(2026, 10, 14)
SEARCH_RUN = "00000000-0000-4000-8000-000000000550"
CONFIG = {"max_pages_fetched": 30, "max_usd_per_run": 5.0, "request_query_limit": 8}


@dataclass(frozen=True)
class _Candidate:
    score_band: str | None
    triage_verdict: str


@pytest.fixture
def session():
    engine = create_engine(URL)
    with Session(engine) as db:
        has_550 = db.execute(text(
            "SELECT 1 FROM information_schema.columns WHERE table_name = "
            "'actor_update_subscription' AND column_name = 'focus_terms'"
        )).first()
        if not has_550:
            pytest.skip("migration 550 is not applied to this database")
        created: list[str] = []
        yield db, created
        db.rollback()
    engine.dispose()


def _create(db, created, **overrides):
    fields = {
        "title": "Test: energy storage in the Northeast",
        "sector_codes": ["ENERGY"],
        "focus_terms": ["battery storage"],
        "region_code": "northeast",
        "start_date": TODAY,
        "end_date": TODAY + timedelta(days=20),
        "cadence": "weekly",
        "max_new_actors_per_run": 3,
        **overrides,
    }
    written = store.create_request(db, live=True, **fields)
    created.append(written.subscription_id)
    return written.subscription_id


def _row(db, subscription_id):
    return db.execute(text(
        "SELECT status, last_run_at, next_due_at FROM actor_update_subscription "
        "WHERE actor_update_subscription_id = CAST(:id AS uuid)"
    ), {"id": subscription_id}).mappings().one()


def test_a_dry_create_writes_nothing(session):
    db, _ = session
    before = db.execute(text("SELECT count(*) FROM actor_update_subscription")).scalar()
    # Dated from the fixed TODAY, like every other request here: left to default
    # to the real date, the end date fell before the start once TODAY passed.
    result = store.create_request(db, title="Dry", sector_codes=["AGRI"], start_date=TODAY,
                                  end_date=TODAY + timedelta(days=5), cadence="once")
    assert result.live is False and result.subscription_id is None
    assert db.execute(text("SELECT count(*) FROM actor_update_subscription")).scalar() == before


def test_a_request_runs_records_and_moves_on(session):
    db, created = session
    subscription_id = _create(db, created)
    seen = []

    def discover(request):
        seen.append(request)
        return {"status": "succeeded", "status_reason": "", "run_id": SEARCH_RUN,
                "stats": {"search_results_unique": 12, "search_results_deduplicated": 2,
                          "pages_fetched": 6, "cost_usd": 0.4},
                "candidates": [_Candidate("auto_high", "accepted"),
                               _Candidate("review", "review"),
                               _Candidate("auto_low", "rejected")]}

    report = run_due_requests(db, live=True, today=TODAY, config=CONFIG, discover=discover)
    mine = [o for o in report.outcomes if o.subscription_id == subscription_id]
    assert len(mine) == 1 and mine[0].status == "succeeded"
    assert seen[-1].focus_terms == ("battery storage",) and seen[-1].max_new_actors == 3
    assert all("battery storage" in q for q in mine[0].queries)

    run = db.execute(text(
        "SELECT cr.status, cr.trigger_type, cr.cadence, cr.found_count, cr.staged_count, "
        "cr.review_item_count, cr.fetch_count FROM actor_update_subscription_run sr "
        "JOIN collection_run cr USING (collection_run_id) "
        "WHERE sr.actor_update_subscription_id = CAST(:id AS uuid)"
    ), {"id": subscription_id}).mappings().one()
    assert dict(run) == {"status": "succeeded", "trigger_type": "subscription",
                         "cadence": "weekly", "found_count": 12, "staged_count": 1,
                         "review_item_count": 1, "fetch_count": 6}
    row = _row(db, subscription_id)
    assert row["status"] == "active" and row["next_due_at"].date() == TODAY + timedelta(days=7)
    runs = store.load_request_runs(db, subscription_id)
    assert runs[0]["search_run_id"] == SEARCH_RUN

    # Not due again tomorrow; the run record cannot be rewritten.
    again = run_due_requests(db, live=False, today=TODAY + timedelta(days=1), config=CONFIG)
    assert again.skipped.get(subscription_id) == "not_due"
    with pytest.raises(Exception, match="append-only"):
        db.execute(text("DELETE FROM actor_update_subscription_run "
                        "WHERE actor_update_subscription_id = CAST(:id AS uuid)"),
                   {"id": subscription_id})
    db.rollback()


def test_a_failed_run_is_recorded_and_the_request_stays_due(session):
    db, created = session
    subscription_id = _create(db, created, cadence="biweekly")

    def discover(request):
        raise RuntimeError("search provider unavailable")

    report = run_due_requests(db, live=True, today=TODAY, config=CONFIG, discover=discover)
    mine = next(o for o in report.outcomes if o.subscription_id == subscription_id)
    assert mine.status == "failed" and "unavailable" in mine.status_reason
    assert _row(db, subscription_id)["last_run_at"] is None
    plan = run_due_requests(db, live=False, today=TODAY, config=CONFIG)
    assert subscription_id in {o.subscription_id for o in plan.outcomes}


def test_a_once_request_closes_after_its_run(session):
    db, created = session
    subscription_id = _create(db, created, cadence="once")
    ok = {"status": "succeeded", "stats": {}, "candidates": []}
    run_due_requests(db, live=True, today=TODAY, config=CONFIG, discover=lambda r: ok)
    assert _row(db, subscription_id)["status"] == "expired"


def test_pause_resume_cancel(session):
    db, created = session
    subscription_id = _create(db, created)
    store.change_status(db, subscription_id, "pause", live=True)
    plan = run_due_requests(db, live=False, today=TODAY, config=CONFIG)
    assert plan.skipped[subscription_id] == "paused"
    store.change_status(db, subscription_id, "resume", live=True)
    store.change_status(db, subscription_id, "cancel", live=True)
    with pytest.raises(SubscriptionError, match="cannot be resumed"):
        store.change_status(db, subscription_id, "resume", live=True)


def test_the_database_refuses_a_request_without_a_topic(session):
    db, _ = session
    with pytest.raises(Exception, match="ck_actor_update_subscription_discovery_topic"):
        db.execute(text(
            "INSERT INTO actor_update_subscription (end_date, cadence, requested_via, "
            "region_code) VALUES (:end, 'weekly', 'discovery_page', 'northeast')"
        ), {"end": TODAY + timedelta(days=5)})
    db.rollback()


def test_run_now_ignores_the_cadence_but_not_the_status(session):
    db, created = session
    subscription_id = _create(db, created, cadence="monthly", end_date=TODAY + timedelta(days=90))
    ok = {"status": "succeeded", "stats": {}, "candidates": []}
    run_due_requests(db, live=True, today=TODAY, config=CONFIG, discover=lambda r: ok)
    # Not due for a month - but a person asked for it now.
    later = TODAY + timedelta(days=2)
    report = run_due_requests(db, live=True, today=later, config=CONFIG,
                              discover=lambda r: ok, request_id=subscription_id)
    assert [o.subscription_id for o in report.outcomes] == [subscription_id], (
        report.skipped, report.invalid)
    store.change_status(db, subscription_id, "pause", live=True)
    paused = run_due_requests(db, live=False, today=later, config=CONFIG,
                              request_id=subscription_id)
    assert paused.outcomes == [] and paused.skipped[subscription_id] == "paused"
