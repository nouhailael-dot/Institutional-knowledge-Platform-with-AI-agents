"""Delete in the Ecosystem Directory: removable, never wiped (29 Oct 2026).
No database: the session and the decision writer are stand-ins."""
from unittest.mock import MagicMock, patch

import pytest

from agents.review import admission

ACTOR = "11111111-2222-3333-4444-555555555555"


def session_with(status):
    session = MagicMock()
    row = {"name": "Example Water Lab", "status": status} if status else None
    session.execute.return_value.mappings.return_value.first.return_value = row
    return session


def decide(kind, status="verified", **extra):
    decision = {"decision_kind": kind, "entity_type": "actor", "entity_id": ACTOR,
                "reviewer": "Nouhaila El Hail", "reason": "Duplicate of another record", **extra}
    with patch("agents.enrichment.decisions.record_verification_decision") as writer:
        outcome = admission.apply_directory_decision(session_with(status), decision)
    return outcome, writer


def test_removing_appends_a_rejected_decision_with_its_reason():
    outcome, writer = decide("remove_from_directory")
    assert outcome["status"] == "applied" and outcome["current_status"] == "rejected"
    kwargs = writer.call_args.kwargs
    assert kwargs["decision"] == "rejected" and kwargs["decided_by"] == "Nouhaila El Hail"
    assert kwargs["rejection_reason"] == "Duplicate of another record"
    # The Directory's "Removed" view finds removals by this prefix.
    assert kwargs["notes"].startswith("Removed from the Ecosystem Directory")


def test_restoring_appends_a_verified_decision():
    outcome, writer = decide("restore_to_directory", status="rejected", reason="")
    assert outcome["current_status"] == "verified"
    assert writer.call_args.kwargs["decision"] == "verified"
    assert writer.call_args.kwargs["rejection_reason"] is None


def test_an_unchanged_record_is_reported_not_rewritten():
    outcome, writer = decide("remove_from_directory", status="rejected")
    assert outcome["status"] == "unchanged"
    writer.assert_not_called()


@pytest.mark.parametrize("change, message", [
    ({"reason": ""}, "reason is required"),
    ({"entity_id": "not-a-uuid"}, "UUID"),
    ({"entity_type": "event"}, "only organizations"),
    ({"reviewer": ""}, "reviewer"),
    ({"decision_kind": "wipe"}, "unsupported"),
])
def test_refusals(change, message):
    with pytest.raises(admission.AdmissionValidationError, match=message):
        decide("remove_from_directory", **change)


def test_a_missing_organization_is_refused():
    with pytest.raises(admission.AdmissionValidationError, match="not in the directory"):
        decide("remove_from_directory", status=None)
