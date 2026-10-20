"""Real isolated-database proof for verified-only Phase 10 Deep Pull."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from agents.collection.deep_pull import CollectedValue, DeepPullRequest, append_deep_pull
from agents.common.resolve_route import RouteDecision
from agents.discovery.promote import map_new_actor
from agents.discovery.stage import StagedRecord
from agents.enrichment.decisions import record_verification_decision

pytestmark = pytest.mark.skipif(
    not os.environ.get("V2_TEST_DATABASE_URL"), reason="V2_TEST_DATABASE_URL is required"
)


def _url():
    raw = os.environ["V2_TEST_DATABASE_URL"]
    parsed = urlsplit(raw.replace("postgresql+psycopg2", "postgresql", 1))
    if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port != 55432 \
            or not parsed.path.removeprefix("/").endswith("_test"):
        raise RuntimeError("Phase 10 integration test refuses non-local/non-test databases")
    return raw


@pytest.fixture(scope="module")
def session_factory():
    engine = create_engine(_url(), future=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    yield factory
    engine.dispose()


def test_verified_topic_gate_and_live_layer2_append(session_factory):
    with session_factory() as session:
        topic_id = str(uuid.uuid4())
        session.execute(text(
            "INSERT INTO topic(topic_id,code,name,description,active) "
            "VALUES(CAST(:id AS uuid),:code,:code,'Phase 10 isolated topic',true)"
        ), {"id": topic_id, "code": f"deep-{uuid.uuid4().hex[:10]}"})
        session.commit()
        run_id = str(session.execute(text(
            "SELECT run_id FROM scrape_run ORDER BY started_at LIMIT 1"
        )).scalar_one())
        now = datetime.now(UTC)
        staged = StagedRecord(
            run_id=run_id, raw_document_id=None, entity_type="actor",
            natural_key=f"deep-{uuid.uuid4()}", source_url="https://deep.example.test",
            payload={}, normalized_payload={
                "name": f"Deep Pull Actor {uuid.uuid4().hex[:8]}",
                "website": "https://deep.example.test", "description": "Topic research.",
                "actor_category": "company", "category_type": "private_company",
                "classification_evidence": {"main_job": "A corporate topic R&D center."},
                "country": "United States", "location_city": "Boston", "state_code": "MA",
                "topic_id": topic_id, "match_reason": "Official topic work is documented.",
            }, prompt_version="phase10", extracted_at=now.isoformat(),
        )
        created = map_new_actor(
            staged, RouteDecision(zone="create", score=0.0, metadata={"topic_id": topic_id}),
            session=session, live=True, manage_transaction=False,
        )
        session.commit()
        request = DeepPullRequest(
            created.entity_id, topic_id, "company", ("relevant_products",),
            "ghus-integration-reviewer", str(uuid.uuid4()),
        )
        value = CollectedValue(
            "relevant_products", {"items": ["Topic product"]}, "found",
            "https://deep.example.test/product", "newly_found", now, "high",
        )
        with pytest.raises(PermissionError):
            append_deep_pull(session, request, {"relevant_products": value}, live=True)
        session.rollback()
        record_verification_decision(
            session, entity_type="actor", entity_ids=[created.entity_id], decision="verified",
            decided_by="ghus-integration-reviewer", topic_id=topic_id,
        )
        session.commit()
        assert append_deep_pull(
            session, request, {"relevant_products": value}
        ) == ["would_append"]
        append_deep_pull(session, request, {"relevant_products": value}, live=True)
        session.commit()
        row = session.execute(text(
            "SELECT layer,fact_type,fact_key,collection_state,source_origin,confidence "
            "FROM actor_fact WHERE actor_id=CAST(:actor AS uuid) "
            "AND topic_id=CAST(:topic AS uuid) AND fact_type='deep_pull'"
        ), {"actor": created.entity_id, "topic": topic_id}).mappings().one()
        assert dict(row) == {
            "layer": 2, "fact_type": "deep_pull", "fact_key": "relevant_products",
            "collection_state": "found", "source_origin": "newly_found", "confidence": "high",
        }
