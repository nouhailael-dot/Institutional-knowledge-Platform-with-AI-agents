"""Phase 1 sectors: hub-derived links, checked description reads, and the writer."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from agents.common.llm import FixtureToolClient
from agents.enrichment.phase1_sectors import (
    classify_from_description,
    hub_links,
    usable_description,
)

SECTORS = [{"code": "WATER", "name": "Water"}, {"code": "AGRI", "name": "Agriculture"},
           {"code": "ENERGY", "name": "Energy Transition"}]
ACTOR = {"actor_id": "a", "name": "Plains Irrigation Lab", "actor_category": "research_center",
         "description": "The lab develops precision irrigation and groundwater monitoring for farms."}


def test_one_hub_sector_is_the_primary_and_the_reason_names_the_hub():
    links = hub_links([{"hub": "Kansas Water Hub", "code": "WATER", "is_primary": True}])
    assert links == [{"sector": "WATER", "primary": True, "match_strength": "moderate",
                      "reason": links[0]["reason"]}]
    assert "Kansas Water Hub" in links[0]["reason"] and "Derived" in links[0]["reason"]


def test_several_hub_sectors_keep_a_primary_only_when_the_hubs_agree_on_one():
    agreed = hub_links([{"hub": "H1", "code": "WATER", "is_primary": True},
                        {"hub": "H1", "code": "AGRI", "is_primary": False}])
    assert {l["sector"]: l["primary"] for l in agreed} == {"AGRI": False, "WATER": True}
    split = hub_links([{"hub": "H1", "code": "WATER", "is_primary": True},
                       {"hub": "H2", "code": "AGRI", "is_primary": True}])
    assert not any(l["primary"] for l in split)


def test_a_placeholder_or_short_description_is_not_used():
    assert not usable_description("")
    assert not usable_description("Water org.")
    assert not usable_description("Details should be verified from primary sources before use here.")
    assert usable_description(ACTOR["description"])


def test_a_checked_answer_links_only_the_main_sector_as_primary():
    client = FixtureToolClient({"sectors": ["WATER", "AGRI"], "confidence": "high",
                                "evidence_quote": "precision irrigation and groundwater monitoring"})
    result = classify_from_description(client, ACTOR, SECTORS)
    assert [(l["sector"], l["primary"]) for l in result["links"]] == [("WATER", True)]
    assert "groundwater monitoring" in result["links"][0]["reason"]


def test_a_quote_matches_across_curly_quotes_and_dashes():
    actor = {**ACTOR, "description": "The lab’s team – precision irrigation, groundwater monitoring."}
    client = FixtureToolClient({"sectors": ["WATER"], "confidence": "medium",
                                "evidence_quote": "lab's team - precision irrigation, groundwater"})
    assert classify_from_description(client, actor, SECTORS)["links"][0]["sector"] == "WATER"


@pytest.mark.parametrize("payload, why", [
    ({"sectors": ["WATER"], "confidence": "low", "evidence_quote": "precision irrigation"}, "plainly"),
    ({"sectors": [], "confidence": "high", "evidence_quote": "precision irrigation"}, "plainly"),
    ({"sectors": ["WATER"], "confidence": "high", "evidence_quote": "world-leading water company"},
     "quote"),
    ({"sectors": ["MINING"], "confidence": "high", "evidence_quote": "precision irrigation"}, "plainly"),
    ({"sectors": ["WATER"], "confidence": "high", "evidence_quote": "Plains Irrigation Lab"}, "quote"),
])
def test_a_weak_unquoted_or_unknown_answer_leaves_it_unlinked(payload, why):
    result = classify_from_description(FixtureToolClient(payload), ACTOR, SECTORS)
    assert result["links"] == [] and why in result["unclear"]


URL = os.environ.get("V2_TEST_DATABASE_URL", "")


@pytest.mark.skipif(not URL or "127.0.0.1:55432" not in URL, reason="V2_TEST_DATABASE_URL is required")
def test_the_writer_adds_a_link_never_changes_one_and_keeps_an_existing_primary():
    from agents.common.provenance import insert_source
    from agents.enrichment.decisions import link_actor_sector

    engine = create_engine(URL)
    with engine.connect() as conn:
        outer = conn.begin()
        try:
            session = Session(bind=conn, join_transaction_mode="create_savepoint")
            actor = session.execute(text(
                "SELECT actor_id::text FROM actor a WHERE NOT EXISTS (SELECT 1 FROM actor_sector s "
                "WHERE s.actor_id=a.actor_id) LIMIT 1")).scalar()
            codes = session.execute(text(
                "SELECT code FROM sector WHERE active ORDER BY code LIMIT 2")).scalars().all()
            if not actor or len(codes) < 2:
                pytest.skip("needs an actor with no sector and two sectors")
            source = insert_source(session, source_url="urn:test:phase1", fetched_at=None,
                                   description="test", source_type="system", trust_tier="derived")
            with pytest.raises(ValueError, match="reason"):
                link_actor_sector(session, actor_id=actor, sector_code=codes[0], source_id=source,
                                  reason=" ", live=True)
            with pytest.raises(ValueError, match="no active sector"):
                link_actor_sector(session, actor_id=actor, sector_code="NOPE", source_id=source,
                                  reason="r", live=True)
            dry = link_actor_sector(session, actor_id=actor, sector_code=codes[0],
                                    source_id=None, reason="r", primary=True)
            assert dry == {"action": "would_link", "sector": codes[0], "primary": True}
            assert session.execute(text("SELECT count(*) FROM actor_sector WHERE "
                                        "actor_id=CAST(:a AS uuid)"), {"a": actor}).scalar() == 0
            first = link_actor_sector(session, actor_id=actor, sector_code=codes[0],
                                      source_id=source, reason="r", primary=True, live=True)
            assert first["action"] == "linked" and first["primary"] is True
            again = link_actor_sector(session, actor_id=actor, sector_code=codes[0],
                                      source_id=source, reason="other", primary=False, live=True)
            assert again["action"] == "already_linked"
            second = link_actor_sector(session, actor_id=actor, sector_code=codes[1],
                                       source_id=source, reason="r", primary=True, live=True)
            assert second["primary"] is False
            rows = session.execute(text(
                "SELECT s.code, a.is_primary, a.match_reason FROM actor_sector a JOIN sector s "
                "USING(sector_id) WHERE a.actor_id=CAST(:a AS uuid) ORDER BY s.code"),
                {"a": actor}).all()
            assert [(r[0], r[1], r[2]) for r in rows] == [(codes[0], True, "r"), (codes[1], False, "r")]
            session.close()
        finally:
            outer.rollback()
    engine.dispose()


def test_a_quote_that_is_only_the_name_is_not_evidence():
    actor = {**ACTOR, "name": "Berkeley Water Center", "description": "Berkeley Water Center. A campus unit."}
    client = FixtureToolClient({"sectors": ["WATER"], "confidence": "high",
                                "evidence_quote": "Berkeley Water Center"})
    result = classify_from_description(client, actor, SECTORS)
    assert result["links"] == [] and "name" in result["unclear"]


def test_a_quote_joined_from_two_phrases_counts_but_an_invented_join_does_not():
    from agents.enrichment.phase1_sectors import quote_in
    desc = ("Arca is a company developing mineral carbonation processes that store CO2 by reacting "
            "it with residues (e.g., slag), producing stable carbonate minerals.")
    assert quote_in("company developing mineral carbonation processes that store CO2, "
                    "producing stable carbonate minerals", desc)
    assert not quote_in("mineral carbonation processes and green hydrogen", desc)
    assert not quote_in("CO2", desc)
