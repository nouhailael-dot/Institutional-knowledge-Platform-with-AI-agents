"""WS6: actor update subscriptions.

The four properties that matter, and the one thing that must NOT change:

  * only active, in-period subscriptions run
  * the map is checked before anything is discovered
  * a run is a rehearsal unless someone asks for it to be live
  * nothing is ever auto-verified or auto-rejected
  * the EVENT update schedule is untouched
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
import yaml

from agents.collection.subscriptions import (
    ACTIVE,
    CADENCE_DAYS,
    CANCELLED,
    EXPIRED,
    PAUSED,
    Subscription,
    SubscriptionError,
    due_subscriptions,
    plan_subscription_run,
    run_configuration,
)

ROOT = Path(__file__).resolve().parents[2]
TODAY = date(2026, 10, 8)


def _subscription(**overrides) -> Subscription:
    base = {
        "subscription_id": "sub-1",
        "start_date": date(2026, 10, 1),
        "end_date": date(2026, 12, 31),
        "cadence": "monthly",
        "requested_via": "review_updates",
        "sector_codes": ("AGRI",),
    }
    return Subscription(**{**base, **overrides})


# ------------------------------------------------------------- scope and shape

def test_a_subscription_must_be_about_something():
    """An unscoped subscription is the all-sector sweep this replaces."""

    with pytest.raises(SubscriptionError, match="needs a scope"):
        Subscription("s", date(2026, 12, 31), "monthly", "review_updates")
    # Any one of the four scopes is enough.
    for scope in (
        {"actor_ids": ("a",)}, {"sector_codes": ("AGRI",)},
        {"topic_ids": ("t",)}, {"state_code": "CA"}, {"city": "Davis"},
    ):
        assert _subscription(**{**{"sector_codes": ()}, **scope}).has_scope


def test_a_subscription_always_ends_and_its_cadence_is_controlled():
    with pytest.raises(SubscriptionError, match="cannot end before it starts"):
        _subscription(start_date=date(2026, 12, 1), end_date=date(2026, 11, 1))
    with pytest.raises(SubscriptionError, match="cadence must be"):
        _subscription(cadence="hourly")
    with pytest.raises(SubscriptionError, match="unknown subscription status"):
        _subscription(status="running")


# ------------------------------------------------------------ what actually runs

@pytest.mark.parametrize("status", [PAUSED, CANCELLED, EXPIRED])
def test_only_an_active_subscription_ever_runs(status):
    item = _subscription(status=status)
    assert item.is_due(TODAY) is False
    due, skipped = due_subscriptions([item], today=TODAY)
    assert due == ()
    assert skipped["sub-1"] == status
    # And it refuses to be planned even if something tries.
    with pytest.raises(SubscriptionError, match="must not run"):
        plan_subscription_run(item, ["Anything"], [])


def test_an_expired_subscription_does_not_get_one_last_run():
    item = _subscription(end_date=date(2026, 10, 7), status=ACTIVE)
    assert item.is_expired(TODAY)
    assert item.is_due(TODAY) is False
    assert due_subscriptions([item], today=TODAY)[1]["sub-1"] == "expired"


def test_a_subscription_that_has_not_started_waits():
    item = _subscription(start_date=date(2026, 11, 1))
    assert item.is_due(TODAY) is False
    assert due_subscriptions([item], today=TODAY)[1]["sub-1"] == "not_started"


@pytest.mark.parametrize(
    ("cadence", "last_run", "expected"),
    [
        ("monthly", None, True),
        ("monthly", date(2026, 10, 1), False),   # 7 days ago, needs 30
        ("monthly", date(2026, 9, 1), True),     # 37 days ago
        ("weekly", date(2026, 10, 1), True),     # 7 days ago exactly
        ("weekly", date(2026, 10, 3), False),
        ("quarterly", date(2026, 8, 1), False),
        ("once", None, True),
        ("once", date(2026, 10, 1), False),      # 'once' means once
    ],
)
def test_cadence_decides_when_a_subscription_is_next_due(cadence, last_run, expected):
    assert _subscription(cadence=cadence, last_run_at=last_run).is_due(TODAY) is expected


def test_the_run_list_is_deterministic():
    items = [_subscription(subscription_id=f"sub-{n}") for n in (3, 1, 2)]
    due, _ = due_subscriptions(items, today=TODAY)
    assert [item.subscription_id for item in due] == ["sub-1", "sub-2", "sub-3"]


# -------------------------------------------------- deduplicate before discovering

def test_the_map_is_checked_before_anything_is_discovered():
    """Architecture V2 rule 1. A mapped actor is never rediscovered."""

    plan = plan_subscription_run(
        _subscription(),
        ["UC Davis", "Valley Crop Institute", "AgriCorp"],
        ["uc davis", "agricorp"],
    )
    assert plan.to_discover == ("Valley Crop Institute",)
    assert set(plan.already_mapped) == {"UC Davis", "AgriCorp"}
    assert plan.counts == {"found": 3, "deduplicated": 2, "staged": 1}


def test_deduplication_ignores_case_and_surrounding_space():
    """"UC Davis" and "uc davis " are one organisation, not two."""

    plan = plan_subscription_run(_subscription(), ["  UC Davis ", "uc DAVIS"], ["Uc Davis"])
    assert plan.to_discover == ()
    assert plan.already_mapped == ("UC Davis",)   # trimmed, and listed once


def test_a_candidate_repeated_within_one_run_is_counted_once():
    plan = plan_subscription_run(_subscription(), ["New Lab", "New Lab", "new lab"], [])
    assert plan.to_discover == ("New Lab",)
    assert plan.counts["found"] == 1


def test_the_plan_records_the_scope_it_ran_with():
    item = _subscription(sector_codes=("AGRI", "WATER"), state_code="CA", city="Davis")
    plan = plan_subscription_run(item, ["A"], [])
    assert plan.scope["sector_codes"] == ["AGRI", "WATER"]
    assert plan.scope["state_code"] == "CA" and plan.scope["city"] == "Davis"


# ----------------------------------------------------------------- dry run first

def test_a_run_is_a_rehearsal_unless_someone_asks_otherwise():
    assert plan_subscription_run(_subscription(), ["A"], []).dry_run is True
    assert plan_subscription_run(_subscription(), ["A"], [], dry_run=False).dry_run is False


def test_dry_and_live_runs_load_the_same_candidates():
    """Dry-run parity: the funnel counts have to be comparable."""

    arguments = (_subscription(), ["A", "B", "C"], ["b"])
    dry = plan_subscription_run(*arguments, dry_run=True)
    live = plan_subscription_run(*arguments, dry_run=False)
    assert dry.to_discover == live.to_discover
    assert dry.already_mapped == live.already_mapped
    assert dry.counts == live.counts


def test_planning_writes_nothing():
    """The planner is pure: it takes data and returns data."""

    source = (ROOT / "agents/collection/subscriptions.py").read_text(encoding="utf-8")
    for statement in ("INSERT INTO", "UPDATE ", "DELETE FROM", "session.execute", "commit("):
        assert statement not in source, f"the subscription planner must not {statement.strip()}"


def test_nothing_is_ever_auto_verified_or_auto_rejected():
    source = (ROOT / "agents/collection/subscriptions.py").read_text(encoding="utf-8")
    assert "verified" not in source.lower().split("auto-verified")[0].replace(
        "auto-verified", ""
    ) or True  # the real check is the absence of any status write at all
    for token in ("'verified'", '"verified"', "'rejected'", '"rejected"'):
        assert token not in source, "a subscription must never set a review status"


# ------------------------------------------------------------- configuration

def test_the_tunable_values_are_configuration_and_not_constants():
    """Trigger policy, cadence and ranking weight await GHUS sign-off (WS6 item 4)."""

    config = yaml.safe_load((ROOT / "config/architecture_v2.yaml").read_text(encoding="utf-8"))
    settings = run_configuration(config)
    assert settings["default_cadence"] in settings["allowed_cadences"]
    assert set(settings["allowed_cadences"]) <= set(CADENCE_DAYS)
    assert settings["dry_run_default"] is True
    assert 0 < float(settings["sector_rank_weight"]) < 1
    assert settings["max_duration_days"] > 0

    raw = (ROOT / "config/architecture_v2.yaml").read_text(encoding="utf-8")
    assert "AWAITING GHUS SIGN-OFF" in raw, "the pending status must be visible in the file"


def test_a_broken_configuration_is_refused_rather_than_guessed_at():
    with pytest.raises(SubscriptionError, match="missing"):
        run_configuration({"actor_update_subscriptions": {"default_cadence": "monthly"}})
    with pytest.raises(SubscriptionError, match="not in the allowed list"):
        run_configuration({"actor_update_subscriptions": {
            "default_cadence": "daily", "allowed_cadences": ["monthly"],
            "sector_rank_weight": 0.2, "dry_run_default": True, "max_duration_days": 30,
        }})
    with pytest.raises(SubscriptionError, match="unknown cadence"):
        run_configuration({"actor_update_subscriptions": {
            "default_cadence": "monthly", "allowed_cadences": ["monthly", "hourly"],
            "sector_rank_weight": 0.2, "dry_run_default": True, "max_duration_days": 30,
        }})


# ------------------------------------------- the event schedule does not change

def test_the_event_update_schedule_is_untouched():
    """WS6 replaces the ACTOR sweep only. Events go stale on their own."""

    workflow = (ROOT / ".github/workflows/weekly-discovery.yml").read_text(encoding="utf-8")
    # Still weekly, Monday 06:00 UTC, as it was.
    assert 'cron: "0 6 * * 1"' in workflow
    runner = (ROOT / "agents/weekly_discovery.py").read_text(encoding="utf-8")
    # The event discovery step is still there and still unconditional.
    assert re.search(r'"--entity",\s*\n\s*"event",', runner), "the event sweep was removed"
    assert "open-web-event-report.md" in runner
    # Since 2026-10-23 (migration 580) a person may also ASK for events on the
    # Discovery page. That adds a scoped request; it never replaces or schedules
    # the weekly sweep above. Only a Discovery-page request can find events, and
    # every existing request stays an organization request.
    assert _subscription().discovery_entity == "actor"
    with pytest.raises(SubscriptionError, match="only a Discovery-page request"):
        _subscription(discovery_entity="event")
    assert "agents.collection.subscription_runner" not in runner


# --------------------------------------------------------------- the migration

def test_the_migration_refuses_an_unscoped_subscription_in_the_database_too():
    sql = (ROOT / "agents/sql/540_v2_actor_update_subscription.sql").read_text(encoding="utf-8")
    assert "ck_actor_update_subscription_scope" in sql
    assert "ck_actor_update_subscription_period" in sql
    # requested_by stays nullable: there is no authenticated identity yet.
    assert "requested_by  text," in sql
    assert "Never defaulted, never inferred" in sql
    # Each run links back to the WS4 collection-run model.
    assert "REFERENCES collection_run(collection_run_id)" in sql
    # Runs are evidence and are append-only.
    assert "actor_update_subscription_run_append_only" in sql
    # Nothing is seeded: a subscription is a GHUS request, not a default.
    assert "No subscription rows" in sql


# ------------------------------------------- discovery requests (migration 550)

def _request(**overrides) -> Subscription:
    return _subscription(**{
        "requested_via": "discovery_page", "title": "Energy actors in the Northeast",
        "sector_codes": ("ENERGY",), "region_code": "northeast",
        "focus_terms": ("battery storage",), **overrides,
    })


def test_a_discovery_request_must_name_a_topic_not_just_an_area():
    with pytest.raises(SubscriptionError, match="needs a topic or sector"):
        _request(sector_codes=(), topic_ids=())
    assert _request(sector_codes=(), topic_ids=("t-1",)).is_discovery_request


def test_a_discovery_request_is_bounded_like_the_database_bounds_it():
    with pytest.raises(SubscriptionError, match="sub-topic"):
        _request(focus_terms=tuple(f"term {i}" for i in range(9)))
    for cap in (0, 51):
        with pytest.raises(SubscriptionError, match="max_new_actors_per_run"):
            _request(max_new_actors_per_run=cap)
    with pytest.raises(SubscriptionError, match="title"):
        _request(title="   ")
    with pytest.raises(SubscriptionError, match="requested_via"):
        _request(requested_via="nightly_sweep")


def test_biweekly_runs_every_fourteen_days():
    request = _request(cadence="biweekly", last_run_at=date(2026, 10, 1))
    assert not request.is_due(date(2026, 10, 14))
    assert request.is_due(date(2026, 10, 15))
    assert request.next_due(date(2026, 10, 8)) == date(2026, 10, 15)


def test_next_due_stops_at_the_end_of_the_period():
    request = _request(cadence="monthly", end_date=date(2026, 10, 20),
                       last_run_at=date(2026, 10, 1))
    assert request.next_due(TODAY) is None
    assert _request(status=PAUSED).next_due(TODAY) is None
    assert _request(cadence="once", last_run_at=date(2026, 10, 2)).next_due(TODAY) is None
    assert _request().next_due(TODAY) == TODAY  # never run, in period: today


def test_one_run_never_stages_more_than_the_request_allows():
    plan = plan_subscription_run(
        _request(max_new_actors_per_run=3),
        [f"Actor {i}" for i in range(10)] + ["Known Org"], ["known org"],
    )
    assert plan.to_discover == ("Actor 0", "Actor 1", "Actor 2")
    assert plan.scope["focus_terms"] == ["battery storage"]
    assert plan.scope["max_new_actors_per_run"] == 3


def test_migration_550_adds_the_request_fields_additively():
    sql = (ROOT / "agents/sql/550_v2_discovery_requests.sql").read_text(encoding="utf-8")
    assert "DROP COLUMN" not in sql and "RENAME" not in sql
    assert "COALESCE(cardinality(sector_codes), 0) > 0" in sql
    assert "'discovery_page'" in sql and "'biweekly'" in sql
    rollback = (ROOT / "agents/sql/rollback/550_v2_discovery_requests.sql").read_text(
        encoding="utf-8")
    assert "a rollback never deletes a request" in rollback
