"""Offline reconciliation guards; SQL execution still needs isolated PostgreSQL."""
from unittest.mock import Mock

import pytest

from agents.enrichment import decisions
from agents.review import admission


class Result:
    def __init__(self, value=None, rowcount=1):
        self.value, self.rowcount = value, rowcount

    def mappings(self):
        return self

    def first(self):
        return self.value

    def scalar(self):
        return self.value


class Session:
    def __init__(self):
        self.fact = {"actor_id": "actor", "topic_id": "topic", "fact_key": "location",
                     "source_id": "source", "fact_value": {"city": "Boston", "state_code": "MA"}}
        self.pointer = "old"
        self.duplicate = None
        self.rowcount = 1
        self.statements = []
        self.transaction = Mock()

    def begin(self):
        return self.transaction

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append((sql, params))
        if "FROM actor_fact WHERE" in sql:
            return Result(self.fact)
        if "FROM actor_fact_current_pointer" in sql:
            return Result(self.pointer)
        if "SELECT actor_id FROM actor" in sql:
            return Result(("actor",))
        if "SELECT 1 FROM actor_location" in sql:
            return Result(self.duplicate)
        return Result(rowcount=self.rowcount)


@pytest.fixture
def context(monkeypatch):
    session = Session()
    item = {"status": "pending", "entity_id": "actor"}
    payload = {"new_fact_id": "new", "current_fact_id": "old", "field_key": "location"}
    monkeypatch.setattr(decisions, "_pending_review_item", lambda *a: (item, payload))
    monkeypatch.setattr(decisions, "_has_column", lambda *a: True)
    resolution, close = Mock(), Mock()
    monkeypatch.setattr(decisions, "_append_fact_resolution", resolution)
    monkeypatch.setattr(decisions, "_close_review_item", close)
    return session, item, payload, resolution, close


def decide(session, **kwargs):
    return decisions.record_fact_review_decision(
        session, review_item_id="review", decided_by="Reviewer", accept=False,
        keep_both=True, **kwargs)


def test_keep_both_preserves_pointer_and_carries_source_in_existing_writer(context):
    session, _, _, resolution, close = context
    result = decide(session, live=True)
    assert result["action"] == "decided"
    inserted = [(sql, args) for sql, args in session.statements if sql.startswith("INSERT")]
    assert len(inserted) == 1 and "actor_location" in inserted[0][0]
    assert inserted[0][1]["source"] == "source"
    assert not any("UPDATE actor_fact_current_pointer" in sql for sql, _ in session.statements)
    assert any("FROM actor WHERE" in sql and "FOR UPDATE" in sql for sql, _ in session.statements)
    resolution.assert_called_once()
    close.assert_called_once()


def test_duplicate_location_is_not_inserted_again(context):
    session, *_ = context
    session.duplicate = (1,)
    assert decide(session, live=True)["location_already_listed"] is True
    assert not any(sql.startswith("INSERT") for sql, _ in session.statements)


def test_dry_run_checks_duplicates_without_writing(context):
    session, _, _, resolution, close = context
    assert decide(session)["action"] == "would_decide"
    assert any("FROM actor_location" in sql for sql, _ in session.statements)
    assert all(sql.startswith("SELECT") for sql, _ in session.statements)
    resolution.assert_not_called()
    close.assert_not_called()


@pytest.mark.parametrize("invalid", ["stale", "wrong_actor", "no_source", "wrong_field", "unplaceable"])
def test_invalid_location_decisions_never_write(context, invalid):
    session, _, payload, resolution, close = context
    if invalid == "stale":
        session.pointer = "newer"
    elif invalid == "wrong_actor":
        session.fact["actor_id"] = "other"
    elif invalid == "no_source":
        session.fact["source_id"] = None
    elif invalid == "wrong_field":
        session.fact["fact_key"] = payload["field_key"] = "funding_signal"
    else:
        session.fact["fact_value"] = {"city": "Unknown", "country": "FR"}
    with pytest.raises(ValueError):
        decide(session, live=True)
    assert all(sql.startswith("SELECT") for sql, _ in session.statements)
    resolution.assert_not_called()
    close.assert_not_called()


def test_already_resolved_item_is_not_rewritten(context):
    session, item, _, resolution, close = context
    item["status"] = "approved"
    assert decide(session, live=True)["action"] == "already_resolved"
    assert session.statements == []
    close.assert_not_called()


@pytest.mark.parametrize("failure", [None, "missed_write", "provenance"])
def test_admission_owns_location_and_review_transaction(context, failure):
    session, _, _, resolution, close = context
    if failure == "missed_write":
        session.rowcount = 0
    elif failure == "provenance":
        resolution.side_effect = ValueError("resolution audit failed")
    decision = {"decision_kind": "resolve_fact", "keep_both": True, "accept": False,
                "review_item_id": "review", "reviewer": "Reviewer", "idempotency_key": "key"}
    if failure:
        with pytest.raises(ValueError):
            admission.apply_review_item_decision(session, decision)
        session.transaction.rollback.assert_called_once()
        session.transaction.commit.assert_not_called()
        close.assert_not_called()
    else:
        assert admission.apply_review_item_decision(session, decision)["decision"] == "keep_both"
        session.transaction.commit.assert_called_once()
        session.transaction.rollback.assert_not_called()
