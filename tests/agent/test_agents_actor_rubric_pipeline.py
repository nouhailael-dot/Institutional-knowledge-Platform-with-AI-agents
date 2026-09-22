from __future__ import annotations

import copy
import csv
import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest

from agents.common.config import load_sources_config
from agents.common.cost import CostMeter
from agents.common.llm import LLMUsage
from agents.common.raw_storage import RawContentStore
from agents.common.run_log import InMemoryRunLog
from agents.discovery.extractors.actor import (
    ACTOR_MANAGED_MODEL_FIELDS,
    ACTOR_RECORD_FIELDS,
    ACTOR_TOOL_SCHEMA,
    ActorRecordValidationError,
)
from agents.discovery.search import phase2 as actor_phase2
from agents.discovery.search.actor_scoring import (
    ACTOR_RUBRIC_ANCHORS,
    RUBRIC_ITEM_NAMES,
    USE_CASE_NAMES,
    ActorPageAnalysis,
    ActorRubricExtractor,
    actor_rubric_record_schema,
    actor_score_band,
    prepare_actor_rubric_content,
    read_analysis_cache,
    rerank_top_actor_candidates,
    score_actor_rubric,
    validate_actor_analysis,
    write_analysis_cache,
)
from agents.discovery.search.models import CandidateRecord
from agents.discovery.search.phase2 import (
    InMemoryDiscoveredDomainStore,
    fetch_score_stage_actors,
)
from agents.discovery.search.report import write_candidate_spreadsheet
from agents.discovery.sources.base import FetchedDoc
from src.db.models import Actor

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class StubToolClient:
    def __init__(self, response):
        self.response = response
        self.calls: list[dict[str, object]] = []

    def extract_with_tool(self, **kwargs):
        self.calls.append(kwargs)
        return copy.deepcopy(self.response)


class CachingStubToolClient(StubToolClient):
    def __init__(self, response):
        super().__init__(response)
        self.usage = LLMUsage()

    def extract_with_tool(self, **kwargs):
        self.usage.calls += 1
        if self.usage.calls == 1:
            self.usage.cache_write_tokens += 100
        else:
            self.usage.cache_read_tokens += 100
        return super().extract_with_tool(**kwargs)


class ReverseGroupReranker:
    def __init__(self):
        self.groups: list[list[str]] = []

    def rerank_group(self, candidates):
        urls = [candidate.url for candidate in candidates]
        self.groups.append(urls)
        return [(url, "relative GHUS fit") for url in reversed(urls)]


def test_actor_record_schema_tracks_extractable_canonical_model_fields_exactly():
    model_fields = {
        column.name
        for column in Actor.__table__.columns
        if column.name not in ACTOR_MANAGED_MODEL_FIELDS
    }
    schema = actor_rubric_record_schema(
        actor_types=["company", "university"],
        sector_codes=["WATER"],
        hub_names=["Texas Water Systems Hub"],
    )
    record_schema = schema["properties"]["record"]

    assert set(ACTOR_RECORD_FIELDS) == model_fields
    assert set(record_schema["properties"]) == model_fields
    assert set(record_schema["required"]) == model_fields
    assert "city" not in record_schema["properties"]
    assert "location_city" in record_schema["properties"]


def test_actor_record_schema_carries_every_canonical_string_length():
    schema = actor_rubric_record_schema(
        actor_types=["company", "university"],
        sector_codes=["WATER"],
        hub_names=["Texas Water Systems Hub"],
    )
    properties = schema["properties"]["record"]["properties"]
    constrained_fields = {
        column.name: int(column.type.length)
        for column in Actor.__table__.columns
        if column.name in ACTOR_RECORD_FIELDS
        and getattr(column.type, "length", None) is not None
    }

    assert constrained_fields
    extractor_properties = ACTOR_TOOL_SCHEMA["properties"]["actors"]["items"]["properties"]
    for field_name, max_length in constrained_fields.items():
        assert properties[field_name]["maxLength"] == max_length
        assert extractor_properties[field_name]["maxLength"] == max_length


