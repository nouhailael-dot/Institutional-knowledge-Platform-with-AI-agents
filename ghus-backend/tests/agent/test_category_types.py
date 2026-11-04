"""Category Types for untyped organizations: from their own category's list, empty when unsure."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from agents.common.actor_classification import load_category_catalog
from agents.common.llm import FixtureToolClient
from agents.enrichment.category_types import classify, what_it_does

CATALOG = load_category_catalog()
ACTOR = {"actor_id": "a", "name": "Texas A&M Department of Soil & Crop Sciences",
         "actor_category": "university_academic",
         "about": "Details should be verified from primary sources."}


def test_the_placeholder_is_never_given_as_what_it_does():
    assert what_it_does(ACTOR["about"]) == ""
    assert what_it_does("Researches soil fertility.") == "Researches soil fertility."


def test_a_confident_type_from_the_list_is_planned_and_a_doubtful_one_left_empty():
    confident = FixtureToolClient({"category_type": "academic_department", "category_note": None,
                                   "doubt": False, "main_job_evidence": "A university department."})
    assert classify(confident, ACTOR, CATALOG) == {"category_type": "academic_department"}
    doubtful = FixtureToolClient({"category_type": "academic_department", "category_note": "unsure",
                                  "doubt": True, "main_job_evidence": "A university department."})
    assert "unclear" in classify(doubtful, ACTOR, CATALOG)
    catch_all = FixtureToolClient({"category_type": "not_applicable", "category_note": "none fits",
                                   "main_job_evidence": "A university department."})
    assert "unclear" in classify(catch_all, ACTOR, CATALOG)


URL = os.environ.get("V2_TEST_DATABASE_URL", "")


@pytest.mark.skipif(not URL or "127.0.0.1:55432" not in URL, reason="V2_TEST_DATABASE_URL is required")
def test_the_writer_fills_an_empty_type_only_and_never_a_catch_all():
    from agents.enrichment.decisions import fill_category_type

    engine = create_engine(URL)
    with engine.connect() as conn:
        outer = conn.begin()
        try:
            session = Session(bind=conn, join_transaction_mode="create_savepoint")
            row = session.execute(text(
                "SELECT actor_id::text, actor_category FROM actor WHERE actor_category="
                "'university_academic' AND (category_type IS NULL OR category_type='') LIMIT 1")).first()
            if row is None:
                pytest.skip("needs an untyped university actor")
            with pytest.raises(ValueError):
                fill_category_type(session, actor_id=row[0], actor_category=row[1],
                                   category_type="not_applicable", live=True)
            with pytest.raises(ValueError):
                fill_category_type(session, actor_id=row[0], actor_category=row[1],
                                   category_type="public_utility", live=True)
            assert fill_category_type(session, actor_id=row[0], actor_category=row[1],
                                      category_type="academic_department")["action"] == "would_fill"
            assert fill_category_type(session, actor_id=row[0], actor_category=row[1],
                                      category_type="academic_department", live=True)["action"] == "filled"
            assert fill_category_type(session, actor_id=row[0], actor_category=row[1],
                                      category_type="research_lab_center", live=True)["action"] == "already_typed"
            assert fill_category_type(session, actor_id=row[0], actor_category="company",
                                      category_type="private_company", live=True)["action"] == "category_changed"
            session.close()
        finally:
            outer.rollback()
    engine.dispose()
