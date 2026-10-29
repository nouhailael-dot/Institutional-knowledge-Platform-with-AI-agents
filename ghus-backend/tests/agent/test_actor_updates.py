"""Updating an actor: the predicted Phase 11 outcome of each box, and which boxes are read."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from agents.collection import actor_updates as au
from agents.collection.actor_updates import (
    PRESETS,
    ActorUpdateError,
    classify,
    plan_fields,
    prioritise,
    settings,
)

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)
LIMITS = settings({})


def _recorded(value, *, confidence="medium", when="2026-09-01T00:00:00+00:00", by="agent"):
    return {"collection_state": "found", "fact_value": value, "confidence": confidence,
            "retrieved_at": when, "creator_class": by, "source_url": "https://x.example/old"}


def _read(value):
    return {"collection_state": "found", "value": value, "confidence": "high",
            "source_url": "https://x.example/about", "date_read": NOW.isoformat()}


SILENT = {"collection_state": "not_found", "value": None, "source_url": "https://x.example/"}


def _outcome(before, evidence, rejected=None, field="funding_signal"):
    return classify(field, before, evidence, rejected, read_at=NOW, topic_name="Water")


# ------------------------------------------------------------ classification

def test_a_box_that_was_empty_and_is_now_stated_is_new():
    box = _outcome(None, _read("$2M from DOE in 2026."))
    assert (box["outcome"], box["group"]) == ("new", "new")
    assert box["proposed"]["source_url"] == "https://x.example/about"
    assert box["proposed"]["confidence"] == "high"
    assert box["topic"] == "Water"


def test_stronger_newer_evidence_changes_the_value_and_keeps_the_old_one():
    box = _outcome(_recorded("$1M grant."), _read("$2M grant."))
    assert (box["outcome"], box["group"]) == ("changed", "changed")
    assert box["previous"]["value"] == "$1M grant."
    assert box["proposed"]["value"] == "$2M grant."
    assert "history" in box["resolution"]
    assert "was: 1M" in box["what_changed"] or "1" in box["what_changed"]


def test_weaker_or_older_evidence_is_a_conflict_for_review():
    later = (NOW + timedelta(days=30)).isoformat()
    box = _outcome(_recorded("$1M grant.", confidence="high", when=later), _read("$2M grant."))
    assert (box["outcome"], box["group"]) == ("conflict", "conflicts")
    assert "Review" in box["resolution"]


def test_a_value_set_by_ghus_is_never_overwritten():
    box = _outcome(_recorded("$1M grant.", by="ghus_human"), _read("$2M grant."))
    assert (box["outcome"], box["group"]) == ("protected", "conflicts")
    assert box["previous"]["set_by"] == "GHUS"
    assert "never overwritten" in box["resolution"]


def test_the_same_value_is_corroboration_not_a_change():
    box = _outcome(_recorded({"date": "March 2026", "description": "X"}),
                   _read({"date": "March 2026", "description": "X"}), field="recent_activity")
    assert (box["outcome"], box["group"]) == ("corroborated", "confirmed")


def test_a_reworded_fact_is_corroboration_not_an_update():
    """Seen on CPower Energy, 2026-10-17: the same funding fact, reworded."""
    before = _recorded("Paid customers over $1.5 billion from demand response and energy programs.")
    after = _read("CPower has paid customers over $1.5 billion from demand response and energy programs.")
    assert _outcome(before, after)["outcome"] == "corroborated"


def test_a_reading_that_only_says_less_corroborates_instead_of_replacing():
    """Seen on CPower Energy, 2026-10-18: the About page dropped the figures."""
    before = _recorded("CPower Energy is an NRG company (NRG Energy has acquired CPower); "
                       "manages 4,600 customers and 21,000 participating sites across the U.S.")
    after = _read("CPower Energy is an NRG company (subsidiary of NRG Energy)")
    assert _outcome(before, after, field="ownership_and_size")["outcome"] == "corroborated"
    # Saying more - a new figure - is still a change.
    more = _read("CPower Energy is an NRG company with 5,200 customers.")
    assert _outcome(before, more, field="ownership_and_size")["outcome"] == "changed"


def test_a_different_number_is_a_different_fact():
    before = _recorded("Paid customers over $1.5 billion from demand response.")
    after = _read("Paid customers over $2 billion from demand response.")
    assert _outcome(before, after)["outcome"] == "changed"


def test_a_silent_page_never_erases_what_is_recorded():
    box = _outcome(_recorded("$1M grant."), SILENT)
    assert (box["outcome"], box["group"]) == ("unchanged", "no_change")
    assert box["previous"]["value"] == "$1M grant." and box["proposed"] is None
    assert au.RESOLUTION["unchanged"].startswith("Nothing is written")


def test_nothing_recorded_and_nothing_stated_is_missing_not_inapplicable():
    box = _outcome(None, SILENT)
    assert (box["outcome"], box["group"]) == ("not_found", "missing")


def test_a_box_not_read_with_nothing_recorded_is_not_yet_collected():
    box = _outcome(None, None)
    assert (box["outcome"], box["group"]) == ("not_yet_collected", "missing")


def test_a_refused_answer_is_reported_and_never_written_as_not_found():
    box = _outcome(None, SILENT, "the quote given is not on the page it names")
    assert box["outcome"] == "not_found"
    assert "quote" in box["reason"]
    assert box["resolution"].startswith("Nothing is written")


def test_a_refused_answer_keeps_what_is_recorded():
    box = _outcome(_recorded({"date": "Aug. 12, 2026", "description": "X"}), SILENT,
                   "the quote given is not on the page it names", field="recent_activity")
    assert box["outcome"] == "unchanged" and box["reason"]


def test_public_findings_hide_the_evidence_kept_for_apply():
    box = au.public(_outcome(None, _read("$2M.")))
    assert not any(key.startswith("_") for key in box)


# ------------------------------------------------------------- which boxes

SCHEMA = ["location", "funding_signal", "recent_activity", "ownership_and_size"]


def test_general_reads_every_box_of_the_schema_and_nothing_else():
    read, skipped = plan_fields("general", SCHEMA, {}, today=NOW, limits=LIMITS)
    assert read == SCHEMA and skipped == []


def test_missing_reads_only_empty_boxes_and_waits_before_rechecking_not_found():
    current = {
        "location": _recorded("Austin, TX"),
        "funding_signal": {"collection_state": "not_found", "fact_value": None,
                           "retrieved_at": (NOW - timedelta(days=10)).isoformat()},
        "recent_activity": {"collection_state": "not_found", "fact_value": None,
                            "retrieved_at": (NOW - timedelta(days=200)).isoformat()},
    }
    read, skipped = plan_fields("missing", SCHEMA, current, today=NOW, limits=LIMITS)
    assert read == ["recent_activity", "ownership_and_size"]
    reasons = {s["field"]: s["reason"] for s in skipped}
    assert reasons["location"] == "Already has a value."
    assert "10 days ago" in reasons["funding_signal"]


def test_outdated_reads_only_stale_values_and_time_sensitive_ones_sooner():
    old = (NOW - timedelta(days=200)).isoformat()
    current = {
        "location": _recorded("Austin, TX", when=old),           # 365-day window: fresh
        "recent_activity": _recorded("Opened a lab.", when=old),  # 180-day window: stale
        "funding_signal": _recorded("$1M.", when=(NOW - timedelta(days=400)).isoformat()),
    }
    read, skipped = plan_fields("outdated", SCHEMA, current, today=NOW, limits=LIMITS)
    assert read == ["funding_signal", "recent_activity"]
    reasons = {s["field"]: s["reason"] for s in skipped}
    assert "still fresh" in reasons["location"]
    assert "Missing information" in reasons["ownership_and_size"]


def test_specific_reads_only_the_chosen_boxes_and_refuses_inapplicable_ones():
    read, skipped = plan_fields("specific", SCHEMA, {}, fields=["funding_signal", "rankings"],
                                today=NOW, limits=LIMITS)
    assert read == ["funding_signal"]
    assert skipped == [{"field": "rankings", "reason":
                        "Not in this actor's category schema, so it is never filled."}]
    with pytest.raises(ActorUpdateError):
        plan_fields("specific", SCHEMA, {}, fields=["rankings"], today=NOW, limits=LIMITS)


def test_specific_changes_by_type_read_only_those_boxes_the_category_has():
    # "Funding & Partnerships": funding + partnerships; only funding_signal is in this schema.
    read, skipped = plan_fields("specific", SCHEMA, {}, categories=["funding", "partnerships"],
                                today=NOW, limits=LIMITS)
    assert read == ["funding_signal"]
    # Boxes outside the category are not listed as "not in schema" noise.
    assert skipped == []
    # "Organization & Activities": organisation boxes plus the category's own.
    read, _ = plan_fields("specific", SCHEMA, {}, categories=["organization", "category"],
                          category_fields=("recent_activity",), today=NOW, limits=LIMITS)
    assert read == ["recent_activity", "ownership_and_size"]
    read, _ = plan_fields("specific", SCHEMA, {}, categories=["geography"], today=NOW, limits=LIMITS)
    assert read == ["location"]
    # Nothing of the chosen type in this category: refused, never widened.
    with pytest.raises(ActorUpdateError, match="None of the chosen types"):
        plan_fields("specific", ["location"], {}, categories=["funding"], today=NOW, limits=LIMITS)
    # Chosen boxes still win over types.
    read, _ = plan_fields("specific", SCHEMA, {}, fields=["location"], categories=["funding"],
                          today=NOW, limits=LIMITS)
    assert read == ["location"]


def test_change_categories_reorder_and_never_add_boxes():
    assert prioritise(SCHEMA, ["funding"]) == [
        "funding_signal", "location", "recent_activity", "ownership_and_size"]
    read, _ = plan_fields("general", SCHEMA, {}, categories=["geography", "funding"],
                          today=NOW, limits=LIMITS)
    assert sorted(read) == sorted(SCHEMA)
    assert read[:2] == ["location", "funding_signal"]
    read, _ = plan_fields("general", SCHEMA, {}, categories=["category"],
                          category_fields=("ownership_and_size",), today=NOW, limits=LIMITS)
    assert read[0] == "ownership_and_size"


def test_an_unknown_scope_is_refused():
    with pytest.raises(ActorUpdateError):
        plan_fields("everything", SCHEMA, {}, today=NOW, limits=LIMITS)


def test_change_category_boxes_are_real_light_pull_boxes():
    from agents.collection.light_pull_reader import FIELD_CRITERIA

    for category in au.CHANGE_CATEGORIES.values():
        for field in category["fields"]:
            assert field in FIELD_CRITERIA, field
    for fields in PRESETS.values():
        for field in fields:
            assert field in FIELD_CRITERIA, field


def test_limits_come_from_configuration():
    assert settings({"actor_updates": {"max_usd_per_actor": 0.05}})["max_usd_per_actor"] == 0.05
    from agents.discovery.search.run import load_open_web_config

    configured = settings(load_open_web_config())
    assert configured["max_usd_per_actor"] > 0
    assert configured["max_actors_per_request"] >= 1


# ---------------------------------------------------------------- checks

def test_a_check_id_cannot_name_a_file_outside_the_runs_folder(tmp_path):
    with pytest.raises(ActorUpdateError):
        au._check_path(tmp_path, "../../.env")


def test_writing_outside_a_local_test_database_needs_the_bridge_switch(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user@db.example.supabase.co:5432/postgres")
    monkeypatch.delenv("ACTOR_UPDATE_WRITES_ENABLED", raising=False)
    assert au.main(["apply", "--check-id", "0" * 32]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False and "ACTOR_UPDATE_WRITES_ENABLED" in result["error"]


# ---------------------------------------------------------------- requests

from datetime import date  # noqa: E402

from agents.collection.actor_updates import request_options  # noqa: E402

TODAY = date(2026, 10, 18)
ACTOR = "11111111-2222-3333-4444-555555555555"


def _request(**changes):
    payload = {"actor_ids": [ACTOR], "scope": "missing", "cadence": "monthly",
               "start_date": "2026-10-20", "end_date": "2027-01-20"}
    payload.update(changes)
    return request_options(payload, config={}, today=TODAY)


def test_a_request_is_normalised_into_what_the_table_stores():
    prepared = _request(categories=["funding"], max_usd_per_run=0.5)
    assert prepared["actor_ids"] == [ACTOR]
    assert prepared["max_usd_per_run"] == 0.5
    assert prepared["options"] == {
        "scope": "missing", "depth": "light", "categories": ["funding"], "fields": [],
        "focus": "", "topic": None, "category": None, "max_actors_per_run": 1}
    # A one-time request ends the day it starts.
    once = _request(cadence="once", end_date=None)
    assert once["end_date"] == once["start_date"]


@pytest.mark.parametrize("changes,words", [
    ({"actor_ids": [], "group": {}}, "never sweeps"),
    ({"group": {"sector": "WATER", "town": "x"}}, "sector, type and state"),
    ({"depth": "deep"}, "Light refresh"),
    ({"scope": "specific"}, "at least one box"),
    ({"max_usd_per_run": 9}, "spend ceiling"),
    ({"max_usd_per_run": -1}, "spend ceiling"),
    ({"max_actors_per_run": 99}, "Actors per run"),
    ({"actor_ids": [str(uuid.uuid4()) for _ in range(21)]}, "at most 20"),
    ({"end_date": None}, "end date"),
    ({"start_date": "2026-10-01"}, "past"),
    ({"end_date": "2030-01-01"}, "at most"),
    ({"cadence": "daily"}, "frequency"),
    ({"surprise": 1}, "Unknown request field"),
])
def test_a_request_that_could_run_unbounded_or_wrong_is_refused(changes, words):
    with pytest.raises(ActorUpdateError, match=words):
        _request(**changes)


def test_specific_changes_may_be_asked_by_type_of_information_alone():
    prepared = _request(scope="specific", categories=["funding", "partnerships"])
    assert prepared["options"]["scope"] == "specific"
    assert prepared["options"]["fields"] == []
    # Without limits from the page, the configured safeguards apply.
    assert prepared["max_usd_per_run"] == LIMITS["max_usd_per_request_run"]
    grouped = _request(actor_ids=[], group={"sector": "WATER"}, scope="general")
    assert grouped["options"]["max_actors_per_run"] == LIMITS["max_actors_per_request"]


def test_a_group_request_needs_a_sector_and_takes_its_facts_there():
    prepared = _request(actor_ids=[], group={"sector": "water", "state": "ca"})
    assert (prepared["sector"], prepared["state"], prepared["options"]["topic"]) == (
        "WATER", "CA", "WATER")


def test_the_subscription_itself_refuses_an_update_request_without_a_ceiling():
    from agents.collection.subscriptions import ACTOR_UPDATES, Subscription, SubscriptionError

    with pytest.raises(SubscriptionError, match="spend ceiling"):
        Subscription(subscription_id="x", end_date=TODAY, cadence="once",
                     requested_via=ACTOR_UPDATES, start_date=TODAY, actor_ids=(ACTOR,),
                     update_options={"scope": "general"})
    ok = Subscription(subscription_id="x", end_date=TODAY, cadence="once",
                      requested_via=ACTOR_UPDATES, start_date=TODAY, actor_ids=(ACTOR,),
                      update_options={"scope": "general"}, max_usd_per_run=0.5)
    assert ok.is_actor_update_request and not ok.is_discovery_request


def test_saving_a_request_without_migration_570_says_so():
    from agents.collection import subscription_store as store
    from agents.collection.subscriptions import SubscriptionError

    class NoColumns:
        def execute(self, *args, **kwargs):
            class Result:
                def scalar(self):
                    return 0
            return Result()

    with pytest.raises(SubscriptionError, match="migration 570"):
        store.create_update_request(
            NoColumns(), title="t", end_date=TODAY, start_date=TODAY, cadence="once",
            update_options={"scope": "general"}, max_usd_per_run=0.5, actor_ids=[ACTOR],
            live=True)


def test_request_writes_outside_a_local_test_database_need_the_bridge_switch(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user@db.example.supabase.co:5432/postgres")
    monkeypatch.delenv("ACTOR_UPDATE_WRITES_ENABLED", raising=False)
    assert au.main(["request-create", "--json", "{}", "--live"]) == 0
    assert "ACTOR_UPDATE_WRITES_ENABLED" in json.loads(capsys.readouterr().out)["error"]