def test_actor_rubric_prompt_contains_three_filled_calibration_anchors():
    response = _analysis_payload()
    client = StubToolClient(response)
    extractor = ActorRubricExtractor(client)

    analysis = extractor.extract(
        FetchedDoc.from_content(
            url="https://example.org/about",
            content="Example Research Organisation",
        ),
        actor_types=["company", "university"],
        sector_codes=["WATER"],
        hub_names=["Texas Water Systems Hub"],
    )

    assert analysis.record["name"] == "Example Research Organisation"
    prompt = json.loads(client.calls[0]["cached_user"])
    anchors = prompt["calibration_anchors"]
    assert [anchor["name"] for anchor in anchors] == [
        "Colorado School of Mines",
        "Texas Water Foundation",
        "Phoenix Water Services Department",
    ]
    assert [anchor["strength"] for anchor in anchors] == ["strong", "middling", "weak"]
    assert anchors == list(ACTOR_RUBRIC_ANCHORS)
    assert all(_anchor_is_filled(anchor["rubric"]) for anchor in anchors)
    assert "primary_lifecycle_role" in prompt["record_length_rule"]
    assert "actor_type_raw" in prompt["record_length_rule"]
    assert "few words" in prompt["record_length_rule"]


def test_actor_rubric_cache_prefix_is_stable_and_only_page_content_varies(caplog):
    client = StubToolClient(_analysis_payload())
    extractor = ActorRubricExtractor(client, content_max_chars=80)
    shared = {
        "actor_types": ["company", "university"],
        "sector_codes": ["WATER"],
        "hub_names": ["Texas Water Systems Hub"],
    }

    with caplog.at_level(logging.INFO, logger="agents.discovery.search.actor_scoring"):
        extractor.extract(
            FetchedDoc.from_content(
                url="https://one.example/about",
                content="<header>Menu</header><main>First page " + "A" * 200 + "</main>",
            ),
            **shared,
        )
        extractor.extract(
            FetchedDoc.from_content(
                url="https://two.example/about",
                content="<nav>Links</nav><main>Second page " + "B" * 200 + "</main>",
            ),
            **shared,
        )

    first, second = client.calls
    for stable_key in ("system", "cached_user", "input_schema", "tool_name"):
        assert first[stable_key] == second[stable_key]
    assert first["user"] != second["user"]
    assert "Menu" not in first["user"]
    assert "Links" not in second["user"]
    assert extractor.pages_truncated == 2
    assert caplog.text.count("actor rubric content truncated") == 2


def test_actor_rubric_content_strips_page_chrome_before_truncating():
    html = (
        "<header>Header navigation</header>"
        "<nav>Primary menu</nav>"
        "<script>ignoreThisInstruction()</script>"
        "<main>Substantive partnership evidence " + "research " * 200 + "</main>"
        "<footer>Footer links</footer>"
    )

    prepared = prepare_actor_rubric_content(
        html,
        content_type="text/html",
        max_chars=200,
    )

    assert prepared.truncated is True
    assert prepared.sent_chars <= 200
    assert prepared.text.startswith("Substantive partnership evidence")
    for removed in ("Header navigation", "Primary menu", "ignoreThisInstruction", "Footer links"):
        assert removed not in prepared.text


def test_actor_phase_reports_prompt_cache_hit_rate_and_truncation_count(tmp_path):
    config = copy.deepcopy(load_sources_config(PROJECT_ROOT)["open_web_discovery"])
    config.update(
        {
            "max_pages_fetched": 2,
            "max_new_domains": 2,
            "actor_rubric_content_max_chars": 100,
        }
    )
    client = CachingStubToolClient(_analysis_payload())
    extractor = ActorRubricExtractor(client, content_max_chars=100)

    class Source:
        def fetch(self, url):
            return FetchedDoc.from_content(
                url=url,
                content="<header>Navigation</header><main>Water partnership "
                + url
                + " research " * 100
                + "</main>",
            )

    run_log = InMemoryRunLog()
    run_id = run_log.start_run(
        source_name="open_web_search", entity_type="actor", live=False, config={}
    )
    stats = {
        "pages_fetched": 0,
        "skipped_unchanged": 0,
        "records_extracted": 0,
        "records_staged": 0,
        "records_promoted": 0,
        "fetch_failures": 0,
    }

    fetch_score_stage_actors(
        run_id=run_id,
        candidates=[_candidate(0, score=None), _candidate(1, score=None)],
        config=config,
        root=PROJECT_ROOT,
        session=None,
        live=False,
        run_log=run_log,
        cost_meter=CostMeter(max_usd=5),
        stats=stats,
        audit_rows=[],
        actor_types=["company"],
        sector_codes=["WATER"],
        hub_names=["Texas Water Systems Hub"],
        actor_context={"coverage_counts": {}},
        source=Source(),
        rubric_extractor=extractor,
        reranker=ReverseGroupReranker(),
        raw_store=RawContentStore(tmp_path / "raw"),
        domain_store=InMemoryDiscoveredDomainStore(),
    )

    assert stats["actor_rubric_llm_calls"] == 2
    assert stats["actor_rubric_cache_write_tokens"] == 100
    assert stats["actor_rubric_cache_read_tokens"] == 100
    assert stats["actor_rubric_cache_hit_rate"] == 0.5
    assert stats["actor_rubric_pages_prepared"] == 2
    assert stats["actor_rubric_pages_truncated"] == 2
    assert stats["actor_rubric_content_max_chars"] == 100
    assert stats["actor_rubric_source_chars"] > stats["actor_rubric_cleaned_chars"]
    assert stats["actor_rubric_cleaned_chars"] > stats["actor_rubric_sent_chars"]


