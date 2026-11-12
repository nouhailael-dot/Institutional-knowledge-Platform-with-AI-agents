"""A map blocked by a charge that was never confirmed can go on (12 Nov 2026).

GHUS feedback, 11 Nov: after "A call's charge is uncertain; further calls are
blocked" the map stayed blocked for good and Send did nothing. With approval,
each unconfirmed charge is counted at its reserved maximum (the budget can only
be overstated), and the map can then be continued or reopened.
"""

from __future__ import annotations

import pytest

from src.map_agent.run_store import MICRO, UNKNOWN_CHARGE, MapStopped, RunStore


@pytest.fixture
def store(tmp_path):
    return RunStore(tmp_path / "runs.sqlite3")


def _blocked(store, how):
    job = store.create(budget=2 * MICRO)
    store.claim(job, "running", "Research", ("draft",))
    call = store.reserve(job, "Discovery", "fake", 400_000, {})
    if how == "no usage":
        store.settle(call, None, {}, {})
    else:  # the server restarted mid-call
        RunStore(store.path).recover()
    return job


@pytest.mark.parametrize("how", ["no usage", "restart"])
def test_an_unconfirmed_charge_is_counted_at_its_maximum_and_the_map_goes_on(store, how):
    job = _blocked(store, how)
    before = store.get(job)
    assert before["cost"]["usage_complete"] is False
    if how == "no usage":
        assert before["error"] == UNKNOWN_CHARGE

    assert store.settle_unknown(job) == pytest.approx(0.4)
    after = store.get(job)
    assert after["cost"]["usage_complete"] is True
    assert after["cost"]["estimated_usd"] == pytest.approx(0.4)  # never less than it may have cost
    assert after["status"] == "cancelled"
    # Stopped, so the person can reopen it (no unfinished plan here) and chat again.
    assert after["cost"]["can_reopen"] is True
    store.reopen(job)
    assert store.get(job)["status"] in ("draft", "awaiting_reply", "done", "ready")


def test_a_map_still_working_is_not_touched(store):
    job = store.create(budget=2 * MICRO)
    store.claim(job, "running", "Research", ("draft",))
    store.reserve(job, "Discovery", "fake", 100, {})
    with pytest.raises(MapStopped):
        store.settle_unknown(job)


def test_the_map_page_offers_the_way_out_and_says_why_research_is_unfinished():
    from pathlib import Path

    page = (Path(__file__).resolve().parents[1] / "frontend" / "index.html").read_text(encoding="utf-8")
    assert '"/api/map/"+id+"/settle-charges"' in page
    assert "Count it at its maximum and go on" in page
    assert "Research is unfinished: some planned searches did not run." in page
