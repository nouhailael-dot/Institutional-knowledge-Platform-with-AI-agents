from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

from agents.common.resolve_route import route_actor
from agents.discovery.promote import (
    ACTOR_MAPPING_STEPS,
    DISCOVERED_DOMAIN_PAYLOAD_KEY,
    map_new_actor,
    promote,
)
from agents.discovery.stage import StagedRecord

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Resolver:
    HIGH = 0.96
    LOW = 0.18
    model_name = "frozen_combiner_review_only"

    def __init__(self, score: float | None = None):
        self.score = score
        self.candidate_calls = 0

    def _candidates(self, name):
        self.candidate_calls += 1
        if self.score is None:
            return pd.DataFrame(columns=["actor_id", "name"])
        return pd.DataFrame([{"actor_id": "close-1", "name": "Example Climate Labs"}])

    def _score(self, record, candidates):
        scored = candidates.copy()
        scored["score"] = self.score
        return scored


def actor_record(**overrides):
    return {
        "name": "Example Climate Lab",
        "website": "https://example.org/about",
        **overrides,
    }


def mapped(**overrides):
    return {
        "actor_id": "actor-1",
        "name": "Example Climate Lab",
        "alternate_names": [],
        "website": "https://example.org",
        "website_domain": "example.org",
        "record_status": "imported",
        **overrides,
    }


@pytest.mark.parametrize(
    ("record", "candidate", "rule"),
    [
        (actor_record(name="Different Public Name"), mapped(), "website_domain"),
        (actor_record(website="https://other.org"), mapped(), "name_or_alternate_name"),
        (
            actor_record(name="ECL", website="https://other.org"),
            mapped(alternate_names=["ECL"]),
            "name_or_alternate_name",
        ),
    ],
)
def test_exact_domain_name_or_alt_name_appends_existing_without_model(record, candidate, rule):
    resolver = Resolver(score=0.99)
    decision = route_actor(record, resolver, [candidate])

    assert decision.zone == "absorb"
    assert decision.target_entity_id == "actor-1"
    assert decision.metadata["match_rule"] == rule
    assert resolver.candidate_calls == 0


def test_rejected_exact_match_remains_the_append_target():
    decision = route_actor(
        actor_record(),
        Resolver(score=0.99),
        [mapped(record_status="rejected")],
    )

    assert decision.zone == "absorb"
    assert decision.metadata["matched_record_status"] == "rejected"


def test_non_exact_high_score_is_possible_duplicate_and_never_absorbed():
    decision = route_actor(
        actor_record(website="https://different.example"),
        Resolver(score=0.999),
        [mapped(name="Other Lab", website_domain="other.example")],
    )

    assert decision.zone == "review"
    assert decision.metadata["review_kind"] == "possible_duplicate"


def test_discovered_domain_exact_match_still_appends_existing_actor():
    record = actor_record(**{DISCOVERED_DOMAIN_PAYLOAD_KEY: "events.example"})
    staged = StagedRecord(
        run_id="00000000-0000-0000-0000-000000000001",
        raw_document_id=None,
        entity_type="actor",
        natural_key="example-climate-lab",
        source_url="https://events.example/conference",
        payload={},
        normalized_payload=record,
        prompt_version="event_participant_v2",
        extracted_at="2026-09-28T00:00:00+00:00",
    )

    result = promote(staged, route_actor(record, Resolver(), [mapped()]))

    assert result.action == "would_absorb"
    assert result.entity_id == "actor-1"


def test_sessionless_dry_run_preserves_the_strict_creation_order():
    staged = StagedRecord(
        run_id="00000000-0000-0000-0000-000000000001",
        raw_document_id=None,
        entity_type="actor",
        natural_key="example-climate-lab",
        source_url="https://example.org",
        payload={},
        normalized_payload=actor_record(),
        prompt_version="actor_v2",
        extracted_at="2026-09-25T00:00:00+00:00",
    )

    result = map_new_actor(staged, route_actor(actor_record(), Resolver(), []))

    assert result.dry_run is True
    assert result.action == "would_create"
    assert result.step_trace == list(ACTOR_MAPPING_STEPS)


def test_no_canonical_delete_path_exists_in_application_python():
    roots = [PROJECT_ROOT / "agents", PROJECT_ROOT / "scripts", PROJECT_ROOT / "src"]
    pattern = re.compile(
        r"delete\s+from\s+(actor|event|person|hub|hub_actor|actor_person|"
        r"organization_hierarchy|actor_fact|actor_topic|actor_location|entity_edge)\b",
        re.IGNORECASE,
    )
    violations = []
    for root in roots:
        for path in root.rglob("*.py"):
            if "diagnostics" in path.parts:
                continue
            if pattern.search(path.read_text(encoding="utf-8")):
                violations.append(path.relative_to(PROJECT_ROOT).as_posix())
    assert violations == []


def test_canonical_sql_writers_are_allowlisted():
    allowed = {
        "agents/discovery/promote.py",
        "agents/enrichment/decisions.py",
    }
    pattern = re.compile(
        r"(?:insert\s+into|update)\s+(actor|event|person|hub|hub_actor|actor_person|"
        r"organization_hierarchy|actor_fact|actor_topic|actor_location|entity_edge)\b",
        re.IGNORECASE,
    )
    violations = []
    for root_name in ("agents", "scripts", "src"):
        for path in (PROJECT_ROOT / root_name).rglob("*.py"):
            relative = path.relative_to(PROJECT_ROOT).as_posix()
            if relative in allowed or "diagnostics" in path.parts:
                continue
            if pattern.search(path.read_text(encoding="utf-8")):
                violations.append(relative)
    assert violations == []
