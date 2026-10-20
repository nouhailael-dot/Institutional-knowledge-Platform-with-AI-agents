from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from agents.collection.light_pull import (
    CATEGORY_LIGHT_FIELDS,
    COMMON_LIGHT_FIELDS,
    MAX_LIGHT_PULL_FETCHES,
    light_schema,
    run_light_pull,
)

NOW = datetime(2026, 10, 5, tzinfo=UTC)
TOPIC_ID = str(uuid.uuid4())


def _payload(**overrides):
    value = {
        "name": "Evidence Systems",
        "website": "https://evidence.example.org",
        "description": "Builds evidence systems for the mapped topic.",
        "category_type": "private_company",
        "country": "United States",
        "location_city": "Boston",
        "match_strength": "strong",
        "match_reason": "The official page documents topic-specific work.",
    }
    value.update(overrides)
    return value


def test_all_12_categories_have_common_plus_category_specific_light_schema():
    assert len(CATEGORY_LIGHT_FIELDS) == 12
    for category, category_fields in CATEGORY_LIGHT_FIELDS.items():
        schema = light_schema(category)
        assert schema[: len(COMMON_LIGHT_FIELDS)] == COMMON_LIGHT_FIELDS
        assert schema[len(COMMON_LIGHT_FIELDS):] == category_fields
        assert len(schema) == len(set(schema))


def test_light_pull_is_topic_scoped_provenanced_and_explicit_about_missing_evidence():
    result = run_light_pull(
        payload=_payload(), actor_category="company", topic_id=TOPIC_ID,
        source_url="https://evidence.example.org/about", date_read=NOW,
    )
    assert result.topic_id == TOPIC_ID
    assert tuple(fact.field_key for fact in result.facts) == result.schema_fields
    assert all(fact.source_url == "https://evidence.example.org/about" for fact in result.facts)
    assert all(fact.date_read == NOW for fact in result.facts)
    facts = {fact.field_key: fact for fact in result.facts}
    assert facts["description"].collection_state == "found"
    assert (facts["funding_signal"].collection_state, facts["funding_signal"].value) == (
        "not_found", None,
    )


def test_orchestrator_fetches_at_most_three_distinct_pages_and_restricts_extractor_schema():
    calls = []

    def fetch(url):
        calls.append(url)
        return SimpleNamespace(url=url, text=f"document for {url}")

    def extract(documents, schema, topic_id):
        assert len(documents) == MAX_LIGHT_PULL_FETCHES
        assert topic_id == TOPIC_ID
        assert "topic_research_focus" in schema
        return {"topic_research_focus": {
            "collection_state": "found",
            "value": "Documented battery recycling research.",
            "source_url": documents[0].url,
            "date_read": documents[0].date_read,
            "confidence": "high",
        }}

    urls = [f"https://evidence.example.org/{index}" for index in range(5)]
    result = run_light_pull(
        payload=_payload(light_pull_urls=[*urls, urls[0]]),
        actor_category="research_center", topic_id=TOPIC_ID,
        source_url="https://evidence.example.org", date_read=NOW,
        fetcher=fetch, extractor=extract,
    )
    assert calls == urls[:3]
    assert result.fetched_urls == tuple(urls[:3])
    assert next(f for f in result.facts if f.field_key == "topic_research_focus").confidence == "high"

    with pytest.raises(ValueError, match="outside its schema"):
        run_light_pull(
            payload=_payload(light_pull_documents=[{
                "url": urls[0], "text": "read", "date_read": NOW,
            }]),
            actor_category="research_center", topic_id=TOPIC_ID,
            source_url=urls[0], date_read=NOW,
            extractor=lambda *_args: {"rankings": {"value": "invented"}},
        )


