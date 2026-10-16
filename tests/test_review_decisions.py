"""WS3: Verify, Park and Reject, and the audit row each one leaves behind.

The brief maps the three Review actions onto the states that already exist
rather than inventing new ones:

    Verify  -> approved              (authorises the topic-scoped Deep Pull)
    Park    -> stays pending_review  (the record waits, nothing is written)
    Reject  -> rejected_by_reviewer  (kept, with a required reason)

What these tests are really checking is that a decision can always be
reconstructed afterwards: who made it, when, what the record looked like before
and after, and why. A decision that cannot be audited is not a decision, it is
a change.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.review.store import (  # noqa: E402
    REJECTION_REASONS,
    STATUSES,
    ReviewConflict,
    ReviewNotConfigured,
    ReviewStore,
    ReviewValidationError,
)


@pytest.fixture
def store(tmp_path):
    return ReviewStore(tmp_path / "review.sqlite3", enable_test_canonical=True)


@pytest.fixture
def unwritable(tmp_path):
    """A store with no canonical writer, which is how production starts."""

    return ReviewStore(tmp_path / "closed.sqlite3")


def _candidate(store: ReviewStore, candidate_id: str = "a") -> dict:
    store.sync_external_candidates([{
        "source_key": f"postgres:search_candidate:{candidate_id}",
        "source_run_id": "discovery:run-1",
        "source_index": candidate_id,
        "source_description": "Open-web actor discovery",
        "entity_type": "actor",
        "payload": {
            "name": "Decision Test Lab",
            "website": "https://decision.example.org",
            "actor_category": "research_center",
            "category_type": "independent_institute",
            "description": "An independent institute.",
        },
        "evidence": [{"url": "https://decision.example.org", "supports": "Self-description"}],
        "agent_metadata": {
            "source_table": "search_candidate", "source_candidate_id": candidate_id,
        },
        "duplicate_state": "new",
        "created_at": 1_800_000_000.0,
    }])
    return next(
        row for row in store.list(status="all")["candidates"]
        if row["source_index"] == candidate_id
    )


def _decisions(store: ReviewStore) -> list[dict]:
    with store.connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM review_decision")]


# ---------------------------------------------------------------- the states

def test_no_new_status_was_invented():
    """Verify / Park / Reject map onto the three states that already exist."""

    assert STATUSES == ("pending_review", "approved", "rejected_by_reviewer")


# ------------------------------------------------------------------- Verify

def test_verify_writes_one_auditable_row_with_who_when_and_before_and_after(store):
    candidate = _candidate(store)
    before = dict(candidate["reviewed_payload"])
    edited = {**before, "description": "An independent institute, reviewed."}

    at = time.time()
    result = store.approve(
        candidate["candidate_id"], reviewer="A GHUS Reviewer",
        idempotency_key="verify-1", confirmed=True,
        notes="Checked the self-description.", edited_payload=edited,
    )
    assert result["status"] == "approved"

    rows = _decisions(store)
    assert len(rows) == 1
    row = rows[0]
    assert row["decision"] == "approved"
    assert row["reviewer"] == "A GHUS Reviewer"
    assert row["notes"] == "Checked the self-description."
    assert row["entity_type"] == "actor"
    assert row["source_run_id"] == candidate["source_run_id"]
    # Within a few seconds of now, and never a placeholder.
    assert at - 5 <= row["decided_at"] <= time.time() + 5
    # Before and after are both kept, so the edit is reconstructable.
    assert json.loads(row["original_payload"])["description"] == before["description"]
    assert json.loads(row["final_payload"])["description"] == edited["description"]
    assert json.loads(row["evidence"])


def test_verify_requires_an_explicit_confirmation_and_a_named_reviewer(store):
    candidate = _candidate(store)
    with pytest.raises(ReviewValidationError, match="confirmation"):
        store.approve(candidate["candidate_id"], reviewer="R",
                      idempotency_key="k", confirmed=False)
    for blank in ("", "   "):
        with pytest.raises(ReviewValidationError):
            store.approve(candidate["candidate_id"], reviewer=blank,
                          idempotency_key="k2", confirmed=True)
    # Nothing was written by a refused attempt.
    assert _decisions(store) == []
    assert store.get(candidate["candidate_id"])["status"] == "pending_review"


# --------------------------------------------------------------------- Park

def test_park_leaves_the_record_pending_and_writes_no_decision(store):
    """Park is the absence of a decision, so it must leave no decision behind."""

    candidate = _candidate(store)
    plan = store.admission_request(
        candidate["candidate_id"], decision_kind="defer", reviewer="A GHUS Reviewer",
        idempotency_key="park-1", confirmed=True, notes="Waiting on the annual report.",
    )
    assert plan["decision_kind"] == "defer"
    assert plan["notes"] == "Waiting on the annual report."
    assert store.get(candidate["candidate_id"])["status"] == "pending_review"
    assert _decisions(store) == []


# ------------------------------------------------------------------- Reject

def test_reject_keeps_the_record_and_records_the_reason(store):
    candidate = _candidate(store)
    result = store.reject(
        candidate["candidate_id"], reviewer="A GHUS Reviewer",
        rejection_reason="Outside target geography",
        idempotency_key="reject-1", confirmed=True, notes="Not in the mapped states.",
    )
    assert result["status"] == "rejected_by_reviewer"

    # The record itself is still there. Rejection is a verdict, not a delete.
    assert store.get(candidate["candidate_id"])["display_name"] == "Decision Test Lab"
    rows = _decisions(store)
    assert len(rows) == 1 and rows[0]["decision"] == "rejected_by_reviewer"
    assert rows[0]["reviewer"] == "A GHUS Reviewer"
    stored = store.rejection(candidate["candidate_id"])
    assert stored["rejection_reason"] == "Outside target geography"


def test_reject_without_a_reason_is_blocked(store):
    candidate = _candidate(store)
    for reason in (None, "", "   "):
        with pytest.raises(ReviewValidationError):
            store.reject(candidate["candidate_id"], reviewer="R", rejection_reason=reason,
                         idempotency_key=f"r-{reason!r}", confirmed=True)
    assert store.get(candidate["candidate_id"])["status"] == "pending_review"


def test_the_rejection_reason_comes_from_the_fixed_list(store):
    candidate = _candidate(store)
    assert "Other" in REJECTION_REASONS
    with pytest.raises(ReviewValidationError, match="fixed rejection reasons"):
        store.admission_request(
            candidate["candidate_id"], decision_kind="reject", reviewer="R",
            idempotency_key="bad-reason", confirmed=True,
            rejection_reason="Because I said so",
        )
    # "Other" is allowed, but only with an explanation.
    with pytest.raises(ReviewValidationError, match="Other"):
        store.admission_request(
            candidate["candidate_id"], decision_kind="reject", reviewer="R",
            idempotency_key="other-blank", confirmed=True,
            rejection_reason="Other", rejection_reason_other="   ",
        )


# ------------------------------------------------------- safety and idempotency

def test_a_decision_cannot_be_taken_twice(store):
    candidate = _candidate(store)
    store.approve(candidate["candidate_id"], reviewer="R",
                  idempotency_key="once", confirmed=True)
    # The same key replays the same answer rather than deciding again.
    again = store.approve(candidate["candidate_id"], reviewer="R",
                          idempotency_key="once", confirmed=True)
    assert again["status"] == "approved"
    assert len(_decisions(store)) == 1
    # A different key on an already-decided record is a conflict, not a second
    # decision.
    with pytest.raises(ReviewConflict, match="already been decided"):
        store.reject(candidate["candidate_id"], reviewer="R",
                     rejection_reason="Duplicate of an existing record",
                     idempotency_key="twice", confirmed=True)
    assert len(_decisions(store)) == 1


def test_verify_fails_closed_without_a_canonical_writer(unwritable):
    candidate = _candidate(unwritable)
    assert unwritable.admission_configured is False
    with pytest.raises(ReviewNotConfigured):
        unwritable.approve(candidate["candidate_id"], reviewer="R",
                           idempotency_key="k", confirmed=True)
    assert unwritable.get(candidate["candidate_id"])["status"] == "pending_review"
    assert _decisions(unwritable) == []


def test_reject_is_local_by_design_and_the_UI_is_what_disables_it(unwritable):
    """A difference between the store and the brief, asserted rather than hidden.

    The brief (WS3) says to disable all three actions when the canonical writer
    is unavailable. The **screen** does: Verify, Park and Reject are all
    disabled behind `writerDown`, which is what a reviewer meets.

    The **store** lets a rejection through, deliberately: a rejection never
    reaches canonical tables at all, so there is no writer for it to need.
    `test_rejection_is_atomic_durable_and_never_reaches_canonical_tables` in
    tests/test_review.py pins that design.

    The consequence is worth naming: a rejection taken while the writer is down
    is recorded locally only, so the canonical record does not learn of it and a
    later sighting of the same organisation would not be suppressed. The UI
    prevents that from arising. If the API is ever called directly, it would.
    Raised as an open question rather than changed here, because changing it
    would alter a deliberate, separately tested design.
    """

    candidate = _candidate(unwritable)
    assert unwritable.admission_configured is False
    decided = unwritable.reject(
        candidate["candidate_id"], reviewer="R",
        rejection_reason="Outside target geography",
        idempotency_key="k2", confirmed=True,
    )
    assert decided["status"] == "rejected_by_reviewer"
    # It stayed local: nothing was promoted anywhere.
    assert unwritable.canonical_rows("actor") == []


def test_a_decided_record_can_no_longer_be_edited(store):
    """The payload a decision was made on stays the payload it was made on."""

    candidate = _candidate(store)
    store.approve(candidate["candidate_id"], reviewer="R",
                  idempotency_key="final", confirmed=True)
    with pytest.raises(ReviewConflict, match="Only pending candidates"):
        store.update(candidate["candidate_id"], {"name": "Renamed After The Fact"})


def test_no_decision_path_deletes_anything(store):
    """Decision D15 and guardrail 4: there is no delete, in any path."""

    source = Path("src/review/store.py").read_text(encoding="utf-8")
    for statement in ("DELETE FROM review_candidate", "DROP TABLE", "TRUNCATE"):
        assert statement not in source, f"the review store must never {statement}"

    candidate = _candidate(store)
    store.reject(candidate["candidate_id"], reviewer="R",
                 rejection_reason="Not relevant to GHUS sectors",
                 idempotency_key="keep", confirmed=True)
    # Still listed, still readable, still carrying its evidence.
    listed = store.list(status="all")["candidates"]
    assert any(row["candidate_id"] == candidate["candidate_id"] for row in listed)
    assert store.get(candidate["candidate_id"])["evidence"]


# ------------------------------- the 120-second sync must not undo a decision

def _resync(store: ReviewStore, candidate_id: str = "a", **changes) -> None:
    """Re-deliver the same candidate, as the periodic PostgreSQL sync does."""

    payload = {
        "name": "Decision Test Lab",
        "website": "https://decision.example.org",
        "actor_category": "research_center",
        "category_type": "independent_institute",
        "description": "An independent institute.",
    }
    payload.update(changes.pop("payload", {}))
    store.sync_external_candidates([{
        "source_key": f"postgres:search_candidate:{candidate_id}",
        "source_run_id": "discovery:run-2",
        "source_index": candidate_id,
        "entity_type": "actor",
        "payload": payload,
        "evidence": [{"url": "https://decision.example.org", "supports": "Found again"}],
        "agent_metadata": {"source_table": "search_candidate"},
        "duplicate_state": changes.pop("duplicate_state", "new"),
    }])


def test_a_rejected_candidate_is_not_resurrected_by_the_next_sync(store):
    """The agent finds it again next week. The reviewer's no has to survive that.

    Review mirrors PostgreSQL every 120 seconds. If a re-delivery could move a
    decided row back to pending_review, a rejection would silently decay into
    "not yet looked at" and the item would reappear in the queue.
    """

    candidate = _candidate(store)
    store.reject(candidate["candidate_id"], reviewer="Ismail",
                 rejection_reason=REJECTION_REASONS[0], idempotency_key="idem-reject",
                 confirmed=True)

    _resync(store)
    assert store.get(candidate["candidate_id"])["status"] == "rejected_by_reviewer"

    # The realistic case: it comes back changed, and newly flagged a duplicate.
    _resync(store, payload={"name": "Decision Test Lab (renamed)"},
            duplicate_state="possible_duplicate")
    after = store.get(candidate["candidate_id"])
    assert after["status"] == "rejected_by_reviewer"
    # The decided row is left entirely alone — not even its duplicate flag moves,
    # because the sync's UPDATE is scoped to WHERE status='pending_review'.
    assert after["duplicate_state"] == "new"

    assert not store.list(status="pending_review")["candidates"]
    # And exactly one decision exists: the re-sync created no second history.
    assert len(_decisions(store)) == 1


def test_an_approved_candidate_is_not_reopened_by_the_next_sync(store):
    """Same property on the other side. A Verify must not decay either."""

    candidate = _candidate(store, "b")
    store.approve(candidate["candidate_id"], reviewer="Ismail",
                  idempotency_key="idem-approve", confirmed=True)

    _resync(store, "b", payload={"name": "Decision Test Lab (upstream edit)"})
    after = store.get(candidate["candidate_id"])
    assert after["status"] == "approved"
    # The reviewed values are what was verified, not what the agent later sent.
    assert after["reviewed_payload"]["name"] == "Decision Test Lab"
    assert not store.list(status="pending_review")["candidates"]


# ------------------------------------------- the store is durable state, not a cache

def test_a_restart_does_not_resurrect_a_rejected_candidate(tmp_path):
    """Reopen the same file and the reviewer's no is still there.

    The 120-second sync test above covers a running process. This covers the
    other half: the process dies, a new one opens the same store, PostgreSQL
    re-delivers the candidate, and it must not reappear in the queue.
    """

    path = tmp_path / "durable.sqlite3"
    first = ReviewStore(path, enable_test_canonical=True)
    candidate = _candidate(first)
    first.reject(candidate["candidate_id"], reviewer="Ismail",
                 rejection_reason=REJECTION_REASONS[0],
                 idempotency_key="idem-restart", confirmed=True)

    # A new process, same file, and the agent finds it again.
    second = ReviewStore(path, enable_test_canonical=True)
    _resync(second)
    assert second.get(candidate["candidate_id"])["status"] == "rejected_by_reviewer"
    assert not second.list(status="pending_review")["candidates"]
    assert len(_decisions(second)) == 1


def test_losing_the_store_file_is_what_resurrection_actually_looks_like(tmp_path):
    """The failure this guards against, written down so it is not theoretical.

    A redeploy onto fresh storage is indistinguishable from a brand-new store.
    PostgreSQL still serves the candidate, nothing declines to insert it, and
    the rejection is gone. This is why REVIEW_STORE_DB is durable state.
    """

    path = tmp_path / "lost.sqlite3"
    first = ReviewStore(path, enable_test_canonical=True)
    candidate = _candidate(first)
    first.reject(candidate["candidate_id"], reviewer="Ismail",
                 rejection_reason=REJECTION_REASONS[0],
                 idempotency_key="idem-lost", confirmed=True)

    path.unlink()                      # the redeploy
    rebuilt = ReviewStore(path, enable_test_canonical=True)
    _resync(rebuilt)
    assert rebuilt.list(status="pending_review")["candidates"], (
        "losing the store resurrects the candidate - that is the risk being documented"
    )


def test_the_store_says_so_when_its_persistence_is_not_durable(tmp_path, monkeypatch):
    monkeypatch.delenv("REVIEW_STORE_DB", raising=False)
    default = ReviewStore(tmp_path / "unset.sqlite3")
    warnings = default.persistence_warnings()
    assert any("REVIEW_STORE_DB is not set" in w for w in warnings)
    assert any("returns to the queue" in w for w in warnings)

    # A path under the system temporary directory is never durable.
    monkeypatch.setenv("REVIEW_STORE_DB", str(tmp_path / "temp.sqlite3"))
    temporary = ReviewStore(tmp_path / "temp.sqlite3")
    assert any("not durable" in w for w in temporary.persistence_warnings())


def test_the_warning_counts_the_decisions_that_would_be_lost(tmp_path, monkeypatch):
    monkeypatch.delenv("REVIEW_STORE_DB", raising=False)
    store = ReviewStore(tmp_path / "counted.sqlite3", enable_test_canonical=True)
    assert not any("decision(s) are already recorded" in w
                   for w in store.persistence_warnings())

    candidate = _candidate(store)
    store.reject(candidate["candidate_id"], reviewer="Ismail",
                 rejection_reason=REJECTION_REASONS[0],
                 idempotency_key="idem-count", confirmed=True)
    assert any("1 review decision(s) are already recorded" in w
               for w in store.persistence_warnings())


# ----------------------------------- enrichment that lands after the first sync

def test_a_later_sync_brings_in_enrichment_but_never_overwrites_an_edit(store):
    """Light Pull runs after a candidate first appears, and the screen must show it.

    A discovered actor reaches Review before enrichment has filled in its
    location, sector and the rest. Those arrive on a later sync. Freezing the
    captured payload at first sight left the screen showing empty fields
    forever while the facts beside them updated - which is exactly how State
    and Sector came to look missing on actors that had both.
    """

    candidate = _candidate(store)
    before = store.get(candidate["candidate_id"])
    assert not before["reviewed_payload"].get("location_city")

    _resync(store, payload={"location_city": "New York", "state": "NY"})
    after = store.get(candidate["candidate_id"])
    assert after["reviewed_payload"]["location_city"] == "New York"
    assert after["original_payload"]["state"] == "NY"

    # Now a reviewer edits it. From here the enrichment must not win.
    store.update(candidate["candidate_id"], {"location_city": "Brooklyn"})
    _resync(store, payload={"location_city": "Albany", "state": "NY"})
    edited = store.get(candidate["candidate_id"])
    assert edited["reviewed_payload"]["location_city"] == "Brooklyn", (
        "a later sync must never overwrite what a reviewer typed"
    )


def test_a_decided_candidate_is_never_refreshed(store):
    """The payload of a decided record is evidence; it does not move."""

    candidate = _candidate(store, "refresh")
    store.reject(candidate["candidate_id"], reviewer="Ismail",
                 rejection_reason=REJECTION_REASONS[0],
                 idempotency_key="idem-refresh", confirmed=True)
    _resync(store, "refresh", payload={"location_city": "Somewhere Else"})
    after = store.get(candidate["candidate_id"])
    assert after["reviewed_payload"].get("location_city") != "Somewhere Else"
    assert after["status"] == "rejected_by_reviewer"
