from __future__ import annotations

from dataclasses import replace

import pytest

from agents.common.hub_detection import DetectionActor, HubDetectionConfig, canonical_result_json
from agents.hubs.decisions import apply_hub_proposal_decision
from agents.hubs.detect import DetectionSnapshot, execute_hub_detection


class Result:
    def __init__(self, row=None):
        self.row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self.row


class DecisionSession:
    def __init__(self, row=None):
        self.row = row or {"proposal_kind": "deterministic_cluster", "status": "pending"}
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        if str(statement).lstrip().startswith("SELECT proposal_kind"):
            return Result(self.row)
        return Result()


def decision(session=None, **changes):
    values = {
        "session": session or DecisionSession(),
        "proposed_hub_id": "00000000-0000-0000-0000-000000000001",
        "decision": "approve",
        "decided_by": "GHUS reviewer",
    }
    values.update(changes)
    return apply_hub_proposal_decision(**values)


def test_decision_dry_run_is_default_and_writes_nothing():
    session = DecisionSession()
    plan = decision(session)
    assert plan.resulting_status == "accepted"
    assert len(session.calls) == 1


def test_live_approval_appends_decision_and_marks_proposal_accepted():
    session = DecisionSession()
    plan = decision(session, live=True)
    assert plan.resulting_status == "accepted"
    assert "INSERT INTO proposed_hub_decision" in session.calls[1][0]
    assert "UPDATE proposed_hub SET status" in session.calls[2][0]
    assert all("INSERT INTO hub " not in sql for sql, _ in session.calls)


def test_live_rejection_is_terminal_without_deleting_proposal():
    session = DecisionSession()
    plan = decision(session, decision="reject", live=True)
    assert plan.resulting_status == "rejected"
    assert not any("DELETE" in sql.upper() for sql, _ in session.calls)


def test_canonical_status_contract_records_rename_as_terminal():
    session = DecisionSession({"proposal_kind": "deterministic_cluster", "status": "open"})
    plan = decision(session, decision="rename", final_name="Renamed Hub", live=True)
    assert plan.resulting_status == "renamed"
    assert session.calls[-1][1]["current_status"] == "open"


def test_rename_and_radius_require_complete_values():
    with pytest.raises(ValueError, match="final_name"):
        decision(decision="rename")
    with pytest.raises(ValueError, match="radius"):
        decision(decision="set_radius", final_radius_miles=201)


def test_decision_rejects_legacy_or_terminal_proposal():
    with pytest.raises(ValueError, match="deterministic_cluster"):
        decision(DecisionSession({"proposal_kind": "legacy_review", "status": "pending"}))
    with pytest.raises(ValueError, match="terminal"):
        decision(DecisionSession({"proposal_kind": "deterministic_cluster", "status": "rejected"}))


def test_detector_dry_run_does_not_open_write_transaction(monkeypatch):
    actors = tuple(
        DetectionActor(
            str(index),
            f"Actor {index}",
            "topic",
            "Fusion",
            "Alpha",
            "CA",
            0.0,
            0.0,
            "verified",
            f"category-{index % 5}",
            "type",
        )
        for index in range(10)
    )
    snapshot = DetectionSnapshot(actors, (), (), ())

    class DrySession:
        def begin(self):
            raise AssertionError("dry run must not open a write transaction")

    monkeypatch.setattr("agents.hubs.detect.load_detection_snapshot", lambda session: snapshot)
    execution = execute_hub_detection(DrySession(), HubDetectionConfig())
    assert execution.dry_run is True
    assert len(execution.result.proposals) == 1


def test_comparison_only_changes_trigger_statuses(monkeypatch):
    imported = DetectionActor(
        "a",
        "Actor",
        "topic",
        "Fusion",
        "Alpha",
        "CA",
        0.0,
        0.0,
        "imported",
        "company",
        "startup",
    )
    snapshot = DetectionSnapshot(tuple(replace(imported, actor_id=str(i)) for i in range(10)), (), (), ())

    class DrySession:
        pass

    monkeypatch.setattr("agents.hubs.detect.load_detection_snapshot", lambda session: snapshot)
    config = HubDetectionConfig(minimum_categories=1)
    execution = execute_hub_detection(DrySession(), config)
    assert not execution.result.proposals
    assert len(execution.verified_plus_imported_comparison.proposals) == 1


def test_dry_and_live_modes_compute_identical_complete_result(monkeypatch):
    actors = tuple(
        DetectionActor(
            str(index),
            f"Actor {index}",
            "topic",
            "Fusion",
            "Alpha",
            "CA",
            0.0,
            0.0,
            "verified",
            f"category-{index % 5}",
            "type",
        )
        for index in range(10)
    )
    snapshot = DetectionSnapshot(actors, (), (), ())
    monkeypatch.setattr("agents.hubs.detect.load_detection_snapshot", lambda session: snapshot)
    monkeypatch.setattr(
        "agents.hubs.detect._validate_persistence_compatibility",
        lambda session, config: "pending",
    )
    monkeypatch.setattr("agents.hubs.detect._persist_proposal", lambda *args: None)

    class Transaction:
        is_active = True

        def commit(self):
            self.is_active = False

        def rollback(self):
            self.is_active = False

    class Session:
        def begin(self):
            return Transaction()

        def execute(self, statement, params=None):
            return Result()

    config = HubDetectionConfig()
    dry = execute_hub_detection(Session(), config)
    live = execute_hub_detection(Session(), config, live=True)
    assert canonical_result_json(dry.result) == canonical_result_json(live.result)