def test_rankings_are_university_only_and_require_attribution():
    valid_ranking = [{
        "publisher": "QS",
        "ranking_name": "World University Rankings by Subject",
        "year": 2026,
        "ranked_entity": "Example University",
        "position": "#14",
        "subject": "Agriculture & Forestry",
    }]
    result = run_light_pull(
        payload=_payload(
            category_type="university_system",
            light_pull_evidence={"rankings": {
                "collection_state": "found", "value": valid_ranking,
            }},
        ),
        actor_category="university_academic", topic_id=TOPIC_ID,
        source_url="https://university.example.org/rankings", date_read=NOW,
    )
    assert next(f for f in result.facts if f.field_key == "rankings").value == valid_ranking

    invalid = [{**valid_ranking[0], "publisher": "Unverified Blog"}]
    with pytest.raises(ValueError, match="publisher"):
        run_light_pull(
            payload=_payload(
                category_type="university_system",
                light_pull_evidence={"rankings": {
                    "collection_state": "found", "value": invalid,
                }},
            ),
            actor_category="university_academic", topic_id=TOPIC_ID,
            source_url="https://university.example.org/rankings", date_read=NOW,
        )


def test_startup_stage_or_trl_is_never_inferred_without_published_evidence():
    result = run_light_pull(
        payload=_payload(category_type="independent_startup"),
        actor_category="startup", topic_id=TOPIC_ID,
        source_url="https://startup.example.org", date_read=NOW,
    )
    stage = next(f for f in result.facts if f.field_key == "published_stage_or_trl")
    assert (stage.collection_state, stage.value) == ("not_found", None)

    with pytest.raises(ValueError, match="published evidence"):
        run_light_pull(
            payload=_payload(
                category_type="independent_startup",
                light_pull_evidence={"published_stage_or_trl": {
                    "collection_state": "found", "value": {"trl": 7},
                }},
            ),
            actor_category="startup", topic_id=TOPIC_ID,
            source_url="https://startup.example.org", date_read=NOW,
        )


def test_explicit_not_yet_collected_is_preserved_and_people_remain_disabled():
    result = run_light_pull(
        payload=_payload(light_pull_evidence={"funding_signal": {
            "collection_state": "not_yet_collected", "value": None,
        }}),
        actor_category="company", topic_id=TOPIC_ID,
        source_url="https://evidence.example.org", date_read=NOW,
    )
    funding = next(f for f in result.facts if f.field_key == "funding_signal")
    assert funding.collection_state == "not_yet_collected"
    assert all("person" not in field and "people" not in field for field in result.schema_fields)


def test_default_planning_is_deterministic_for_dry_run_live_parity():
    arguments = {
        "payload": _payload(),
        "actor_category": "company",
        "topic_id": TOPIC_ID,
        "source_url": "https://evidence.example.org",
        "date_read": NOW,
    }
    assert run_light_pull(**arguments) == run_light_pull(**arguments)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"description": "One. Two. Three. Four."}, "1 to 3"),
        ({"match_strength": "weak"}, "strong or moderate"),
        ({"match_reason": "One. Two. Three."}, "1 to 2"),
        ({"recent_activity": "Undated claim"}, "date and description"),
    ],
)
def test_common_light_fields_enforce_bounded_factual_shapes(overrides, message):
    with pytest.raises(ValueError, match=message):
        run_light_pull(
            payload=_payload(**overrides), actor_category="company", topic_id=TOPIC_ID,
            source_url="https://evidence.example.org", date_read=NOW,
        )


def test_academic_unit_never_inherits_university_wide_ranking():
    ranking = [{
        "publisher": "QS", "ranking_name": "World University Rankings", "year": 2026,
        "ranked_entity": "Example University", "position": "#14",
    }]
    with pytest.raises(ValueError, match="never inherit"):
        run_light_pull(
            payload=_payload(
                category_type="academic_department",
                light_pull_evidence={"rankings": {
                    "collection_state": "found", "value": ranking,
                }},
            ),
            actor_category="university_academic", topic_id=TOPIC_ID,
            source_url="https://university.example.org", date_read=NOW,
        )
