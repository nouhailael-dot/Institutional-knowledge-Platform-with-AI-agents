"""Isolated PostgreSQL proof of the Phase 11 immutable fact lifecycle."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from agents.collection.deep_pull import (
    CollectedValue,
    DeepPullRequest,
    append_deep_pull,
    append_specific_ask,
)
from agents.common.fact_reads import actor_fact_history, current_actor_facts
from agents.common.facts import ActorFactWrite
from agents.enrichment.decisions import append_actor_fact

pytestmark = pytest.mark.skipif(not os.environ.get("V2_TEST_DATABASE_URL"),
                                reason="V2_TEST_DATABASE_URL is required")
NOW = datetime(2026, 10, 5, tzinfo=UTC)


def _guarded_url() -> str:
    raw = os.environ["V2_TEST_DATABASE_URL"]
    parsed = urlsplit(raw.replace("postgresql+psycopg2", "postgresql", 1))
    if (
        parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.port != 55432
        or not parsed.path.removeprefix("/").endswith("_test")
    ):
        raise RuntimeError("Phase 11 integration test refuses non-local/non-test databases")
    return raw


@pytest.fixture(scope="module")
def session_factory():
    engine = create_engine(_guarded_url(), future=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    yield factory
    engine.dispose()


def _actor_and_topic(session):
    actor = session.execute(text(
        "SELECT actor_id::text FROM actor ORDER BY actor_id LIMIT 1"
    )).scalar_one()
    topic = session.execute(text(
        "SELECT topic_id::text FROM topic ORDER BY topic_id LIMIT 1"
    )).scalar_one_or_none()
    if topic is None:
        topic = str(uuid.uuid4())
        session.execute(text(
            "INSERT INTO topic(topic_id,code,name) VALUES(CAST(:id AS uuid),:code,:name)"
        ), {"id": topic, "code": f"phase11-{topic[:8]}",
            "name": f"Phase 11 {topic[:8]}"})
    return actor, topic


def _write(actor, topic, key, value, *, confidence="medium", when=NOW,
           origin="newly_found", creator="agent.phase11", fact_type="light_pull"):
    return ActorFactWrite(
        actor_id=actor, topic_id=topic, field_key=key, fact_type=fact_type, layer=1,
        value=value, collection_state="found", source_url=f"https://facts.example/{uuid.uuid4()}",
        source_origin=origin, date_read=when, confidence=confidence,
        created_by=creator, request_id=str(uuid.uuid4()),
    )


def test_complete_fact_lifecycle_current_and_history(session_factory):
    with session_factory() as session:
        actor, topic = _actor_and_topic(session)
        key = f"phase11_{uuid.uuid4().hex}"

        first = append_actor_fact(session, _write(actor, topic, key, {"value": "A"}), live=True)
        session.commit()
        assert session.execute(text(
            "SELECT actor_fact_id::text FROM actor_fact_current_v2 WHERE actor_id=CAST(:a AS uuid) "
            "AND topic_id=CAST(:t AS uuid) AND fact_key=:k"
        ), {"a": actor, "t": topic, "k": key}).scalar_one() == first

        same = append_actor_fact(session, _write(
            actor, topic, key, {"value": "A"}, confidence="high", when=NOW+timedelta(days=1)
        ), live=True)
        session.commit()
        assert same == first
        assert session.execute(text(
            "SELECT count(*) FROM fact_corroboration WHERE actor_fact_id=CAST(:id AS uuid)"
        ), {"id": first}).scalar_one() == 1

        newer = append_actor_fact(session, _write(
            actor, topic, key, {"value": "B"}, confidence="high", when=NOW+timedelta(days=2)
        ), live=True)
        session.commit()
        current = session.execute(text(
            "SELECT actor_fact_id::text,supersedes_fact_id::text FROM actor_fact_current_v2 "
            "WHERE actor_id=CAST(:a AS uuid) AND topic_id=CAST(:t AS uuid) AND fact_key=:k"
        ), {"a": actor, "t": topic, "k": key}).one()
        assert current == (newer, first)

        weaker = append_actor_fact(session, _write(
            actor, topic, key, {"value": "C"}, confidence="low", when=NOW+timedelta(days=3)
        ), live=True)
        session.commit()
        assert session.execute(text(
            "SELECT lifecycle_state FROM actor_fact WHERE actor_fact_id=CAST(:id AS uuid)"
        ), {"id": weaker}).scalar_one() == "conflict_flagged"
        assert session.execute(text(
            "SELECT count(*) FROM review_item WHERE review_kind='fact_conflict' "
            "AND payload->>'new_fact_id'=:id"
        ), {"id": weaker}).scalar_one() == 1

        human_key = f"human_{uuid.uuid4().hex}"
        human = append_actor_fact(session, _write(
            actor, topic, human_key, "GHUS value", origin="ghus_manual", creator="ghus-user"
        ), live=True)
        session.commit()
        pending = append_actor_fact(session, _write(
            actor, topic, human_key, "Agent difference", confidence="high",
            when=NOW+timedelta(days=9)
        ), live=True)
        session.commit()
        assert session.execute(text(
            "SELECT actor_fact_id::text FROM actor_fact_current_v2 WHERE actor_id=CAST(:a AS uuid) "
            "AND topic_id=CAST(:t AS uuid) AND fact_key=:k"
        ), {"a": actor, "t": topic, "k": human_key}).scalar_one() == human
        assert session.execute(text(
            "SELECT lifecycle_state FROM actor_fact WHERE actor_fact_id=CAST(:id AS uuid)"
        ), {"id": pending}).scalar_one() == "pending_update"
        assert session.execute(text(
            "SELECT count(*) FROM review_item WHERE review_kind='pending_update' "
            "AND payload->>'new_fact_id'=:id"
        ), {"id": pending}).scalar_one() == 1

        history = session.execute(text(
            "SELECT actor_fact_id::text,is_current FROM actor_fact_history "
            "WHERE actor_id=CAST(:a AS uuid) AND topic_id=CAST(:t AS uuid) AND fact_key=:k"
        ), {"a": actor, "t": topic, "k": key}).all()
        assert len(history) == 3
        assert sum(bool(row.is_current) for row in history) == 1
        with pytest.raises(Exception, match="append-only"):
            session.execute(text(
                "UPDATE actor_fact SET fact_value='\"overwrite\"'::jsonb "
                "WHERE actor_fact_id=CAST(:id AS uuid)"
            ), {"id": first})
        session.rollback()


def test_light_deep_and_specific_ask_share_one_fact_lifecycle(session_factory):
    with session_factory() as session:
        actor, topic = _actor_and_topic(session)
        session.execute(text(
            "INSERT INTO actor_verification_event("
            "actor_id,topic_id,decision,decided_by,decided_at,decision_origin) "
            "VALUES(CAST(:actor AS uuid),CAST(:topic AS uuid),'verified',"
            "'phase11-test',now(),'ghus_review')"
        ), {"actor": actor, "topic": topic})
        session.commit()

        light_key = f"light_{uuid.uuid4().hex}"
        first = append_actor_fact(
            session, _write(actor, topic, light_key, {"value": "light"}), live=True
        )
        same = append_actor_fact(
            session, _write(actor, topic, light_key, {"value": "light"}, when=NOW + timedelta(days=1)),
            live=True,
        )
        assert same == first

        deep_key = f"deep_{uuid.uuid4().hex}"
        deep_request = DeepPullRequest(
            actor_id=actor, topic_id=topic, actor_category="company",
            selected_fields=("relevant_products",), requested_by="agent.phase11",
            request_id=str(uuid.uuid4()),
        )
        deep_value = CollectedValue(
            field_key=deep_key, value={"product": "A"}, collection_state="found",
            source_url="https://facts.example/deep", source_origin="newly_found",
            date_read=NOW, confidence="medium",
        )
        # The request schema controls the ledger key; use its selected field here.
        deep_value = CollectedValue(**{**deep_value.__dict__, "field_key": "relevant_products"})
        deep_id = append_deep_pull(
            session, deep_request, {"relevant_products": deep_value}, live=True
        )[0]

        ask_key = f"ask_{uuid.uuid4().hex}"
        ask_value = CollectedValue(
            field_key=ask_key, value={"answer": "documented"}, collection_state="found",
            source_url="https://facts.example/ask", source_origin="newly_found",
            date_read=NOW, confidence="high",
        )
        ask_id = append_specific_ask(
            session, actor_id=actor, topic_id=topic, requested_by="ghus-requester",
            request_text="What is documented?", request_id=str(uuid.uuid4()),
            values=[ask_value], live=True,
        )[0]
        session.commit()

        current = current_actor_facts(session, actor_id=actor, topic_id=topic)
        by_key = {row["fact_key"]: row for row in current}
        assert by_key[light_key]["actor_fact_id"] == uuid.UUID(first)
        assert by_key["relevant_products"]["actor_fact_id"] == uuid.UUID(deep_id)
        assert by_key[ask_key]["actor_fact_id"] == uuid.UUID(ask_id)
        assert by_key["relevant_products"]["fact_type"] == "deep_pull"
        assert by_key[ask_key]["fact_type"] == "specific_ask"
        assert len(actor_fact_history(session, actor_id=actor, topic_id=topic,
                                      fact_key=light_key)) == 1