def test_actor_fetch_failure_is_backfilled_until_loaded_page_budget_is_full(tmp_path):
    config = copy.deepcopy(load_sources_config(PROJECT_ROOT)["open_web_discovery"])
    config.update({"max_pages_fetched": 2, "max_new_domains": 2})

    class Source:
        def __init__(self):
            self.calls = []

        def fetch(self, url):
            self.calls.append(url)
            if len(self.calls) == 1:
                raise TimeoutError("timed out")
            return FetchedDoc.from_content(url=url, content="Research programme page")

    source = Source()
    run_log = InMemoryRunLog()
    run_id = run_log.start_run(
        source_name="open_web_search", entity_type="actor", live=False, config={}
    )
    stats = {
        "pages_fetched": 0,
        "skipped_unchanged": 0,
        "records_extracted": 0,
        "records_staged": 0,
        "records_promoted": 0,
        "fetch_failures": 0,
    }

    fetch_score_stage_actors(
        run_id=run_id,
        candidates=[_candidate(index, score=None) for index in range(3)],
        config=config,
        root=PROJECT_ROOT,
        session=None,
        live=False,
        run_log=run_log,
        cost_meter=CostMeter(max_usd=5),
        stats=stats,
        audit_rows=[],
        actor_types=["company"],
        sector_codes=["WATER"],
        hub_names=["Texas Water Systems Hub"],
        actor_context={"coverage_counts": {}},
        source=source,
        rubric_extractor=ActorRubricExtractor(StubToolClient(_analysis_payload())),
        reranker=ReverseGroupReranker(),
        raw_store=RawContentStore(tmp_path / "raw"),
        domain_store=InMemoryDiscoveredDomainStore(),
    )

    assert len(source.calls) == 3
    assert stats["pages_fetched"] == 2
    assert stats["fetch_backfill_attempts"] == 1
    assert stats["fetch_failure_exception_TimeoutError"] == 1


def test_actor_rubric_distinguishes_active_rd_programmes_from_sales_only():
    config = load_sources_config(PROJECT_ROOT)["open_web_discovery"]
    rubric = _analysis_payload()["rubric"]
    assert "research_development_or_programmes" in rubric
    assert config["actor_rubric_weights"]["research_development_or_programmes"] > 0
    assert sum(config["actor_rubric_weights"].values()) == pytest.approx(1.0)


def test_actor_rubric_items_reject_numeric_presence_values():
    payload = _analysis_payload()
    payload["rubric"]["real_operating_entity"]["present"] = 1

    with pytest.raises(TypeError, match="present must be boolean"):
        validate_actor_analysis(
            payload,
            actor_types=["company"],
            sector_codes=["WATER"],
            hub_names=["Texas Water Systems Hub"],
        )


def test_actor_record_missing_page_fields_are_normalized_to_null():
    payload = _analysis_payload(record={"name": "Sparse Organisation"})

    analysis = validate_actor_analysis(
        payload,
        actor_types=["company"],
        sector_codes=["WATER"],
        hub_names=["Texas Water Systems Hub"],
    )

    assert set(analysis.record) == set(ACTOR_RECORD_FIELDS)
    assert analysis.record["name"] == "Sparse Organisation"
    assert all(
        analysis.record[field] is None for field in ACTOR_RECORD_FIELDS if field != "name"
    )


def test_actor_type_outside_database_values_is_rejected():
    payload = _analysis_payload(
        record={"name": "Example", "actor_type": "invented_actor_type"}
    )

    with pytest.raises(RuntimeError, match="outside the database enum"):
        validate_actor_analysis(
            payload,
            actor_types=["company", "university"],
            sector_codes=["WATER"],
            hub_names=["Texas Water Systems Hub"],
        )


