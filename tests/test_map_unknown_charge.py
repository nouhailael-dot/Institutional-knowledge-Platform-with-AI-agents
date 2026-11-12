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


def test_an_api_error_reply_is_not_an_uncertain_charge():
    """A rate-limit or overloaded reply is a refusal: not charged, so the map is
    not locked. A timeout (no reply) stays uncertain."""
    from types import SimpleNamespace

    from src.map_agent.costs import refused_status

    assert refused_status(SimpleNamespace(status_code=429, response=object())) == 429
    assert refused_status(SimpleNamespace(status_code=529, response=object())) == 529
    assert refused_status(TimeoutError("read timed out")) is None
    assert refused_status(SimpleNamespace(status_code=None, response=None)) is None


def test_a_busy_or_rate_limited_answer_is_retried_and_a_timeout_never_is():
    """12 Nov 2026: a map and a Monitor request share the team's API limits; the
    map now waits and retries a free refusal instead of failing."""
    from types import SimpleNamespace

    from src.map_agent.costs import with_refusal_retries

    busy = type("Busy", (Exception,), {})
    def refusal(status, retry_after=None):
        exc = busy("busy")
        exc.status_code = status
        exc.response = SimpleNamespace(headers={"retry-after": retry_after} if retry_after else {})
        return exc

    waits, answers = [], [refusal(429, "3"), refusal(529), "done"]
    def call():
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer
    assert with_refusal_retries(call, sleep=waits.append) == "done"
    assert waits == [3.0, 5]          # the service's own wait first, then the schedule

    timeouts = []
    def timeout():
        timeouts.append(1)
        raise TimeoutError("read timed out")
    with pytest.raises(TimeoutError):
        with_refusal_retries(timeout, sleep=lambda s: None)
    assert timeouts == [1]            # never retried: it may have been charged

    always_busy = lambda: (_ for _ in ()).throw(refusal(429))
    with pytest.raises(busy):
        with_refusal_retries(always_busy, sleep=lambda s: None)
