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


# Sector is much broader than topic, so a fixture hub tagged with a real sector
# would be evaluated alongside every production hub in that sector -- there are
# five AGRI hubs in the restored copy. The fixture gets its own sector so the
# test stays isolated from them.
# Unique per run: this database is not reset between runs, so a fixed code
# would make each run's hubs candidates for the next one's actors.
FIXTURE_SECTOR = f"FXSECT{uuid.uuid4().hex[:8].upper()}"


def _scenario_sector() -> str:
    """A sector of its own, so one scenario's hubs do not compete in another.

    Since 2026-10-08 hub membership gates on SECTOR, not topic. A shared
    fixture sector therefore makes every synthetic hub a candidate
    everywhere, which is how the nearest-wins case below ended up tying on
    distance against a hub from an unrelated scenario.
    """

    return f"FXSECT{uuid.uuid4().hex[:8].upper()}"
FIXTURE_OTHER_SECTOR = f"FXOTHER{uuid.uuid4().hex[:8].upper()}"


def _fixture_sector(session, code: str = None) -> None:
    session.execute(
        text(
            "INSERT INTO sector(code,name,description,is_thematic,active) "
            "VALUES(:code,:name,'Synthetic sector, integration test only',"
            "false,true) ON CONFLICT (code) DO NOTHING"
        ),
        {"code": code or FIXTURE_SECTOR, "name": f"FX Integration Sector {code or FIXTURE_SECTOR}"},
    )
    session.commit()


def _hub(session, *, topic_id: str, latitude: float, longitude: float, radius: float = 200,
         sector_code: str = FIXTURE_SECTOR) -> str:
    """A synthetic hub. It needs a SECTOR, because that is Test 1 since 2026-10-08."""

    _fixture_sector(session, sector_code)

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
    session.execute(
        text(
            "INSERT INTO hub_sector(hub_id,sector_id,is_primary,source) "
            "SELECT CAST(:id AS uuid),sector_id,true,'integration fixture' "
            "FROM sector WHERE code=:code"
        ),
        {"id": hub_id, "code": sector_code},
    )
    session.commit()
    return hub_id