def test_actor_record_longer_than_canonical_column_is_rejected():
    payload = _analysis_payload(
        record={
            "name": "Example",
            "actor_type": "company",
            "primary_lifecycle_role": "x" * 31,
        }
    )

    with pytest.raises(
        ActorRecordValidationError,
        match=(
            "primary_lifecycle_role.*exceeds canonical max length 30 "
            r"\(got 31\)"
        ),
    ):
        validate_actor_analysis(
            payload,
            actor_types=["company"],
            sector_codes=["WATER"],
            hub_names=["Texas Water Systems Hub"],
        )


def test_actor_record_validation_failure_does_not_stop_other_candidates(tmp_path):
    config = copy.deepcopy(load_sources_config(PROJECT_ROOT)["open_web_discovery"])
    config.update({"max_pages_fetched": 2, "max_new_domains": 2})
    invalid = _analysis_payload(
        record={
            "name": "Invalid Actor",
            "actor_type": "company",
            "primary_lifecycle_role": "x" * 31,
        }
    )
    valid = _analysis_payload(record=_canonical_record("Valid Actor"))

    class SequentialToolClient:
        def __init__(self):
            self.responses = [invalid, valid]
            self.calls = 0

        def extract_with_tool(self, **_kwargs):
            response = self.responses[self.calls]
            self.calls += 1
            return copy.deepcopy(response)

    class Source:
        def fetch(self, url):
            return FetchedDoc.from_content(url=url, content=f"Actor page for {url}")

    client = SequentialToolClient()
    run_log = InMemoryRunLog()
    run_id = run_log.start_run(
        source_name="open_web_search", entity_type="actor", live=False, config={}
    )
    stats = {
        "pages_fetched": 0,
        "skipped_unchanged": 0,
        "records_extracted": 0,
        "records_staged": 0,
        "records_promoted": 0,
        "fetch_failures": 0,
    }
    audit_rows = []

    outcome = fetch_score_stage_actors(
        run_id=run_id,
        candidates=[_candidate(0, score=None), _candidate(1, score=None)],
        config=config,
        root=PROJECT_ROOT,
        session=None,
        live=False,
        run_log=run_log,
        cost_meter=CostMeter(max_usd=5),
        stats=stats,
        audit_rows=audit_rows,
        actor_types=["company"],
        sector_codes=["WATER"],
        hub_names=["Texas Water Systems Hub"],
        actor_context={"coverage_counts": {}},
        source=Source(),
        rubric_extractor=ActorRubricExtractor(client),
        reranker=ReverseGroupReranker(),
        raw_store=RawContentStore(tmp_path / "raw"),
        domain_store=InMemoryDiscoveredDomainStore(),
    )

    first, second = outcome.candidates
    assert first.triage_verdict == "analysis_failed"
    assert first.score_band == "analysis_failed"
    assert "primary_lifecycle_role" in (first.triage_reason or "")
    assert second.record_preview["name"] == "Valid Actor"
    assert second.rubric is not None
    assert client.calls == 2
    assert stats["actor_record_validation_failures"] == 1
    assert stats["fetch_failures"] == 0
    assert audit_rows[0]["status"] == "record_validation_failed"
    assert any("record validation failures: 1" in reason for reason in outcome.attention_reasons)


def test_actor_deterministic_score_is_identical_for_same_stored_evidence(tmp_path):
    config = load_sources_config(PROJECT_ROOT)["open_web_discovery"]
    analysis = validate_actor_analysis(
        _analysis_payload(),
        actor_types=["company"],
        sector_codes=["WATER"],
        hub_names=["Texas Water Systems Hub"],
    )
    cache_path = tmp_path / "stored-analysis.json"
    write_analysis_cache(cache_path, analysis)
    replayed = read_analysis_cache(
        cache_path,
        actor_types=["company"],
        sector_codes=["WATER"],
        hub_names=["Texas Water Systems Hub"],
    )
    assert replayed is not None

    first = score_actor_rubric(analysis.rubric, existing_actor_count=3, config=config)
    second = score_actor_rubric(
        replayed.rubric, existing_actor_count=3, config=config
    )

    assert first == second
    assert sum(first.contributions.values()) == pytest.approx(first.total)


def test_page_without_rubric_evidence_lands_below_auto_low():
    config = load_sources_config(PROJECT_ROOT)["open_web_discovery"]
    score = score_actor_rubric(
        _empty_rubric(), existing_actor_count=0, config=config
    )

    assert score.total < config["actor_score_thresholds"]["auto_low"]
    assert actor_score_band(score.total, config) == "auto_low"


