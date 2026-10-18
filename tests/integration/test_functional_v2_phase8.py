"""Phase 3-8 proof: an explicit sourced parent edge enters the real pipeline."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from agents.common.hub_families import FamilyEdge, resolve_actor_families
from agents.common.resolve_route import load_actor_candidates, route_actor
from tests.integration.test_functional_v2_phase3_7 import (
    Resolver,
    _guarded_url,
    _new_payload,
    _promote_live,
    _stage,
    _topic,
)


# The same guard its four sibling modules carry. Without it `_guarded_url()`
# raises a KeyError inside the module fixture when V2_TEST_DATABASE_URL is
# absent, so this module reported an ERROR where the others reported SKIP. The
# coverage is unchanged: with the database configured these tests still run.
pytestmark = pytest.mark.skipif(
    not os.environ.get("V2_TEST_DATABASE_URL"),
    reason="V2_TEST_DATABASE_URL is required for isolated integration tests",
)


@pytest.fixture(scope="module")
def phase8_session_factory():
    engine = create_engine(_guarded_url(), future=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    yield factory
    engine.dispose()


def test_phase8_explicit_parent_edge_and_phase7_family_integration(
    phase8_session_factory,
):
    with phase8_session_factory() as session:
        parent_id = session.execute(text(
            "SELECT actor_id::text FROM actor "
            "WHERE COALESCE(to_jsonb(actor)->>'actor_category',to_jsonb(actor)->>'actor_type','') "
            "<> 'aggregate' ORDER BY actor_id LIMIT 1"
        )).scalar_one()
        topic_id = _topic(session, f"phase8-{uuid.uuid4().hex[:10]}")
        payload = _new_payload(f"Phase 8 Child {uuid.uuid4().hex[:8]}", topic_id)
        payload["parent_connection"] = {
            "relationship_type": "unit_of",
            "actor_id": parent_id,
            "confidence": "high",
        }
        staged = _stage(session, payload, suffix="phase8-parent")
        route = route_actor(
            staged.normalized_payload, Resolver(), load_actor_candidates(session)
        )
        created = _promote_live(session, staged, route)

        edge = session.execute(text(
            "SELECT relationship_type,subject_id::text,object_id::text,source_id::text "
            "FROM entity_edge WHERE subject_type='actor' AND subject_id=CAST(:child AS uuid)"
        ), {"child": created.entity_id}).one()
        assert edge.relationship_type == "unit_of"
        assert edge.subject_id == created.entity_id
        assert edge.object_id == parent_id
        assert edge.source_id

        families = resolve_actor_families(
            [created.entity_id],
            [FamilyEdge(created.entity_id, parent_id, edge.relationship_type)],
        )
        assert families.family_by_actor[created.entity_id] == parent_id
        assert families.unresolved == {}
        assert session.execute(text(
            "SELECT COALESCE(to_jsonb(actor)->>'status',to_jsonb(actor)->>'record_status') "
            "FROM actor WHERE actor_id=CAST(:id AS uuid)"
        ), {"id": created.entity_id}).scalar_one() == "parked"
        assert session.execute(text(
            "SELECT count(*) FROM review_item WHERE entity_id=CAST(:id AS uuid) "
            "AND review_kind='verify_actor' AND status='pending'"
        ), {"id": created.entity_id}).scalar_one() == 1
