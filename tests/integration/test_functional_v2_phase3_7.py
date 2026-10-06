"""Isolated production-copy proof for the integrated Phase 3-7 actor path."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from agents.collection.light_pull import light_schema
from agents.common.resolve_route import load_actor_candidates, route_actor
from agents.discovery.promote import ACTOR_MAPPING_STEPS, map_new_actor
from agents.discovery.stage import SQLStageStore, stage_record
from agents.enrichment.decisions import record_verification_decision

pytestmark = pytest.mark.skipif(
    not os.environ.get("V2_TEST_DATABASE_URL"),
    reason="V2_TEST_DATABASE_URL is required for isolated integration tests",
)


class Resolver:
    HIGH = 0.96
    LOW = 0.18
    model_name = "controlled_integration_resolver"

    def __init__(self, *, candidate_id: str | None = None, score: float | None = None):
        self.candidate_id = candidate_id
        self.score = score

    def _candidates(self, _name):
        if self.candidate_id is None:
            return pd.DataFrame(columns=["actor_id", "name"])
        return pd.DataFrame([{"actor_id": self.candidate_id, "name": "Close Candidate"}])

    def _score(self, _record, candidates):
        scored = candidates.copy()
        scored["score"] = self.score
        return scored


def _guarded_url() -> str:
    raw = os.environ["V2_TEST_DATABASE_URL"]
    parsed = urlsplit(raw.replace("postgresql+psycopg2", "postgresql", 1))
    if (
        parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.port != 55432
        or not parsed.path.removeprefix("/").endswith("_test")
    ):
        raise RuntimeError("integration test refuses every target except localhost:55432/*_test")
    return raw


@pytest.fixture(scope="module")
def session_factory():
    engine = create_engine(_guarded_url(), future=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    yield factory
    engine.dispose()


def _source_run_id(session) -> str:
    return str(session.execute(text("SELECT run_id FROM scrape_run ORDER BY started_at LIMIT 1")).scalar_one())


def _stage(session, payload: dict[str, object], *, suffix: str):
    payload = {
        **payload,
        "natural_key": f"functional-v2-{suffix}-{uuid.uuid4()}",
        "source_url": payload.get("website") or f"https://{suffix}.example.test",
        "extracted_at": datetime.now(UTC).isoformat(),
        "sector_match": "in_sector",
    }
    return stage_record(
        SQLStageStore(session),
        run_id=_source_run_id(session),
        raw_document_id=None,
        entity_type="actor",
        record=payload,
        prompt_version="functional_v2_integration",
    )


def _topic(session, code: str) -> str:
    topic_id = str(uuid.uuid4())
    session.execute(
        text(
            "INSERT INTO topic(topic_id,code,name,description,active) "
            "VALUES(CAST(:id AS uuid),:code,:name,:definition,true)"
        ),
        {"id": topic_id, "code": code, "name": code, "definition": "Synthetic isolated test topic"},
    )
    session.commit()
    return topic_id


def _hub(session, *, topic_id: str, latitude: float, longitude: float, radius: float = 200) -> str:
    hub_id = str(uuid.uuid4())
    session.execute(
        text(
            "INSERT INTO hub(hub_id,name,slug,topic_id,center_latitude,center_longitude,radius_miles,"
            "center_frozen,center_method,center_method_version,center_computed_at) "
            "VALUES(CAST(:id AS uuid),:name,:slug,CAST(:topic AS uuid),:lat,:lon,:radius,"
            "false,'density_center','density_center_v1',now())"
        ),
        {"id": hub_id, "name": f"Synthetic Hub {hub_id[:8]}",
         "slug": f"synthetic-hub-{hub_id}", "topic": topic_id,
         "lat": latitude, "lon": longitude, "radius": radius},
    )
    session.commit()
    return hub_id


def _new_payload(name: str, topic_id: str, *, lat: float = 42.3601, lon: float = -71.0589):
    return {
        "name": name,
        "website": f"https://{uuid.uuid4().hex}.example.test",
        "actor_category": "company",
        "category_type": "corporate_rd_center",
        "classification_evidence": {
            "main_job": "The official source describes a company operating a climate technology R&D center."
        },
        "description": "Synthetic climate technology research for integration validation.",
        "country": "United States",
        "location_city": "Boston",
        "state_code": "MA",
        "latitude": lat,
        "longitude": lon,
        "topic_id": topic_id,
    }


def _promote_live(session, staged, route):
    """Mirror admission ownership of the outer transaction."""
    try:
        result = map_new_actor(
            staged, route, session=session, live=True, manage_transaction=False
        )
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise


def test_phase3_7_real_pipeline_and_hub_cases(session_factory):
    with session_factory() as session:
        mapped = load_actor_candidates(session)
        existing = next(item for item in mapped if item.get("name"))

        exact_payload = {"name": existing["name"], "website": existing.get("website") or ""}
        exact_staged = _stage(session, exact_payload, suffix="exact")
        exact_route = route_actor(exact_payload, Resolver(), mapped)
        assert exact_route.zone == "absorb"
        exact = _promote_live(session, exact_staged, exact_route)
        assert exact.action == "appended_to_existing"

        close_payload = {"name": f"{existing['name']} Research Division", "website": "https://close.example.test"}
        close_staged = _stage(session, close_payload, suffix="close")
        close_route = route_actor(
            close_payload,
            Resolver(candidate_id=str(existing["actor_id"]), score=0.999),
            mapped,
        )
        assert close_route.zone == "review"
        close = _promote_live(session, close_staged, close_route)
        assert close.action == "queued_for_review"

        topic_inside = _topic(session, f"inside-{uuid.uuid4().hex[:10]}")
        inside_hub = _hub(session, topic_id=topic_inside, latitude=42.36, longitude=-71.06)
        created_staged = _stage(
            session, _new_payload(f"Functional New Actor {uuid.uuid4().hex[:8]}", topic_inside),
            suffix="new",
        )
        created_route = route_actor(created_staged.normalized_payload, Resolver(), load_actor_candidates(session))
        created = _promote_live(session, created_staged, created_route)
        assert created.action == "created"
        assert created.step_trace == list(ACTOR_MAPPING_STEPS)
        assert session.execute(
            text("SELECT COALESCE(to_jsonb(actor)->>'status',to_jsonb(actor)->>'record_status') "
                 "FROM actor WHERE actor_id=CAST(:id AS uuid)"),
            {"id": created.entity_id},
        ).scalar_one() == "parked"
        assert session.execute(
            text("SELECT count(*) FROM review_item WHERE entity_id=CAST(:id AS uuid) AND review_kind='verify_actor'"),
            {"id": created.entity_id},
        ).scalar_one() == 1
        light_facts = session.execute(
            text(
                "SELECT fact_key,fact_value,collection_state,layer,source_origin,confidence "
                "FROM actor_fact WHERE actor_id=CAST(:id AS uuid) "
                "AND topic_id=CAST(:topic AS uuid) AND fact_type='light_pull'"
            ),
            {"id": created.entity_id, "topic": topic_inside},
        ).mappings().all()
        assert len(light_facts) == len(light_schema("company"))
        assert {row["fact_key"] for row in light_facts} == set(light_schema("company"))
        assert all(row["layer"] == 1 for row in light_facts)
        assert all(row["source_origin"] == "newly_found" for row in light_facts)
        assert all(row["confidence"] in {"high", "medium", "low"} for row in light_facts)
        by_key = {row["fact_key"]: row for row in light_facts}
        assert by_key["location"]["fact_value"]["region_code"] == "northeast"
        assert by_key["hub_assignment"]["fact_value"]["assigned_hub_ids"] == [inside_hub]
        hub_evaluation = by_key["hub_assignment"]["fact_value"]["evaluations"][0]
        assert hub_evaluation["selected"] is True
        assert hub_evaluation["distance_miles"] is not None
        assert by_key["parent_connection"]["fact_value"] == {
            "state": "standalone", "parent": None,
        }
        assert session.execute(
            text("SELECT count(*) FROM hub_actor WHERE actor_id=CAST(:id AS uuid) AND hub_id=CAST(:hub AS uuid)"),
            {"id": created.entity_id, "hub": inside_hub},
        ).scalar_one() == 1

        record_verification_decision(
            session, entity_type="actor", entity_ids=[created.entity_id],
            decision="rejected", decided_by="integration-test",
            notes="controlled rejected-rediscovery proof", rejection_reason="not in scope",
        )
        session.commit()
        rejected_candidates = load_actor_candidates(session)
        rejected = next(item for item in rejected_candidates if item["actor_id"] == created.entity_id)
        assert rejected["record_status"] == "rejected"
        rediscovered_staged = _stage(
            session,
            {"name": created_staged.normalized_payload["name"],
             "website": created_staged.normalized_payload["website"]},
            suffix="rejected-rediscovery",
        )
        rediscovered_route = route_actor(
            rediscovered_staged.normalized_payload, Resolver(), rejected_candidates
        )
        assert rediscovered_route.zone == "absorb"
        assert rediscovered_route.metadata["matched_record_status"] == "rejected"
        _promote_live(session, rediscovered_staged, rediscovered_route)
        assert session.execute(
            text(
                "SELECT decision FROM actor_verification_event "
                "WHERE actor_id=CAST(:id AS uuid) "
                "ORDER BY decided_at DESC NULLS LAST,recorded_at DESC,"
                "actor_verification_event_id DESC LIMIT 1"
            ), {"id": created.entity_id}
        ).scalar_one() == "rejected"

        topic_mismatch = _topic(session, f"mismatch-{uuid.uuid4().hex[:10]}")
        other_topic = _topic(session, f"other-{uuid.uuid4().hex[:10]}")
        mismatch_hub = _hub(session, topic_id=other_topic, latitude=42.36, longitude=-71.06)
        mismatch_staged = _stage(
            session, _new_payload(f"Mismatch Actor {uuid.uuid4().hex[:8]}", topic_mismatch),
            suffix="mismatch",
        )
        mismatch_route = route_actor(mismatch_staged.normalized_payload, Resolver(), load_actor_candidates(session))
        mismatch_route.metadata["hub_ids"] = [mismatch_hub]
        mismatch = _promote_live(session, mismatch_staged, mismatch_route)
        assert session.execute(
            text("SELECT count(*) FROM review_item WHERE entity_id=CAST(:id AS uuid) AND payload->>'canonical_outcome'='needs_review_topic'"),
            {"id": mismatch.entity_id},
        ).scalar_one() == 1

        topic_outside = _topic(session, f"outside-{uuid.uuid4().hex[:10]}")
        _hub(session, topic_id=topic_outside, latitude=34.0522, longitude=-118.2437, radius=50)
        outside_staged = _stage(
            session, _new_payload(f"Outside Actor {uuid.uuid4().hex[:8]}", topic_outside),
            suffix="outside",
        )
        outside_route = route_actor(outside_staged.normalized_payload, Resolver(), load_actor_candidates(session))
        outside = _promote_live(session, outside_staged, outside_route)
        assert session.execute(
            text("SELECT count(*) FROM hub_assignment_evidence WHERE actor_id=CAST(:id AS uuid) AND outside_radius"),
            {"id": outside.entity_id},
        ).scalar_one() == 1

        topic_overlap = _topic(session, f"overlap-{uuid.uuid4().hex[:10]}")
        near = _hub(session, topic_id=topic_overlap, latitude=42.36, longitude=-71.06)
        far = _hub(session, topic_id=topic_overlap, latitude=42.50, longitude=-71.20)
        overlap_staged = _stage(
            session, _new_payload(f"Overlap Actor {uuid.uuid4().hex[:8]}", topic_overlap),
            suffix="overlap",
        )
        overlap_route = route_actor(overlap_staged.normalized_payload, Resolver(), load_actor_candidates(session))
        overlap = _promote_live(session, overlap_staged, overlap_route)
        selected = session.execute(
            text("SELECT hub_id::text FROM hub_assignment_evidence WHERE actor_id=CAST(:id AS uuid) AND selected"),
            {"id": overlap.entity_id},
        ).scalars().all()
        assert selected == [near]
        assert far not in selected
        assert session.execute(
            text(
                "SELECT count(*) FROM review_item WHERE entity_id=CAST(:id AS uuid) "
                "AND review_kind='same_topic_overlap' "
                "AND payload->>'canonical_review_kind'='hub_radius_overlap' "
                "AND payload->>'canonical_outcome'='assigned_nearest_center'"
            ),
            {"id": overlap.entity_id},
        ).scalar_one() == 1
