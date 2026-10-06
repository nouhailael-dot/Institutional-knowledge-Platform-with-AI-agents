"""Phase 8 relationship contract and writer tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from agents.common.relationships import (
    FAMILY_RELATIONSHIP_TYPES,
    RELATIONSHIP_ENDPOINTS,
    EntityEdgeRequest,
    actor_relationship_requests,
    network_location_requests,
    validate_entity_edge,
)
from agents.enrichment.decisions import append_entity_edge

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    "unit_of", "operated_by", "affiliated_with", "member_of", "portfolio_of",
    "spinout_of", "funded_by", "collaborates_with", "organizes",
    "participates_in", "connected_to_um6p_ocp",
}


def _request(**changes):
    values = {
        "subject_type": "actor",
        "subject_id": "00000000-0000-0000-0000-000000000001",
        "relationship_type": "unit_of",
        "object_type": "actor",
        "object_id": "00000000-0000-0000-0000-000000000002",
        "source_id": "00000000-0000-0000-0000-000000000003",
    }
    values.update(changes)
    return EntityEdgeRequest(**values)


def test_exact_relationship_vocabulary_and_family_boundary():
    assert set(RELATIONSHIP_ENDPOINTS) == EXPECTED
    assert FAMILY_RELATIONSHIP_TYPES == {"unit_of", "operated_by"}
    assert "connected_to_strategic_entity" not in RELATIONSHIP_ENDPOINTS


@pytest.mark.parametrize(("relationship", "subject", "object_type"), [
    ("unit_of", "actor", "actor"),
    ("operated_by", "actor", "actor"),
    ("affiliated_with", "person", "actor"),
    ("member_of", "actor", "actor"),
    ("portfolio_of", "actor", "actor"),
    ("spinout_of", "actor", "actor"),
    ("funded_by", "actor", "actor"),
    ("collaborates_with", "actor", "actor"),
    ("organizes", "actor", "event"),
    ("participates_in", "person", "event"),
    ("connected_to_um6p_ocp", "event", "strategic_entity"),
])
def test_valid_entity_pairs(relationship, subject, object_type):
    assert validate_entity_edge(_request(
        relationship_type=relationship, subject_type=subject, object_type=object_type
    )).relationship_type == relationship


@pytest.mark.parametrize(("relationship", "subject", "object_type"), [
    ("unit_of", "person", "actor"),
    ("affiliated_with", "actor", "actor"),
    ("organizes", "event", "actor"),
    ("connected_to_um6p_ocp", "actor", "actor"),
])
def test_invalid_cross_entity_pairs_are_rejected(relationship, subject, object_type):
    with pytest.raises(ValueError, match="does not allow"):
        validate_entity_edge(_request(
            relationship_type=relationship, subject_type=subject, object_type=object_type
        ))


def test_standalone_actor_is_complete_and_no_parent_is_invented():
    assert actor_relationship_requests(
        actor_id=_request().subject_id,
        payload={"name": "Independent actor", "location_city": "Boston"},
        source_id=_request().source_id,
        topic_id=None,
    ) == ()


def test_parent_requires_explicit_structural_type_and_source_identity():
    requests = actor_relationship_requests(
        actor_id=_request().subject_id,
        payload={"parent_connection": {
            "relationship_type": "operated_by", "actor_id": _request().object_id,
        }},
        source_id=_request().source_id,
        topic_id=None,
    )
    assert requests == (_request(relationship_type="operated_by"),)
    with pytest.raises(ValueError, match="unit_of or operated_by"):
        actor_relationship_requests(
            actor_id=_request().subject_id,
            payload={"parent_connection": {
                "relationship_type": "portfolio_of", "actor_id": _request().object_id,
            }},
            source_id=_request().source_id,
            topic_id=None,
        )


def test_network_locations_are_children_not_copies_of_network_reach():
    requests = network_location_requests(
        parent_actor_id=_request().object_id,
        location_actor_ids=[_request().subject_id],
        source_id=_request().source_id,
    )
    assert requests == (_request(),)
    assert not hasattr(requests[0], "location")


def test_writer_is_dry_run_by_default():
    class RefuseSession:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("dry-run must not execute SQL")

    assert append_entity_edge(RefuseSession(), _request()) == "would_append"


def test_superseding_proposal_preserves_frozen_250_and_has_db_guards():
    frozen = (ROOT / "agents/sql/250_v2_edges.sql").read_text(encoding="utf-8")
    proposal = (ROOT / "agents/sql/420_v2_edge_contract.sql").read_text(encoding="utf-8")
    assert "connected_to_strategic_entity" in frozen
    assert "connected_to_um6p_ocp" in proposal
    assert "ghus_validate_entity_edge" in proposal
    assert "ghus_prevent_actor_family_cycle" in proposal
    assert "CREATE OR REPLACE VIEW actor_descendants" in proposal
    assert "source_id uuid NOT NULL" in frozen


@pytest.mark.skipif(
    not os.environ.get("V2_TEST_DATABASE_URL"),
    reason="V2_TEST_DATABASE_URL is required for isolated database enforcement",
)
def test_isolated_database_enforces_endpoints_cycles_and_idempotency():
    from src.db.session import SessionLocal

    with SessionLocal() as session:
        actors = session.execute(
            text("SELECT actor_id::text FROM actor ORDER BY actor_id LIMIT 3")
        ).scalars().all()
        source_id = session.execute(
            text("SELECT source_id::text FROM source ORDER BY source_id LIMIT 1")
        ).scalar_one()
        assert len(actors) == 3
        first = _request(subject_id=actors[0], object_id=actors[1], source_id=source_id)
        edge_id = append_entity_edge(session, first, live=True)
        assert append_entity_edge(session, first, live=True) == edge_id
        second = _request(
            subject_id=actors[1], object_id=actors[2], source_id=source_id,
            relationship_type="operated_by",
        )
        append_entity_edge(session, second, live=True)
        descendants = session.execute(text(
            "SELECT descendant_actor_id::text,depth FROM actor_descendants "
            "WHERE root_actor_id=CAST(:root AS uuid) ORDER BY depth"
        ), {"root": actors[2]}).all()
        assert (actors[1], 1) in descendants
        assert (actors[0], 2) in descendants

        with pytest.raises(DBAPIError, match="actor family cycle"), session.begin_nested():
            append_entity_edge(session, _request(
                subject_id=actors[2], object_id=actors[0], source_id=source_id,
            ), live=True)
        with pytest.raises(
            DBAPIError,
            match="missing actor object endpoint",
        ), session.begin_nested():
            append_entity_edge(session, _request(
                subject_id=actors[0],
                object_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
                source_id=source_id,
                relationship_type="collaborates_with",
            ), live=True)
        session.rollback()
