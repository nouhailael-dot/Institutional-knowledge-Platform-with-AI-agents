from __future__ import annotations

import uuid
from argparse import Namespace
from datetime import UTC, datetime

import pytest

from agents.collection.deep_pull import (
    DEEP_FIELDS,
    CollectedValue,
    DeepPullRequest,
    append_deep_pull,
    append_specific_ask,
    map_linked_subentities,
    validate_deep_request,
)
from agents.enrichment.run import run_enrichment


def _request(category="company", fields=("relevant_products",)):
    return DeepPullRequest(str(uuid.uuid4()), str(uuid.uuid4()), category, fields,
                           "ghus-reviewer", str(uuid.uuid4()))


def _value(field="relevant_products"):
    return CollectedValue(field, "Topic-specific evidence", "found",
                          "https://example.org/evidence", "newly_found",
                          datetime.now(UTC), "high")


class Result:
    def __init__(self, decision): self.decision = decision
    def scalar_one(self): return True
    def scalar_one_or_none(self): return self.decision


class Session:
    def __init__(self, decision): self.decision = decision; self.statements = []
    def execute(self, statement, params=None):
        self.statements.append((str(statement), params)); return Result(self.decision)


def test_all_12_categories_have_bounded_deep_schemas():
    assert len(DEEP_FIELDS) == 12
    assert all(fields and len(fields) == len(set(fields)) for fields in DEEP_FIELDS.values())


def test_deep_pull_requires_selected_category_fields_and_requester():
    validate_deep_request(_request())
    with pytest.raises(ValueError, match="non-exhaustive"):
        validate_deep_request(_request(fields=DEEP_FIELDS["company"]))
    with pytest.raises(ValueError, match="outside category"):
        validate_deep_request(_request(fields=("full_portfolio",)))
    with pytest.raises(ValueError, match="requested_by"):
        validate_deep_request(DeepPullRequest(str(uuid.uuid4()), str(uuid.uuid4()),
                                              "company", ("relevant_products",), "", str(uuid.uuid4())))


@pytest.mark.parametrize("decision", [None, "parked", "imported", "rejected"])
def test_deep_pull_refuses_every_non_verified_latest_decision(decision):
    with pytest.raises(PermissionError, match="verified"):
        append_deep_pull(Session(decision), _request(), {"relevant_products": _value()})


def test_verified_deep_pull_uses_fact_writer_and_remains_dry_run_by_default():
    session = Session("verified")
    assert append_deep_pull(session, _request(), {"relevant_products": _value()}) == ["would_append"]
    assert len(session.statements) == 2
    assert "actor_verification_event" in session.statements[1][0]


def test_specific_ask_has_no_implicit_trigger_and_requires_auditable_user_request():
    with pytest.raises(ValueError, match="explicit requester"):
        append_specific_ask(Session("verified"), actor_id=str(uuid.uuid4()),
                            topic_id=str(uuid.uuid4()), requested_by="", request_text="",
                            request_id=str(uuid.uuid4()), values=[_value()])
    result = append_specific_ask(
        Session("verified"), actor_id=str(uuid.uuid4()), topic_id=str(uuid.uuid4()),
        requested_by="ghus-user", request_text="Provide the selected product evidence",
        request_id=str(uuid.uuid4()), values=[_value()],
    )
    assert result == ["would_append"]


def test_linked_subentities_are_capped_and_forced_through_parent_mapping():
    seen = []
    result = map_linked_subentities(
        [{"name": "Topic Lab"}], parent_actor_id=str(uuid.uuid4()),
        mapper=lambda payload: seen.append(payload) or "mapped",
    )
    assert result == ["mapped"]
    assert seen[0]["parent_connection"]["relationship_type"] == "unit_of"
    with pytest.raises(ValueError, match="cap"):
        map_linked_subentities([{"name": str(i)} for i in range(6)],
                               parent_actor_id=str(uuid.uuid4()), mapper=lambda value: value)


def test_legacy_live_actor_enrichment_cannot_bypass_verified_topic_gate():
    with pytest.raises(RuntimeError, match="verified, topic-scoped"):
        run_enrichment(Namespace(entity="actor", live=True))