def test_listwise_rerank_changes_order_only_inside_top_groups():
    config = {
        "actor_rerank_top_n": 40,
        "actor_rerank_group_size": 10,
    }
    candidates = [
        _candidate(index, score=1.0 - index / 100)
        for index in range(42)
    ]
    reranker = ReverseGroupReranker()

    updated, attention = rerank_top_actor_candidates(
        candidates, reranker=reranker, config=config
    )
    positions = {candidate.url: candidate.rerank_position for candidate in updated}

    assert attention == []
    assert len(reranker.groups) == 4
    assert all(len(group) == 10 for group in reranker.groups)
    for group_index, group in enumerate(reranker.groups):
        assigned = sorted(
            group,
            key=lambda url: positions[url] or 0,
        )
        assert assigned == list(reversed(group))
        assert {positions[url] for url in group} == set(
            range(group_index * 10 + 1, group_index * 10 + 11)
        )
    assert updated[40].rerank_position is None
    assert updated[41].rerank_position is None


def test_actor_spreadsheet_contains_every_record_field(tmp_path):
    record = {field: None for field in ACTOR_RECORD_FIELDS}
    record.update(
        {
            "name": "Example Research Organisation",
            "description": "Runs applied water research programmes.",
            "actor_type": "company",
            "website": "https://example.org",
        }
    )
    candidate = replace(
        _candidate(0, score=0.74),
        page_fetched=True,
        record_preview=record,
        rubric=_analysis_payload()["rubric"],
        score_band="auto_high",
        sector_codes=("WATER",),
        hub_matches=("Texas Water Systems Hub",),
        rerank_position=1,
        rerank_reason="Strong partnership route.",
    )
    path = tmp_path / "actor-records.csv"

    write_candidate_spreadsheet(path, [candidate])

    with path.open(encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert set(ACTOR_RECORD_FIELDS).issubset(row)
    assert row["name"] == "Example Research Organisation"
    assert row["funding_summary"] == ""
    assert row["sector_codes"] == "WATER"
    assert row["band"] == "auto_high"
    assert row["rubric_evidence"]


def test_actor_candidate_migration_persists_every_score_input():
    sql = (PROJECT_ROOT / "agents" / "sql" / "140_actor_rubric_candidates.sql").read_text(
        encoding="utf-8"
    )

    for column in (
        "gate_fetch",
        "page_fetched",
        "rubric",
        "record_preview",
        "score_breakdown",
        "existing_actor_count",
        "distinctiveness",
        "score_band",
        "rerank_position",
        "rerank_reason",
    ):
        assert f"{column} " in sql


def test_only_auto_high_actor_records_reach_existing_staging_path(monkeypatch, tmp_path):
    config = copy.deepcopy(load_sources_config(PROJECT_ROOT)["open_web_discovery"])
    config.update({"max_pages_fetched": 3, "max_new_domains": 3})
    candidates = [
        _candidate(0, score=None),
        _candidate(1, score=None),
        _candidate(2, score=None),
    ]
    candidates = [
        replace(candidate, url=url, domain=domain)
        for candidate, url, domain in zip(
            candidates,
            (
                "https://high.example/about",
                "https://review.example/about",
                "https://low.example/about",
            ),
            ("high.example", "review.example", "low.example"),
            strict=True,
        )
    ]
    analyses = {
        "high.example": ActorPageAnalysis(
            rubric=_rubric_with_all_evidence(),
            record=_canonical_record("High Actor"),
        ),
        "review.example": ActorPageAnalysis(
            rubric=_analysis_payload()["rubric"],
            record=_canonical_record("Review Actor"),
        ),
        "low.example": ActorPageAnalysis(
            rubric=_empty_rubric(),
            record=_canonical_record("Low Actor"),
        ),
    }

    class Source:
        def fetch(self, url):
            return FetchedDoc.from_content(url=url, content=f"Page for {url}")

    class Extractor:
        def extract(self, doc, **_kwargs):
            return analyses[doc.url.split("//", 1)[1].split("/", 1)[0]]

    staged_records = []

    def capture_stage(**kwargs):
        staged_records.extend(kwargs["extractor"].extract(kwargs["doc"]))
        kwargs["stats"]["records_extracted"] += 1
        kwargs["stats"]["records_staged"] += 1

    monkeypatch.setattr(actor_phase2, "_extract_stage_route_promote", capture_stage)
    run_log = InMemoryRunLog()
    run_id = run_log.start_run(
        source_name="open_web_search", entity_type="actor", live=False, config={}
    )
    stats = {
        "pages_fetched": 0,
        "skipped_unchanged": 0,
        "records_extracted": 0,
        "records_staged": 0,
        "records_promoted": 0,
        "fetch_failures": 0,
    }

    outcome = fetch_score_stage_actors(
        run_id=run_id,
        candidates=candidates,
        config=config,
        root=PROJECT_ROOT,
        session=None,
        live=False,
        run_log=run_log,
        cost_meter=CostMeter(max_usd=5),
        stats=stats,
        audit_rows=[],
        actor_types=["company"],
        sector_codes=["WATER"],
        hub_names=["Texas Water Systems Hub"],
        actor_context={
            "coverage_counts": {("Texas Water Systems Hub", "WATER"): 0}
        },
        source=Source(),
        rubric_extractor=Extractor(),
        reranker=ReverseGroupReranker(),
        raw_store=RawContentStore(tmp_path / "raw"),
        domain_store=InMemoryDiscoveredDomainStore(),
    )

    by_domain = {candidate.domain: candidate for candidate in outcome.candidates}
    assert by_domain["high.example"].score_band == "auto_high"
    assert by_domain["high.example"].triage_verdict == "accepted"
    assert by_domain["review.example"].score_band == "review"
    assert by_domain["review.example"].triage_verdict == "review"
    assert by_domain["low.example"].score_band == "auto_low"
    assert by_domain["low.example"].triage_verdict == "rejected"
    assert [record["name"] for record in staged_records] == ["High Actor"]
    assert stats["actor_band_auto_high"] == 1
    assert stats["actor_band_review"] == 1
    assert stats["actor_band_auto_low"] == 1


def _analysis_payload(record=None):
    rubric = _empty_rubric()
    rubric["own_organisational_page"] = {
        "present": True,
        "evidence": "Official organisation page.",
    }
    rubric["real_operating_entity"] = {
        "present": True,
        "evidence": "Active programmes and staff are listed.",
    }
    rubric["sector_codes"] = [
        {"code": "WATER", "evidence": "Water research is explicit."}
    ]
    rubric["hub_matches"] = [
        {
            "name": "Texas Water Systems Hub",
            "evidence": "The page names its Texas operation.",
        }
    ]
    return {
        "rubric": rubric,
        "record": record
        or {
            "name": "Example Research Organisation",
            "actor_type": "company",
            "website": "https://example.org",
        },
    }


def _canonical_record(name):
    record = {field: None for field in ACTOR_RECORD_FIELDS}
    record.update(
        {
            "name": name,
            "actor_type": "company",
            "website": f"https://{name.lower().replace(' ', '-')}.example",
        }
    )
    return record


def _rubric_with_all_evidence():
    evidence = {"present": True, "evidence": "Specific page evidence."}
    return {
        **{name: dict(evidence) for name in RUBRIC_ITEM_NAMES},
        "use_cases": {name: dict(evidence) for name in USE_CASE_NAMES},
        "sector_codes": [
            {"code": "WATER", "evidence": "Water programmes are explicit."}
        ],
        "hub_matches": [
            {
                "name": "Texas Water Systems Hub",
                "evidence": "Texas operations are explicit.",
            }
        ],
    }


def _empty_rubric():
    absent = {"present": False, "evidence": None}
    return {
        **{name: dict(absent) for name in RUBRIC_ITEM_NAMES},
        "use_cases": {name: dict(absent) for name in USE_CASE_NAMES},
        "sector_codes": [],
        "hub_matches": [],
    }


def _anchor_is_filled(rubric):
    for name in RUBRIC_ITEM_NAMES:
        item = rubric[name]
        if type(item["present"]) is not bool:
            return False
        if item["present"] is not bool(item["evidence"]):
            return False
    return all(
        type(item["present"]) is bool
        and item["present"] is bool(item["evidence"])
        for item in rubric["use_cases"].values()
    )


def _candidate(index, *, score):
    return CandidateRecord(
        candidate_id=f"candidate-{index}",
        run_id="run-1",
        entity_type="actor",
        query="water research organisation",
        provider="stub",
        url=f"https://actor-{index:02d}.example/about",
        title=f"Actor {index}",
        snippet="Organisation page",
        domain=f"actor-{index:02d}.example",
        triage_verdict="accepted",
        triage_reason="fetch",
        fit_score=score,
    )
