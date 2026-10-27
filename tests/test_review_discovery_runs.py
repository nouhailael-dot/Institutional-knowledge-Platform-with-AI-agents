"""Event and people discovery runs in Review: one name per run.

A run's records arrive two ways - review-band search candidates and staged
records in the event or person queue - and each carried its own description,
so the run took whichever came first. Both now read the run itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.review.postgres_source import PostgresReviewSource  # noqa: E402

RUN = "11111111-2222-4333-8444-555555555555"


class DB:
    def execute(self, sql, params):
        self.sql = sql
        return self

    def fetchall(self):
        return [{"run_id": RUN, "mode": "live", "title": "Water reuse events"}]


def _card(table: str) -> dict:
    return {"entity_type": "event", "source_run_id": f"discovery:{RUN}",
            "source_description": f"Open-web event discovery · {RUN}",
            "agent_metadata": {"source_table": table}}


def test_both_kinds_of_record_of_a_run_share_its_name_and_carry_no_summary():
    source = PostgresReviewSource.__new__(PostgresReviewSource)
    candidates = {"a": _card("search_candidate"), "b": _card("event_review_queue"),
                  "c": {"entity_type": "actor", "source_run_id": "discovery:other",
                        "source_description": "Actor run", "agent_metadata": {}}}
    source._attach_discovery_runs(DB(), {"scrape_run": {"run_id", "stats", "mode"}}, candidates)

    names = {candidates[k]["source_description"] for k in ("a", "b")}
    assert names == {f"Discovery request: Water reuse events · live · {RUN}"}
    assert all("run_summary" not in c["agent_metadata"] for c in candidates.values())
    assert candidates["c"]["source_description"] == "Actor run"     # actors untouched


def test_the_review_list_carries_only_what_a_row_shows():
    """7.9 MB per load froze the page (2026-10-24); an opened record loads in full."""
    from backend.app import _list_view

    full = {
        "candidate_id": "c1", "display_name": "Reuse Summit", "status": "pending_review",
        "reviewed_payload": {"name": "Reuse Summit"}, "original_payload": {"name": "x"},
        "field_constraints": {"name": {"max_length": 255}}, "editable_fields": ["name"],
        "rejection_reasons": ["duplicate"], "evidence": [{"url": "https://x"}],
        "agent_metadata": {
            "source_table": "search_candidate", "entity_id": "a1", "changes": [{"id": 1}],
            "hubs": [{"hub_id": str(i)} for i in range(400)], "fact_history": [1] * 50,
            "quality": {"completeness": "complete", "outcome": "qualified", "checks": [1, 2]},
        },
    }
    row = _list_view(full)
    assert set(row) == {"candidate_id", "display_name", "status", "reviewed_payload",
                        "agent_metadata"}
    assert row["agent_metadata"] == {"source_table": "search_candidate", "entity_id": "a1",
                                     "changes": [{"id": 1}],
                                     "quality": {"completeness": "complete",
                                                 "outcome": "qualified"}}
    assert "hubs" in full["agent_metadata"]          # the stored record is not changed


def test_quality_lists_stored_as_python_text_are_read_back_as_lists():
    from src.review.postgres_source import _lift_quality

    payload = {"name": "Donald Siegel", "quality": {
        "completeness": "incomplete",
        "reasons": "('Identified and relevant, but missing: relevant work.',)",
        "missing_mandatory": "()", "conflicts": [], "checks": [{"name": "identity"}]}}
    metadata: dict = {}
    _lift_quality(payload, metadata)
    quality = metadata["quality"]
    assert quality["reasons"] == ["Identified and relevant, but missing: relevant work."]
    assert quality["missing_mandatory"] == [] and quality["checks"] == [{"name": "identity"}]
    assert "quality" not in payload
