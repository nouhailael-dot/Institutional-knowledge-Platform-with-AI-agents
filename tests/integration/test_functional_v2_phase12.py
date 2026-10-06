"""Isolated proof for the corrected Phase 12 existing-actor policy."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from agents.collection.deep_pull import actor_is_verified_for_topic

pytestmark = pytest.mark.skipif(
    not os.environ.get("V2_PHASE12_POLICY_DATABASE_URL"),
    reason="V2_PHASE12_POLICY_DATABASE_URL is required",
)


@pytest.fixture(scope="module")
def engine():
    raw = os.environ["V2_PHASE12_POLICY_DATABASE_URL"]
    assert "127.0.0.1:55432/ghus_v2_phase12_policy_test" in raw
    value = create_engine(raw)
    try:
        yield value
    finally:
        value.dispose()


def test_corrected_existing_actor_counts(engine):
    with engine.connect() as connection:
        actor = connection.execute(text("""
            SELECT count(*) total,
              count(*) FILTER(WHERE status='verified') verified,
              count(*) FILTER(WHERE category_type IS NOT NULL) type_populated,
              count(*) FILTER(WHERE category_type IS NULL) type_pending
            FROM actor
        """)).mappings().one()
        mapping = connection.execute(text("""
            SELECT count(*) FILTER(WHERE mapping_status='mapped') mapped,
              count(*) FILTER(WHERE mapping_status='requires_review') needs_review
            FROM actor_category_migration_audit
        """)).mappings().one()
        reviews = connection.execute(text("""
            SELECT count(*) FROM review_item
            WHERE review_kind='category_doubt'
              AND payload->>'migration_batch_id'='phase12_existing_canonical_2026_10'
        """)).scalar_one()
        assert dict(actor) == {
            "total": 965,
            "verified": 965,
            "type_populated": 0,
            "type_pending": 965,
        }
        assert dict(mapping) == {"mapped": 751, "needs_review": 214}
        assert reviews == 214


def test_migration_verification_is_honest_and_not_a_named_human_decision(engine):
    with engine.connect() as connection:
        row = connection.execute(text("""
            SELECT count(*) total,
              count(*) FILTER(WHERE decision='verified'
                AND decision_origin='existing_canonical_migration'
                AND decided_by IS NULL AND decided_at IS NULL
                AND topic_id IS NULL
                AND migration_batch_id='phase12_existing_canonical_2026_10') honest
            FROM actor_verification_event
        """)).mappings().one()
        assert dict(row) == {"total": 965, "honest": 965}


def test_direct_status_change_and_forged_migration_event_are_rejected(engine):
    with engine.connect() as connection:
        actor_id = connection.execute(text(
            "SELECT actor_id FROM actor ORDER BY actor_id LIMIT 1"
        )).scalar_one()
        with (
            pytest.raises(DBAPIError, match="requires actor_verification_event"),
            connection.begin_nested(),
        ):
            connection.execute(
                text("UPDATE actor SET status='rejected' WHERE actor_id=:actor"),
                {"actor": actor_id},
            )
        connection.rollback()
        with connection.begin():
            connection.execute(text("SET LOCAL ROLE service_role"))
            with pytest.raises(DBAPIError), connection.begin_nested():
                connection.execute(text("""
                        INSERT INTO actor_verification_event(
                          actor_id,decision,decision_origin,migration_batch_id
                        ) VALUES(:actor,'verified','existing_canonical_migration','forged')
                    """), {"actor": actor_id})


def test_bootstrap_verified_status_does_not_authorize_topic_deep_pull(engine):
    with Session(engine) as session, session.begin():
        actor_id = session.execute(text(
            "SELECT actor_id::text FROM actor ORDER BY actor_id LIMIT 1"
        )).scalar_one()
        topic_id = str(uuid.uuid4())
        session.execute(text("""
            INSERT INTO topic(topic_id,code,name,description)
            VALUES(CAST(:topic AS uuid),:code,:name,'phase12 test')
        """), {"topic": topic_id, "code": f"phase12-{topic_id}", "name": "Phase 12 test"})
        assert not actor_is_verified_for_topic(
            session, actor_id=actor_id, topic_id=topic_id
        )
        session.execute(text("""
            INSERT INTO actor_verification_event(
              actor_id,topic_id,decision,decided_by,decided_at,reason,decision_origin
            ) VALUES(CAST(:actor AS uuid),CAST(:topic AS uuid),'verified',
              'ghus-test-reviewer',now(),'isolated authorization proof','ghus_review')
        """), {"actor": actor_id, "topic": topic_id})
        assert actor_is_verified_for_topic(
            session, actor_id=actor_id, topic_id=topic_id
        )
        session.rollback()


def test_final_cutover_fails_closed_without_loss_audit_attestation(engine):
    with engine.connect() as connection:
        count = connection.execute(text(
            "SELECT count(*) FROM architecture_v2_cutover_attestation "
            "WHERE audit_name='pre_cutover_data_loss_audit' AND passed"
        )).scalar_one()
        assert count == 0
