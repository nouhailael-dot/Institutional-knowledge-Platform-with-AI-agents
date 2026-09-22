"""Offline tests for the transactional human-review admission entry point."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import Mock

import pytest

from agents.discovery.promote import PromotionResult
from agents.review import admission


class ScalarResult:
    def __init__(self, value=None):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class Transaction:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class FakeSession:
    def __init__(self, prior=None):
        self.prior = prior
        self.transaction = Transaction()
        self.statements = []

    def begin(self):
        return self.transaction

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append((sql, params or {}))
        if "SELECT outcome FROM review_admission_decision" in sql:
            return ScalarResult(self.prior)
        return ScalarResult()


def decision(entity_type="actor", kind="new", **updates):
    value = {
        "entity_type": entity_type,
        "source_ref": {"table": "search_candidate", "id": "00000000-0000-0000-0000-000000000001"},
        "decision_kind": kind,
        "target_id": "00000000-0000-0000-0000-000000000002" if kind == "same_existing" else None,
        "edited_payload": {"name": "Example"},
        "reviewer": "Reviewer",
        "idempotency_key": f"{entity_type}-{kind}",
    }
    if entity_type == "person":
        value["edited_payload"].update(
            {"affiliation": "Example University", "role": "Professor"}
        )
    value.update(updates)
    return value


@pytest.mark.parametrize("entity_type", ["actor", "event", "person"])
@pytest.mark.parametrize("kind", ["same_existing", "new"])
def test_entity_admission_decisions_delegate_to_promote(monkeypatch, entity_type, kind):
    session = FakeSession()
    promoted = Mock(return_value=PromotionResult(
        action="created" if kind == "new" else "absorbed",
        entity_type=entity_type,
        zone="create" if kind == "new" else "absorb",
        entity_id="canonical-id",
        dry_run=False,
    ))
    monkeypatch.setattr(admission, "_load_source", lambda *_: {
        "source_id": "source", "run_id": "run", "entity_type": entity_type,
        "source_url": "https://example.org", "payload": decision(entity_type)["edited_payload"],
        "extracted_at": "2026-09-22T00:00:00+00:00",
    })
    monkeypatch.setattr(admission, "_promotion_route", lambda *_: object())
    monkeypatch.setattr(admission, "promote", promoted)
    monkeypatch.setattr(admission, "_insert_proposed_hub", lambda *_: None)
    statuses = []
    monkeypatch.setattr(admission, "_update_source_status", lambda *args: statuses.append(args[3]))

    outcome = admission.apply_review_decision(session, decision(entity_type, kind))

    assert outcome["canonical_entity_id"] == "canonical-id"
    assert statuses == ["approved"]
    assert promoted.call_args.kwargs["manage_transaction"] is False
    assert session.transaction.committed is True


@pytest.mark.parametrize("kind,status", [("reject", "rejected"), ("defer", "deferred")])
def test_reject_and_defer_drain_source_without_canonical_write(monkeypatch, kind, status):
    session = FakeSession()
    value = decision("event", kind)
    if kind == "reject":
        value["rejection_reason"] = "Insufficient evidence on the page"
    monkeypatch.setattr(admission, "_load_source", lambda *_: {
        "entity_type": "event", "payload": {"name": "Example"},
    })
    promoted = Mock()
    monkeypatch.setattr(admission, "promote", promoted)
    statuses = []
    monkeypatch.setattr(admission, "_update_source_status", lambda *args: statuses.append(args[3]))

    outcome = admission.apply_review_decision(session, value)

    assert outcome["status"] == status
    assert statuses == [status]
    promoted.assert_not_called()


def test_idempotency_returns_stored_outcome_without_second_write():
    session = FakeSession(prior={"status": "approved", "canonical_entity_id": "held"})
    outcome = admission.apply_review_decision(session, decision())
    assert outcome == {
        "status": "approved", "canonical_entity_id": "held", "idempotent_replay": True,
    }
    assert session.transaction.rolled_back is True
    assert len(session.statements) == 1


def test_model_length_violation_writes_nothing():
    session = FakeSession()
    with pytest.raises(admission.AdmissionValidationError, match="name exceeds 255"):
        admission.apply_review_decision(
            session, decision(edited_payload={"name": "x" * 256})
        )
    assert session.statements == []


def test_other_rejection_requires_free_text():
    with pytest.raises(admission.AdmissionValidationError, match="free text"):
        admission._normalise_decision(
            decision("actor", "reject", rejection_reason="Other")
        )


def test_proposed_hub_is_never_a_canonical_hub_writer():
    source = admission.Path(admission.__file__).read_text(encoding="utf-8")
    assert "INSERT INTO proposed_hub" in source
    assert "INSERT INTO hub (" not in source
