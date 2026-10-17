"""Updating one actor: what each box's outcome means, and what is never overwritten."""

from __future__ import annotations

from agents.collection.actor_updates import PRESETS, compare


def _recorded(value):
    return {"collection_state": "found", "fact_value": value, "retrieved_at": "2026-09-01"}


def _read(value):
    return {"collection_state": "found", "value": value, "source_url": "https://x.example/about"}


SILENT = {"collection_state": "not_found", "value": None}


def test_a_box_that_was_empty_and_is_now_stated_is_filled():
    box = compare("funding_signal", None, _read("$2M from DOE in 2026."), None)
    assert box["outcome"] == "filled"
    assert box["after"] == "$2M from DOE in 2026."
    assert box["source_url"] == "https://x.example/about"


def test_a_different_value_is_an_update_and_keeps_what_it_replaces():
    box = compare("funding_signal", _recorded("$1M grant."), _read("$2M grant."), None)
    assert box["outcome"] == "updated"
    assert (box["before"], box["after"]) == ("$1M grant.", "$2M grant.")


def test_the_same_value_is_confirmation_not_a_change():
    box = compare("recent_activity", _recorded({"date": "March 2026", "description": "X"}),
                  _read({"date": "March 2026", "description": "X"}), None)
    assert box["outcome"] == "confirmed"


def test_a_silent_page_never_erases_what_is_recorded():
    box = compare("funding_signal", _recorded("$1M grant."), SILENT, None)
    assert box["outcome"] == "unchanged"
    assert box["before"] == "$1M grant." and box["after"] is None


def test_nothing_recorded_and_nothing_stated_says_so():
    assert compare("funding_signal", None, SILENT, None)["outcome"] == "not stated"


def test_a_refused_answer_is_reported_with_its_reason():
    box = compare("funding_signal", None, SILENT, "the quote given is not on the page it names")
    assert box["outcome"] == "refused"
    assert "quote" in box["reason"]


def test_the_presets_name_real_light_pull_boxes():
    from agents.collection.light_pull_reader import FIELD_CRITERIA

    for fields in PRESETS.values():
        for field in fields:
            assert field in FIELD_CRITERIA, field


def test_a_reworded_fact_is_confirmation_not_an_update():
    """Seen on CPower Energy, 2026-10-17: the same funding fact, reworded."""
    before = _recorded("Paid customers over $1.5 billion from demand response and energy programs.")
    after = _read("CPower has paid customers over $1.5 billion from demand response and energy programs.")
    assert compare("funding_signal", before, after, None)["outcome"] == "confirmed"


def test_a_different_number_is_a_different_fact():
    before = _recorded("Paid customers over $1.5 billion from demand response.")
    after = _read("Paid customers over $2 billion from demand response.")
    assert compare("funding_signal", before, after, None)["outcome"] == "updated"


def test_a_newer_date_is_a_new_activity():
    before = _recorded({"date": "Aug. 12, 2026", "description": "Hosted GridFuture 2026."})
    after = _read({"date": "Oct. 2, 2026", "description": "Opened a Boston office."})
    assert compare("recent_activity", before, after, None)["outcome"] == "updated"


def test_a_refused_answer_keeps_what_is_recorded():
    box = compare("recent_activity", _recorded({"date": "Aug. 12, 2026", "description": "X"}),
                  SILENT, "the quote given is not on the page it names")
    assert box["outcome"] == "unchanged" and box["reason"]