def _new_payload(name: str, topic_id: str, *, lat: float = 42.3601, lon: float = -71.0589,
                 sector_code: str = FIXTURE_SECTOR):
    return {
        "name": name,
        "website": f"https://{uuid.uuid4().hex}.example.test",
        "actor_category": "company",
        "category_type": "private_company",
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
        # Hub membership gates on sector; the staged record carries it through.
        "sector_codes": [sector_code],
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
        sector_inside = _scenario_sector()
        inside_hub = _hub(session, topic_id=topic_inside, latitude=42.36, longitude=-71.06,
                          sector_code=sector_inside)
        created_staged = _stage(
            session, _new_payload(f"Functional New Actor {uuid.uuid4().hex[:8]}", topic_inside,
                                  sector_code=sector_inside),
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
        # Every hub in the actor's sector is evaluated, so the selected one is
        # found by its flag rather than by position in the list.
        evaluations = by_key["hub_assignment"]["fact_value"]["evaluations"]
        selected = [item for item in evaluations if item["selected"]]
        assert len(selected) == 1, "exactly one hub is selected"
        hub_evaluation = selected[0]
        assert hub_evaluation["hub_id"] == inside_hub
        assert hub_evaluation["distance_miles"] is not None
        # Test 1 was the sector, and both results travel with the evidence.
        assert hub_evaluation["dimension"] == "sector"
        assert hub_evaluation["sector_matched"] is True
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

        # A different SECTOR is what blocks assignment now. A different topic
        # does not: the actor joins, and the topic mismatch is recorded on the
        # evidence rather than refusing the hub (GHUS decision, 2026-10-08).
        topic_mismatch = _topic(session, f"mismatch-{uuid.uuid4().hex[:10]}")
        other_topic = _topic(session, f"other-{uuid.uuid4().hex[:10]}")
        mismatch_hub = _hub(
            session, topic_id=other_topic, latitude=42.36, longitude=-71.06,
            sector_code=FIXTURE_OTHER_SECTOR,
        )
        mismatch_staged = _stage(
            session, _new_payload(f"Mismatch Actor {uuid.uuid4().hex[:8]}", topic_mismatch),
            suffix="mismatch",
        )
        mismatch_route = route_actor(mismatch_staged.normalized_payload, Resolver(), load_actor_candidates(session))
        mismatch_route.metadata["hub_ids"] = [mismatch_hub]
        mismatch = _promote_live(session, mismatch_staged, mismatch_route)
        assert session.execute(
            text("SELECT count(*) FROM review_item WHERE entity_id=CAST(:id AS uuid) AND payload->>'canonical_outcome'='needs_review_sector'"),
            {"id": mismatch.entity_id},
        ).scalar_one() == 1
        # And the evidence records that the sector failed while keeping the
        # topic result alongside it.
        gate = session.execute(
            text(
                "SELECT outcome,sector_matched,topic_matched,dimension "
                "FROM hub_assignment_evidence WHERE actor_id=CAST(:id AS uuid) "
                "AND hub_id=CAST(:hub AS uuid)"
            ),
            {"id": mismatch.entity_id, "hub": mismatch_hub},
        ).mappings().one()
        assert gate["outcome"] == "needs_review_sector"
        assert gate["sector_matched"] is False and gate["dimension"] == "sector"

        topic_outside = _topic(session, f"outside-{uuid.uuid4().hex[:10]}")
        sector_outside = _scenario_sector()
        _hub(session, topic_id=topic_outside, latitude=34.0522, longitude=-118.2437, radius=50,
             sector_code=sector_outside)
        outside_staged = _stage(
            session, _new_payload(f"Outside Actor {uuid.uuid4().hex[:8]}", topic_outside,
                                  sector_code=sector_outside),
            suffix="outside",
        )
        outside_route = route_actor(outside_staged.normalized_payload, Resolver(), load_actor_candidates(session))
        outside = _promote_live(session, outside_staged, outside_route)
        assert session.execute(
            text("SELECT count(*) FROM hub_assignment_evidence WHERE actor_id=CAST(:id AS uuid) AND outside_radius"),
            {"id": outside.entity_id},
        ).scalar_one() == 1

        topic_overlap = _topic(session, f"overlap-{uuid.uuid4().hex[:10]}")
        sector_overlap = _scenario_sector()
        near = _hub(session, topic_id=topic_overlap, latitude=42.36, longitude=-71.06,
                    sector_code=sector_overlap)
        far = _hub(session, topic_id=topic_overlap, latitude=42.50, longitude=-71.20,
                   sector_code=sector_overlap)
        overlap_staged = _stage(
            session, _new_payload(f"Overlap Actor {uuid.uuid4().hex[:8]}", topic_overlap,
                                  sector_code=sector_overlap),
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


def test_a_same_sector_hub_is_assignable_even_when_its_topic_differs(session_factory):
    """Test 1 is the SECTOR. A same-sector hub is a legitimate match.

    The membership then records the HUB's topic, which is what
    `hub_actor.topic_id` means: approved migration 486 fills it as
    coalesce(ha.topic_id, h.topic_id), and contract 405 constrains the pair
    (hub_id, topic_id) against hub. Recording the actor's topic instead made
    this insert fail the foreign key.
    """

    with session_factory() as session:
        sector = _scenario_sector()
        hub_topic = _topic(session, f"hubtopic-{uuid.uuid4().hex[:10]}")
        actor_topic = _topic(session, f"acttopic-{uuid.uuid4().hex[:10]}")
        hub_id = _hub(session, topic_id=hub_topic, latitude=42.36, longitude=-71.06,
                      sector_code=sector)
        staged = _stage(
            session,
            _new_payload(f"Cross Topic Actor {uuid.uuid4().hex[:8]}", actor_topic,
                         sector_code=sector),
            suffix="crosstopic",
        )
        route = route_actor(staged.normalized_payload, Resolver(), load_actor_candidates(session))
        promoted = _promote_live(session, staged, route)
        assigned = session.execute(
            text("SELECT hub_id::text FROM hub_actor WHERE actor_id=CAST(:id AS uuid)"),
            {"id": promoted.entity_id},
        ).scalars().all()
        assert assigned == [hub_id], "a same-sector hub must be assignable whatever its topic"
        # And the row carries the hub's topic, not the actor's.
        recorded = session.execute(
            text("SELECT topic_id::text FROM hub_actor WHERE actor_id=CAST(:id AS uuid)"),
            {"id": promoted.entity_id},
        ).scalar_one()
        assert recorded == hub_topic
        assert recorded != actor_topic


def test_an_actor_with_a_sector_and_no_topic_can_still_be_promoted(session_factory):
    """A sector is enough to match a hub. Having no topic must not break promotion.

    GHUS decision 3 leaves actor topics to Light Pull enrichment, so most actors
    have none. The membership still needs a topic because contract 405 makes the
    column NOT NULL - and it takes the hub's.
    """

    with session_factory() as session:
        sector = _scenario_sector()
        hub_topic = _topic(session, f"notopic-{uuid.uuid4().hex[:10]}")
        _hub(session, topic_id=hub_topic, latitude=42.36, longitude=-71.06,
             sector_code=sector)
        payload = _new_payload(f"Topicless Actor {uuid.uuid4().hex[:8]}", hub_topic,
                               sector_code=sector)
        payload.pop("topic_id")          # what Light Pull has not filled in yet
        staged = _stage(session, payload, suffix="notopic")
        route = route_actor(staged.normalized_payload, Resolver(), load_actor_candidates(session))
        promoted = _promote_live(session, staged, route)
        assert promoted.entity_id, "an actor without a topic must still promote"
        recorded = session.execute(
            text("SELECT topic_id::text FROM hub_actor WHERE actor_id=CAST(:id AS uuid)"),
            {"id": promoted.entity_id},
        ).scalars().all()
        assert recorded == [hub_topic], "the membership takes the hub's topic"



def test_an_accepted_candidate_is_created_verified_by_the_agent(session_factory):
    """Decision 2026-10-14: accepted (score and every gate) -> Verified, labelled.

    Written after the first live request run stopped at exactly this step.
    """
    from agents.discovery.promote import AUTO_ACCEPT_PAYLOAD_KEY

    with session_factory() as session:
        topic = _topic(session, f"auto-{uuid.uuid4().hex[:10]}")
        sector = _scenario_sector()
        _hub(session, topic_id=topic, latitude=42.36, longitude=-71.06, sector_code=sector)
        payload = {
            **_new_payload(f"Accepted Actor {uuid.uuid4().hex[:8]}", topic, sector_code=sector),
            AUTO_ACCEPT_PAYLOAD_KEY: "Accepted by the discovery agent: score 0.91 meets 0.85 "
                                     "and every quality gate held.",
        }
        staged = _stage(session, payload, suffix="accepted")
        route = route_actor(staged.normalized_payload, Resolver(), load_actor_candidates(session))
        created = _promote_live(session, staged, route)

        assert created.action == "created"
        assert created.review_id is None
        assert created.step_trace == [*ACTOR_MAPPING_STEPS[:-1], "verified_by_agent"]
        status = session.execute(
            text("SELECT status FROM actor WHERE actor_id=CAST(:id AS uuid)"),
            {"id": created.entity_id},
        ).scalar_one()
        assert status == "verified"
        event = session.execute(
            text("SELECT decision, decided_by, decision_origin, reason FROM actor_verification_event "
                 "WHERE actor_id=CAST(:id AS uuid)"),
            {"id": created.entity_id},
        ).mappings().one()
        assert event["decision_origin"] == "agent_auto_accept"
        assert event["decided_by"] == "discovery-agent"
        assert "every quality gate held" in event["reason"]
        assert session.execute(
            text("SELECT count(*) FROM review_item WHERE entity_id=CAST(:id AS uuid) "
                 "AND review_kind='verify_actor'"),
            {"id": created.entity_id},
        ).scalar_one() == 0


def test_an_agent_verified_actor_cannot_be_deep_pulled_without_a_person(session_factory):
    """Auto-Verified (agent_auto_accept) never authorizes topic-specific Deep Pull.

    Deep Pull needs the latest GHUS PERSON decision for that exact actor and
    topic. An agent's verification is ignored by that gate; a person's
    verification authorizes that one topic only.
    """
    from datetime import UTC, datetime

    from agents.collection.deep_pull import (
        CollectedValue, DeepPullRequest, actor_is_verified_for_topic, append_deep_pull,
    )
    from agents.discovery.promote import AUTO_ACCEPT_PAYLOAD_KEY
    from agents.enrichment.decisions import record_verification_decision

    with session_factory() as session:
        topic = _topic(session, f"deep-{uuid.uuid4().hex[:10]}")
        other_topic = _topic(session, f"deep-other-{uuid.uuid4().hex[:10]}")
        sector = _scenario_sector()
        _hub(session, topic_id=topic, latitude=42.36, longitude=-71.06, sector_code=sector)
        payload = {
            **_new_payload(f"Agent Verified {uuid.uuid4().hex[:8]}", topic, sector_code=sector),
            AUTO_ACCEPT_PAYLOAD_KEY: "Accepted by the discovery agent: score 0.91; every gate held.",
        }
        staged = _stage(session, payload, suffix="deep")
        route = route_actor(staged.normalized_payload, Resolver(), load_actor_candidates(session))
        created = _promote_live(session, staged, route)
        actor_id = created.entity_id
        assert session.execute(
            text("SELECT status FROM actor WHERE actor_id=CAST(:id AS uuid)"), {"id": actor_id}
        ).scalar_one() == "verified"

        request = DeepPullRequest(
            actor_id=actor_id, topic_id=topic, actor_category="company",
            selected_fields=("rd_innovation",), requested_by="integration-test",
            request_id=str(uuid.uuid4()),
        )
        value = CollectedValue(field_key="rd_innovation", value="x", collection_state="found",
                               source_url="https://example.test", source_origin="newly_found",
                               date_read=datetime.now(UTC), confidence="medium")
        # Verified by the agent - but not by a person, so no Deep Pull.
        assert actor_is_verified_for_topic(session, actor_id=actor_id, topic_id=topic) is False
        with pytest.raises(PermissionError):
            append_deep_pull(session, request, {"rd_innovation": value}, live=False)

        # A person verifies it for THIS topic: that topic opens, no other.
        record_verification_decision(
            session, entity_type="actor", entity_ids=[actor_id], decision="verified",
            decided_by="ghus-reviewer", topic_id=topic,
        )
        session.commit()
        assert actor_is_verified_for_topic(session, actor_id=actor_id, topic_id=topic) is True
        assert actor_is_verified_for_topic(session, actor_id=actor_id, topic_id=other_topic) is False


def test_a_reviewer_can_add_a_sector_and_its_topic_once(session_factory):
    """A real actor fits no GHUS sector: a reviewer adds one, written only by
    decisions.create_sector, with its mirror topic; asking twice reuses it."""
    from agents.enrichment.decisions import create_sector

    name = f"Water Technology {uuid.uuid4().hex[:6]}"
    with session_factory() as session:
        created = create_sector(session, name=name, created_by="integration-reviewer",
                                code=f"WT{uuid.uuid4().hex[:6].upper()}")
        session.commit()
        assert created["created"] is True
        row = session.execute(text(
            "SELECT s.active, s.is_thematic, t.code AS topic_code FROM sector s "
            "JOIN topic t ON t.code = s.code WHERE s.code = :code"), {"code": created["code"]}
        ).mappings().one()
        assert row["active"] and row["is_thematic"] and row["topic_code"] == created["code"]
        again = create_sector(session, name=name.upper(), created_by="someone-else")
        assert again["created"] is False and again["code"] == created["code"]
