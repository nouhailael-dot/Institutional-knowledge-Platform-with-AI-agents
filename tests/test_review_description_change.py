"""A better description an update wrote shows beside the current one (25 Nov 2026)."""

from __future__ import annotations

from src.review.postgres_source import PostgresReviewSource


def _item(pipeline, fact_change):
    return {
        "source_run_id": "actor-update:run-1", "created_at": 1.0,
        "agent_metadata": {"review_item_id": "ri-1", "review_kind": "pending_update",
                           "topic_id": None, "pipeline": pipeline, "fact_change": fact_change},
    }


def test_the_description_change_reads_as_two_texts():
    source = PostgresReviewSource.__new__(PostgresReviewSource)
    change = source._change_of(_item(
        {"field_key": "description", "current_text": "A lab.",
         "weakness": "The description is only 2 words.", "state": "pending_update"},
        {"field_key": "description", "current": None,
         "proposed": {"value": {"text": "The Example Lab studies minerals.", "quotes": []},
                      "source_url": "https://example.org/about", "set_by": "agent_collected"}},
    ), topics={})
    assert change["kind"] == "fact" and change["field_key"] == "description"
    assert change["current"]["value"] == "A lab."
    assert change["current"]["set_by"] == "record"
    assert change["proposed"]["value"] == "The Example Lab studies minerals."
    assert change["proposed"]["source_url"] == "https://example.org/about"
    assert change["reason"].startswith("The description is only 2 words.")
    assert change["can_keep_both"] is False


def test_other_pending_updates_are_unchanged():
    source = PostgresReviewSource.__new__(PostgresReviewSource)
    change = source._change_of(_item(
        {"field_key": "funding_signal", "state": "pending_update"},
        {"field_key": "funding_signal", "current": {"value": "x"}, "proposed": {"value": "y"}},
    ), topics={})
    assert change["current"] == {"value": "x"} and change["proposed"] == {"value": "y"}
