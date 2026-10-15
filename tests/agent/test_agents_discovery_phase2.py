from __future__ import annotations

import json
from argparse import Namespace
from datetime import date
from pathlib import Path

import pytest
import yaml

from agents import weekly_discovery
from agents.common.cost import CostLimitExceeded, CostMeter
from agents.common.raw_storage import RawContentStore
from agents.common.resolve_route import RouteDecision
from agents.common.run_log import InMemoryRunLog
from agents.discovery import run as discovery_run
from agents.discovery.extractors.climate_week import ClimateWeekExtractor
from agents.discovery.extractors.event import EventExtractor
from agents.discovery.promote import PromotionResult
from agents.discovery.relevance import load_seeded_sector_codes
from agents.discovery.run import load_config, run_pipeline
from agents.discovery.sources.base import FetchedDoc
from agents.discovery.sources.climate_week import ClimateWeekAdapter
from agents.discovery.sources.unga_guide import UngaGuideAdapter
from agents.discovery.sources.unga_programme import UngaProgrammeAdapter
from agents.discovery.stage import InMemoryStageStore

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "agents"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_MODEL_PRICING = {
    "claude-haiku-4-5": {"input_usd_per_million": 1.0, "output_usd_per_million": 5.0},
    "claude-sonnet-5": {"input_usd_per_million": 2.0, "output_usd_per_million": 10.0},
}


class StaticSource:
    name = "climate_week"
    entity_types = ("event",)
    rate_limit_s = 0.0

    def __init__(self, doc: FetchedDoc):
        self.doc = doc
        self.fetch_calls = 0

    def discover(self):
        yield self.doc.url

    def fetch(self, url: str) -> FetchedDoc:
        self.fetch_calls += 1
        assert url == self.doc.url
        return self.doc


class PersonStaticSource(StaticSource):
    name = "people_fixture"
    entity_types = ("person",)


class NetworkUnavailableSource:
    name = "climate_week"
    entity_types = ("event",)
    rate_limit_s = 0.0

    def discover(self):
        raise AssertionError("replay must not discover URLs")

    def fetch(self, url: str):
        raise AssertionError("replay must not fetch from the network")


class EmptySource:
    name = "climate_week"
    entity_types = ("event",)
    rate_limit_s = 0.0

    def __init__(self, reason: str = ""):
        self.last_discovery_reason = reason

    def discover(self):
        return iter(())

    def fetch(self, url: str):
        raise AssertionError("empty source must not fetch")


class CountingToolClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0
        self.usage = type(
            "Usage",
            (),
            {
                "snapshot": lambda _: {
                    "calls": self.calls,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": 0.0,
                }
            },
        )()

    def extract_with_tool(self, **kwargs):
        self.calls += 1
        return self.payload


class StaticExtractor:
    prompt_version = "event_test_v1"

    def __init__(self, records):
        self.records = records
        self.extract_calls = 0
        self.llm_client = CountingToolClient({"events": []})

    def extract(self, doc):
        self.extract_calls += 1
        return [
            {
                "access_type": "Public",
                "event_type": "Conference",
                **record,
            }
            for record in self.records
        ]


class StaticPersonExtractor(StaticExtractor):
    prompt_version = "person_test_v1"


class FailingExtractor(StaticExtractor):
    def __init__(self):
        super().__init__([])

    def extract(self, doc):
        raise RuntimeError("extractor failed")


def fixture_payload():
    return json.loads(
        (FIXTURE_ROOT / "climate_week_events.expected.json").read_text(encoding="utf-8")
    )


def fixture_doc():
    content = (FIXTURE_ROOT / "climate_week_events.html").read_text(encoding="utf-8")
    return FetchedDoc.from_content(url="fixture://climate_week/events", content=content)


def args(**overrides):
    values = {
        "source": "climate_week",
        "entity": "event",
        "limit": None,
        "live": False,
        "out": None,
        "digest_out": None,
        "replay": None,
        "offline": True,
    }
    values.update(overrides)
    return Namespace(**values)


def test_shipped_sources_config_parses_as_yaml_and_has_required_sources():
    config = load_config(PROJECT_ROOT)

    assert sorted(config) == [
        "cost",
        "event_qualification",
        "open_web_discovery",
        "routing",
        "sources",
    ]
    qualification = dict(config["event_qualification"])
    assert qualification["enabled"] is True
    assert qualification["participant_extraction_enabled"] is True
    assert qualification["forward_window_months"] == 12
    assert float(dict(config["cost"])["max_usd_per_run"]) == 0.50
    open_web = dict(config["open_web_discovery"])
    assert open_web["provider"] == "claude"
    assert open_web["brave_api_key_env"] == "BRAVE_SEARCH_API_KEY"
    assert open_web["web_search_tool_version"] == "web_search_20250305"
    assert float(open_web["web_search_usd_per_request"]) == 0.01
    assert open_web["search_model"] == "claude-haiku-4-5"
    assert open_web["triage_model"] == "claude-sonnet-5"
    assert int(open_web["max_searches"]) == 52
    assert int(open_web["max_candidates_triaged"]) == 200
    assert float(open_web["max_usd_per_run"]) == 5.00
    # On since 2026-10-15: supervisor sign-off, recorded in TARGETING_POLICY.md
    # section 6. Person records still route to review, one by one.
    assert open_web["people_enabled"] is True
    sources = dict(config["sources"])
    assert set(sources) >= {"climate_week", "unga_programme", "unga_guide"}
    assert dict(sources["climate_week"])["entity_types"] == ["event"]
    assert dict(sources["unga_programme"])["entity_types"] == ["event"]
    assert dict(sources["unga_guide"])["entity_types"] == ["event"]
    for source_name in ("climate_week", "unga_programme", "unga_guide"):
        source = dict(sources[source_name])
        assert source["raw_storage_dir"]
        assert source["contact_email_env"] == "GHUS_AGENT_CONTACT_EMAIL"
    climate_week = dict(sources["climate_week"])
    assert climate_week["extractor"] == "climate_week"
    assert "claude_model" not in climate_week
    assert "llm_pricing" not in climate_week
    assert "event_row_batch_size" not in climate_week
    assert len(dict(climate_week["theme_to_sector_codes"])) == 12
    for source_name in ("unga_programme", "unga_guide"):
        source = dict(sources[source_name])
        assert "claude_model" in source
        assert "llm_pricing" in source


def test_configured_model_pricing_matches_selected_models():
    config = load_config(PROJECT_ROOT)
    open_web = dict(config["open_web_discovery"])

    _assert_model_pricing_matches(
        open_web["search_model"],
        dict(open_web["search_llm_pricing"]),
    )
    _assert_model_pricing_matches(
        open_web["triage_model"],
        dict(open_web["triage_llm_pricing"]),
    )
    for source in dict(config["sources"]).values():
        source = dict(source)
        if "claude_model" not in source:
            continue
        _assert_model_pricing_matches(source["claude_model"], dict(source["llm_pricing"]))


def routing_signature(result):
    return [
        {
            "source_url": row["source_url"],
            "natural_key": row["natural_key"],
            "zone": row["zone"],
            "score": row["score"],
            "target_entity_id": row["target_entity_id"],
            "candidate_ids": row["candidate_ids"],
        }
        for row in result["audit_rows"]
        if row["status"] != "skipped_unchanged"
    ]


def test_hash_match_skips_extraction_and_llm_calls(tmp_path):
    doc = fixture_doc()
    run_log = InMemoryRunLog()
    seed_run_id = run_log.start_run(
        source_name="climate_week", entity_type="event", live=False, config={}
    )
    raw_store = RawContentStore(tmp_path / "raw")
    storage_path = raw_store.write(run_id=seed_run_id, doc=doc)
    run_log.write_raw_document(run_id=seed_run_id, doc=doc, storage_path=storage_path)

    client = CountingToolClient(fixture_payload())
    result = run_pipeline(
        args(out=str(tmp_path / "audit.csv"), digest_out=str(tmp_path / "digest.md")),
        root=PROJECT_ROOT,
        run_log=run_log,
        stage_store=InMemoryStageStore(),
        source=StaticSource(doc),
        extractor=EventExtractor(client),
        raw_store=raw_store,
    )

    assert result["stats"]["skipped_unchanged"] == 1
    assert result["stats"]["records_extracted"] == 0
    assert result["status"] == "succeeded"
    assert seed_run_id in result["stats"]["status_reason"]
    assert "no extraction needed" in result["stats"]["status_reason"]
    digest = (tmp_path / "digest.md").read_text(encoding="utf-8")
    assert f"**Reason:** 1 document(s) unchanged since run {seed_run_id}" in digest
    assert client.calls == 0


@pytest.mark.parametrize(
    ("adapter_cls", "config", "expected_url"),
    [
        (
            ClimateWeekAdapter,
            {
                "listing_url": "https://www.climateweeknyc.org/event-search",
                "pagination_urls": [
                    "https://www.climateweeknyc.org/event-search/",
                    "https://www.climateweeknyc.org/event-search?redirect=1",
                ],
            },
            "https://www.climateweeknyc.org/event-search",
        ),
        (
            UngaProgrammeAdapter,
            {
                "meeting_url": "https://www.un.org/en/ga/81/meetings/",
                "seed_urls": ["https://www.un.org/en/ga/81/meetings/?redirect=1"],
            },
            "https://www.un.org/en/ga/81/meetings/",
        ),
        (
            UngaGuideAdapter,
            {
                "listing_url": "https://ungaguide.com/",
                "seed_urls": ["https://ungaguide.com/?redirect=1"],
            },
            "https://ungaguide.com/",
        ),
    ],
)
def test_source_adapters_discover_dedupes_after_redirects(
    monkeypatch, adapter_cls, config, expected_url
):
    adapter = adapter_cls(config, project_root=PROJECT_ROOT, offline=False)
    monkeypatch.setattr(adapter.http, "resolve_url", lambda url: expected_url)
    if isinstance(adapter, UngaGuideAdapter):
        monkeypatch.setattr(
            adapter,
            "fetch",
            lambda url: FetchedDoc.from_content(
                url=url, content="<html>Search through 1 events</html>"
            ),
        )

    assert list(adapter.discover()) == [expected_url]


def test_unga_guide_discover_generates_full_pagination_range(monkeypatch):
    adapter = UngaGuideAdapter(
        {"listing_url": "https://ungaguide.com/"}, project_root=PROJECT_ROOT, offline=False
    )
    content = """
    <html><body>
      <main id="site-content">
        <a class="page-numbers" href="https://ungaguide.com/page/2/">2</a>
        <a class="page-numbers" href="https://ungaguide.com/page/3/">3</a>
        <span class="page-numbers dots">...</span>
        <a class="page-numbers" href="https://ungaguide.com/page/11/">11</a>
      </main>
    </body></html>
    """
    monkeypatch.setattr(adapter.http, "resolve_url", lambda url: url)
    monkeypatch.setattr(
        adapter, "fetch", lambda url: FetchedDoc.from_content(url=url, content=content)
    )

    assert list(adapter.discover()) == [
        "https://ungaguide.com/",
        *[f"https://ungaguide.com/page/{page}/" for page in range(2, 12)],
    ]


def test_replay_reproduces_original_routing_with_network_unavailable(tmp_path):
    doc = fixture_doc()
    run_log = InMemoryRunLog()
    raw_store = RawContentStore(tmp_path / "raw")
    first_client = CountingToolClient(fixture_payload())

    first = run_pipeline(
        args(out=str(tmp_path / "first.csv"), digest_out=str(tmp_path / "first.md")),
        root=PROJECT_ROOT,
        run_log=run_log,
        stage_store=InMemoryStageStore(),
        source=StaticSource(doc),
        extractor=EventExtractor(first_client),
        raw_store=raw_store,
    )

    replay_client = CountingToolClient(fixture_payload())
    replay = run_pipeline(
        args(
            replay=first["run_id"],
            out=str(tmp_path / "replay.csv"),
            digest_out=str(tmp_path / "replay.md"),
        ),
        root=PROJECT_ROOT,
        run_log=run_log,
        stage_store=InMemoryStageStore(),
        source=NetworkUnavailableSource(),
        extractor=EventExtractor(replay_client),
        raw_store=raw_store,
    )

    assert routing_signature(replay) == routing_signature(first)
    assert replay_client.calls == first_client.calls


def test_pipeline_dedupes_duplicate_natural_keys_before_staging(tmp_path):
    doc = fixture_doc()
    run_log = InMemoryRunLog()
    stage_store = InMemoryStageStore()
    raw_store = RawContentStore(tmp_path / "raw")
    valid_code = min(load_seeded_sector_codes(PROJECT_ROOT))
    duplicate_records = [
        {
            "title": "Duplicate Climate Event",
            "start_date": "2026-09-22",
            "source_url": doc.url,
            "extracted_at": "2026-08-10T00:00:00+00:00",
            "sector_codes": [valid_code],
        },
        {
            "title": "Duplicate   Climate Event",
            "start_date": "2026-09-22",
            "source_url": doc.url,
            "extracted_at": "2026-08-10T00:00:00+00:00",
            "sector_codes": [valid_code],
        },
    ]

    result = run_pipeline(
        args(out=str(tmp_path / "audit.csv"), digest_out=str(tmp_path / "digest.md")),
        root=PROJECT_ROOT,
        run_log=run_log,
        stage_store=stage_store,
        source=StaticSource(doc),
        extractor=StaticExtractor(duplicate_records),
        raw_store=raw_store,
    )

    assert result["stats"]["records_extracted"] == 1
    assert result["stats"]["records_staged"] == 1
    assert stage_store.row_count() == 1


def test_status_succeeded_when_documents_fetch_and_records_stage(tmp_path):
    doc = fixture_doc()
    valid_code = min(load_seeded_sector_codes(PROJECT_ROOT))

    result = run_pipeline(
        args(out=str(tmp_path / "audit.csv"), digest_out=str(tmp_path / "digest.md")),
        root=PROJECT_ROOT,
        run_log=InMemoryRunLog(),
        stage_store=InMemoryStageStore(),
        source=StaticSource(doc),
        extractor=StaticExtractor(
            [
                {
                    "title": "Climate Status Event",
                    "start_date": "2026-09-22",
                    "source_url": doc.url,
                    "extracted_at": "2026-08-10T00:00:00+00:00",
                    "sector_codes": [valid_code],
                }
            ]
        ),
        raw_store=RawContentStore(tmp_path / "raw"),
    )

    assert result["status"] == "succeeded"
    assert result["stats"]["status_reason"] == "staged 1 record(s): 1 in-sector, 0 out-of-sector"


def test_extractor_attention_reason_overrides_success_status(tmp_path):
    doc = FetchedDoc.from_content(
        url="fixture://climate_week/event-search",
        content="""
        <!-- event listing: total=5 fetched=2 pages_needed=3 max_pages=10 -->
        <div class="hubdb-listing">
          <article class="event-card theme-energy">
            <a class="event-card__link" href="/event-search/one">
              <h3 class="event-card__title">One</h3>
              <time datetime="2026-09-17">September 17, 2026</time>
            </a>
          </article>
          <article class="event-card theme-energy">
            <a class="event-card__link" href="/event-search/two">
              <h3 class="event-card__title">Two</h3>
              <time datetime="2026-09-18">September 18, 2026</time>
            </a>
          </article>
        </div>
        """,
        meta={"extractor_mode": "hubdb_listing"},
    )
    valid_code = min(load_seeded_sector_codes(PROJECT_ROOT))
    result = run_pipeline(
        args(out=str(tmp_path / "audit.csv"), digest_out=str(tmp_path / "digest.md")),
        root=PROJECT_ROOT,
        run_log=InMemoryRunLog(),
        stage_store=InMemoryStageStore(),
        source=StaticSource(doc),
        extractor=ClimateWeekExtractor(
            theme_to_sector_codes={"energy": [valid_code]},
            base_url="https://www.climateweeknyc.org/event-search",
            min_row_count=4,
        ),
        raw_store=RawContentStore(tmp_path / "raw"),
    )

    assert result["stats"]["records_staged"] == 2
    assert result["status"] == "attention"
    assert "below configured floor 4" in result["stats"]["status_reason"]
    assert "displays total=5 but parser found 2 rows" in result["stats"]["status_reason"]


def test_build_climate_week_extractor_never_constructs_llm(monkeypatch):
    source_config = dict(load_config(PROJECT_ROOT)["sources"]["climate_week"])

    def fail_if_constructed(*args, **kwargs):
        raise AssertionError("Climate Week must not construct an LLM client")

    monkeypatch.setattr(discovery_run, "ClaudeToolClient", fail_if_constructed)

    extractor = discovery_run.build_extractor(
        "event",
        source_config,
        PROJECT_ROOT,
        offline=False,
        cost_meter=CostMeter(max_usd=0.50),
    )

    assert isinstance(extractor, ClimateWeekExtractor)
    assert extractor.theme_to_sector_codes == {
        theme: tuple(codes)
        for theme, codes in source_config["theme_to_sector_codes"].items()
    }


def test_status_attention_when_documents_fetch_but_zero_records_extract(tmp_path):
    doc = fixture_doc()
    result = run_pipeline(
        args(out=str(tmp_path / "audit.csv"), digest_out=str(tmp_path / "digest.md")),
        root=PROJECT_ROOT,
        run_log=InMemoryRunLog(),
        stage_store=InMemoryStageStore(),
        source=StaticSource(doc),
        extractor=StaticExtractor([]),
        raw_store=RawContentStore(tmp_path / "raw"),
    )

    assert result["status"] == "attention"
    assert result["stats"]["status_reason"] == "documents fetched but zero records extracted"
    digest = (tmp_path / "digest.md").read_text(encoding="utf-8")
    assert "**Status:** attention" in digest
    assert "**Reason:** documents fetched but zero records extracted" in digest


@pytest.mark.parametrize("event_date", ["2026-09-08", "2027-09-10"])
def test_structured_out_of_window_event_rejects_before_extractor_call(
    event_date,
    tmp_path,
):
    doc = FetchedDoc.from_content(
        url="https://events.example/outside-window",
        content=f'<html><time datetime="{event_date}">{event_date}</time></html>',
    )
    extractor = StaticExtractor(
        [
            {
                "title": "Outside Window Conference",
                "start_date": event_date,
                "source_url": doc.url,
                "extracted_at": "2026-09-09T00:00:00+00:00",
                "sector_codes": [min(load_seeded_sector_codes(PROJECT_ROOT))],
            }
        ]
    )

    result = run_pipeline(
        args(out=str(tmp_path / "audit.csv"), digest_out=str(tmp_path / "digest.md")),
        root=PROJECT_ROOT,
        run_log=InMemoryRunLog(),
        stage_store=InMemoryStageStore(),
        source=StaticSource(doc),
        extractor=extractor,
        raw_store=RawContentStore(tmp_path / "raw"),
        run_date=date(2026, 9, 9),
    )

    assert extractor.extract_calls == 0
    assert extractor.llm_client.calls == 0
    assert result["status"] == "succeeded"
    assert result["stats"]["events_rejected_unqualified"] == 1
    assert result["audit_rows"][0]["status"] == "rejected_date_window"
    digest = (tmp_path / "digest.md").read_text(encoding="utf-8")
    assert "| Rejected: neither path | 1 |" in digest


def test_past_event_with_speakers_mines_participants_without_event_row(
    monkeypatch,
    tmp_path,
):
    sector_code = min(load_seeded_sector_codes(PROJECT_ROOT))
    speaker_rows = "".join(
        f"<li>Speaker {index} - Director, Institute {index}</li>"
        for index in range(1, 6)
    )
    doc = FetchedDoc.from_content(
        url="https://events.example/past-speaker-event",
        content=(
            '<html><time datetime="2026-04-10">April 10, 2026</time>'
            f"<h2>Speakers</h2><ul>{speaker_rows}</ul></html>"
        ),
    )
    extractor = StaticExtractor(
        [
            {
                "title": "Spring Climate Conference",
                "start_date": "2026-04-10",
                "source_url": doc.url,
                "extracted_at": "2026-09-09T00:00:00+00:00",
                "sector_codes": [sector_code],
                "participant_people": [
                    {
                        "name": f"Speaker {index}",
                        "affiliation": f"Institute {index}",
                        "role": "Director",
                        "public_profile_url": None,
                    }
                    for index in range(1, 6)
                ],
            }
        ]
    )
    stage_store = InMemoryStageStore()
    monkeypatch.setattr(
        discovery_run,
        "route_actor",
        lambda _record, _resolver, _mapped=None: RouteDecision(zone="review", score=0.5),
    )

    result = run_pipeline(
        args(
            enable_people_for_run=True,
            out=str(tmp_path / "audit.csv"),
            digest_out=str(tmp_path / "digest.md"),
        ),
        root=PROJECT_ROOT,
        run_log=InMemoryRunLog(),
        stage_store=stage_store,
        source=StaticSource(doc),
        extractor=extractor,
        raw_store=RawContentStore(tmp_path / "raw"),
        actor_resolver=object(),
        run_date=date(2026, 9, 9),
    )

    staged_types = [row.entity_type for row in stage_store.rows.values()]
    assert extractor.extract_calls == 1
    assert "event" not in staged_types
    assert staged_types.count("actor") == 5
    assert staged_types.count("person") == 5
    assert result["stats"]["events_mined_not_stored"] == 1
    assert any(row["status"] == "mined_not_stored" for row in result["audit_rows"])
    digest = (tmp_path / "digest.md").read_text(encoding="utf-8")
    assert "| Mined, not stored | 1 |" in digest


def test_past_event_with_one_organizer_rejects_before_extractor_call(tmp_path):
    doc = FetchedDoc.from_content(
        url="https://events.example/past-organizer-event",
        content=(
            '<script type="application/ld+json">'
            '{"@type":"Event","startDate":"2026-04-10",'
            '"organizer":{"@type":"Organization","name":"Only Organizer"}}'
            "</script>"
        ),
    )
    extractor = StaticExtractor([])
    stage_store = InMemoryStageStore()

    result = run_pipeline(
        args(out=str(tmp_path / "audit.csv"), digest_out=str(tmp_path / "digest.md")),
        root=PROJECT_ROOT,
        run_log=InMemoryRunLog(),
        stage_store=stage_store,
        source=StaticSource(doc),
        extractor=extractor,
        raw_store=RawContentStore(tmp_path / "raw"),
        run_date=date(2026, 9, 9),
    )

    assert extractor.extract_calls == 0
    assert extractor.llm_client.calls == 0
    assert stage_store.row_count() == 0
    assert result["stats"]["events_rejected_unqualified"] == 1


def test_status_succeeded_when_records_extract_but_zero_are_in_sector(tmp_path):
    doc = fixture_doc()
    result = run_pipeline(
        args(out=str(tmp_path / "audit.csv"), digest_out=str(tmp_path / "digest.md")),
        root=PROJECT_ROOT,
        run_log=InMemoryRunLog(),
        stage_store=InMemoryStageStore(),
        source=StaticSource(doc),
        extractor=StaticExtractor(
            [
                {
                    "title": "Out Of Seed Sector Event",
                    "start_date": "2026-09-22",
                    "source_url": doc.url,
                    "extracted_at": "2026-08-10T00:00:00+00:00",
                    "sector_codes": ["UNSEEDED_FRONTIER"],
                }
            ]
        ),
        raw_store=RawContentStore(tmp_path / "raw"),
    )

    assert result["status"] == "succeeded"
    assert result["stats"]["records_extracted"] == 1
    assert result["stats"]["records_in_sector"] == 0
    assert result["stats"]["records_out_of_sector"] == 1
    assert (
        result["stats"]["status_reason"]
        == "extracted 1 record(s); 0 matched seeded sectors; staged as out_of_sector"
    )


def test_cost_ceiling_breach_closes_attention_retains_staged_records(monkeypatch, tmp_path):
    doc = fixture_doc()
    run_log = InMemoryRunLog()
    stage_store = InMemoryStageStore()
    valid_code = min(load_seeded_sector_codes(PROJECT_ROOT))

    def fake_enforce(self):
        self.max_usd = 0.05
        self.spent_usd = 0.06
        raise CostLimitExceeded("agent run cost $0.0600 exceeded ceiling $0.0500")

    monkeypatch.setattr(CostMeter, "enforce", fake_enforce)

    result = run_pipeline(
        args(out=str(tmp_path / "audit.csv"), digest_out=str(tmp_path / "digest.md")),
        root=PROJECT_ROOT,
        run_log=run_log,
        stage_store=stage_store,
        source=StaticSource(doc),
        extractor=StaticExtractor(
            [
                {
                    "title": "Partially Kept Climate Event",
                    "start_date": "2026-09-22",
                    "source_url": doc.url,
                    "extracted_at": "2026-08-10T00:00:00+00:00",
                    "sector_codes": [valid_code],
                }
            ]
        ),
        raw_store=RawContentStore(tmp_path / "raw"),
    )

    run = next(iter(run_log.runs.values()))
    assert result["status"] == "attention"
    assert result["exit_code"] == 1
    assert run.status == "attention"
    assert result["stats"]["records_staged"] == 1
    assert stage_store.row_count() == 1
    assert result["stats"]["failures"] == 0
    assert "cost ceiling exceeded" in result["stats"]["status_reason"]
    assert "$0.060000" in result["stats"]["status_reason"]
    assert (tmp_path / "audit.csv").exists()
    digest = (tmp_path / "digest.md").read_text(encoding="utf-8")
    assert "**Status:** attention" in digest
    assert "**Reason:** cost ceiling exceeded" in digest


def test_discovery_main_exits_nonzero_for_cost_attention(monkeypatch):
    def fake_run_pipeline(_args):
        return {
            "run_id": "run-1",
            "status": "attention",
            "stats": {
                "documents_fetched": 1,
                "skipped_unchanged": 0,
                "records_extracted": 1,
                "records_in_sector": 1,
                "records_out_of_sector": 0,
                "records_staged": 1,
                "audit_csv": "audit.csv",
                "digest_md": "digest.md",
            },
            "exit_code": 1,
        }

    monkeypatch.setattr(discovery_run, "run_pipeline", fake_run_pipeline)

    with pytest.raises(SystemExit) as exc:
        discovery_run.main(["--source", "climate_week", "--entity", "event"])

    assert exc.value.code == 1


def test_status_attention_when_source_yields_zero_urls(tmp_path):
    result = run_pipeline(
        args(out=str(tmp_path / "audit.csv"), digest_out=str(tmp_path / "digest.md")),
        root=PROJECT_ROOT,
        run_log=InMemoryRunLog(),
        stage_store=InMemoryStageStore(),
        source=EmptySource("test source has no URLs"),
        extractor=StaticExtractor([]),
        raw_store=RawContentStore(tmp_path / "raw"),
    )

    assert result["status"] == "attention"
    assert result["stats"]["status_reason"] == "test source has no URLs"


def test_status_attention_when_limit_prevents_all_fetches(tmp_path):
    doc = fixture_doc()
    result = run_pipeline(
        args(limit=0, out=str(tmp_path / "audit.csv"), digest_out=str(tmp_path / "digest.md")),
        root=PROJECT_ROOT,
        run_log=InMemoryRunLog(),
        stage_store=InMemoryStageStore(),
        source=StaticSource(doc),
        extractor=StaticExtractor([]),
        raw_store=RawContentStore(tmp_path / "raw"),
    )

    assert result["status"] == "attention"
    assert result["stats"]["status_reason"] == "source yielded zero fetched documents"


def test_status_failed_when_extractor_raises(tmp_path):
    doc = fixture_doc()
    run_log = InMemoryRunLog()

    with pytest.raises(RuntimeError, match="extractor failed"):
        run_pipeline(
            args(out=str(tmp_path / "audit.csv"), digest_out=str(tmp_path / "digest.md")),
            root=PROJECT_ROOT,
            run_log=run_log,
            stage_store=InMemoryStageStore(),
            source=StaticSource(doc),
            extractor=FailingExtractor(),
            raw_store=RawContentStore(tmp_path / "raw"),
        )

    run = next(iter(run_log.runs.values()))
    assert run.status == "failed"
    assert run.status_reason == "extractor failed"


def test_dry_run_checks_mapped_records_before_discovery_and_exact_event_absorbs(
    monkeypatch, tmp_path
):
    doc = fixture_doc()
    run_log = InMemoryRunLog()
    raw_store = RawContentStore(tmp_path / "raw")
    session = object()
    call_order = []
    decisions = []

    def fake_load_event_candidates(active_session):
        call_order.append(("load_event_candidates", active_session))
        return [
            {"event_id": "evt-1", "name": "Climate Innovation Summit", "next_date": "2026-09-22"}
        ]

    def fake_load_actor_candidates(active_session):
        call_order.append(("load_actor_candidates", active_session))
        return []

    class OrderedSource(StaticSource):
        def discover(self):
            call_order.append(("discover", None))
            yield self.doc.url

    def fake_promote(staged, decision, *, session=None, live=False):
        decisions.append(decision)
        return PromotionResult(
            action=f"would_{decision.zone}",
            entity_type=staged.entity_type,
            zone=decision.zone,
            entity_id=decision.target_entity_id,
            dry_run=True,
        )

    monkeypatch.setattr("agents.discovery.run.load_event_candidates", fake_load_event_candidates)
    monkeypatch.setattr("agents.discovery.run.load_actor_candidates", fake_load_actor_candidates)
    monkeypatch.setattr("agents.discovery.run.promote", fake_promote)

    result = run_pipeline(
        args(
            offline=False, out=str(tmp_path / "audit.csv"), digest_out=str(tmp_path / "digest.md")
        ),
        session=session,
        root=PROJECT_ROOT,
        run_log=run_log,
        stage_store=InMemoryStageStore(),
        source=OrderedSource(doc),
        extractor=EventExtractor(CountingToolClient(fixture_payload())),
        raw_store=raw_store,
        run_date=date(2026, 9, 1),
    )

    assert call_order[:3] == [
        ("load_event_candidates", session),
        ("load_actor_candidates", session),
        ("discover", None),
    ]
    assert decisions[0].zone == "absorb"
    assert result["audit_rows"][0]["zone"] == "absorb"
    assert result["audit_rows"][0]["target_entity_id"] == "evt-1"
    assert result["audit_rows"][0]["candidate_ids"] == ["evt-1"]


def test_person_pipeline_routes_to_review_without_sector_codes(tmp_path):
    doc = fixture_doc()
    run_log = InMemoryRunLog()
    stage_store = InMemoryStageStore()

    result = run_pipeline(
            args(
                source="people_fixture",
                entity="person",
                enable_people_for_run=True,
                out=str(tmp_path / "audit.csv"),
            digest_out=str(tmp_path / "digest.md"),
        ),
        root=PROJECT_ROOT,
        run_log=run_log,
        stage_store=stage_store,
        source=PersonStaticSource(doc),
        extractor=StaticPersonExtractor(
            [
                {
                    "name": "Dr. Amina Example",
                    "affiliation": "Example Climate Lab",
                    "role": "Research Director",
                    "public_profile_url": "https://example.org/amina",
                    "research_area": "climate analytics",
                    "source_url": doc.url,
                    "extracted_at": "2026-08-10T00:00:00+00:00",
                }
            ]
        ),
        raw_store=RawContentStore(tmp_path / "raw"),
    )

    assert result["status"] == "succeeded"
    assert result["stats"]["records_extracted"] == 1
    assert result["stats"]["records_in_sector"] == 1
    assert result["stats"]["records_out_of_sector"] == 0
    assert result["stats"]["queued_for_review"] == 1
    assert result["audit_rows"][0]["zone"] == "review"
    assert result["audit_rows"][0]["status"] == "would_review"
    staged = next(iter(stage_store.rows.values()))
    assert staged.entity_type == "person"
    assert staged.sector_match == "in_sector"
    assert staged.status == "routed_review"


def test_out_of_sector_record_is_staged_and_never_promoted(monkeypatch, tmp_path):
    doc = fixture_doc()
    run_log = InMemoryRunLog()
    stage_store = InMemoryStageStore()
    raw_store = RawContentStore(tmp_path / "raw")
    promoted = []
    valid_code = min(load_seeded_sector_codes(PROJECT_ROOT))

    def fake_promote(staged, decision, *, session=None, live=False):
        promoted.append(staged)
        return PromotionResult(
            action=f"would_{decision.zone}",
            entity_type=staged.entity_type,
            zone=decision.zone,
            entity_id=decision.target_entity_id,
            dry_run=True,
        )

    monkeypatch.setattr("agents.discovery.run.promote", fake_promote)

    result = run_pipeline(
        args(out=str(tmp_path / "audit.csv"), digest_out=str(tmp_path / "digest.md")),
        root=PROJECT_ROOT,
        run_log=run_log,
        stage_store=stage_store,
        source=StaticSource(doc),
        extractor=StaticExtractor(
            [
                {
                    "title": "In-Sector Climate Summit",
                    "start_date": "2026-09-22",
                    "source_url": doc.url,
                    "extracted_at": "2026-08-10T00:00:00+00:00",
                    "sector_codes": [valid_code],
                },
                {
                    "title": "Unseeded Frontier Summit",
                    "start_date": "2026-09-23",
                    "source_url": doc.url,
                    "extracted_at": "2026-08-10T00:00:00+00:00",
                    "sector_codes": ["UNSEEDED_FRONTIER"],
                },
            ]
        ),
        raw_store=raw_store,
        run_date=date(2026, 9, 1),
    )

    assert result["stats"]["records_extracted"] == 2
    assert result["stats"]["records_in_sector"] == 1
    assert result["stats"]["records_out_of_sector"] == 1
    assert result["stats"]["records_staged"] == 2
    assert result["status"] == "succeeded"
    assert len(promoted) == 1
    rows = list(stage_store.rows.values())
    assert sorted(row.sector_match for row in rows) == ["in_sector", "out_of_sector"]
    out_of_sector_rows = [row for row in rows if row.sector_match == "out_of_sector"]
    assert out_of_sector_rows
    assert all(row.status == "staged" for row in out_of_sector_rows)
    assert any(
        row["status"] == "out_of_sector" and row["zone"] == "out_of_sector"
        for row in result["audit_rows"]
    )


def test_scheduled_workflow_does_not_enable_live():
    workflow = yaml.safe_load(
        (PROJECT_ROOT / ".github" / "workflows" / "weekly-discovery.yml").read_text(
            encoding="utf-8"
        )
    )
    run_step = next(
        step
        for step in workflow["jobs"]["weekly-discovery"]["steps"]
        if step.get("name") == "Run weekly discovery"
    )
    script = run_step["run"]

    assert '"$GITHUB_EVENT_NAME" = "workflow_dispatch"' in script
    assert '"$GITHUB_EVENT_NAME" = "schedule"' not in script


def test_weekly_workflow_passes_required_secrets():
    workflow_text = (PROJECT_ROOT / ".github" / "workflows" / "weekly-discovery.yml").read_text(
        encoding="utf-8"
    )
    workflow = yaml.safe_load(workflow_text)
    env = workflow["jobs"]["weekly-discovery"]["env"]

    assert env["DATABASE_URL"] == "${{ secrets.DATABASE_URL }}"
    assert env["ANTHROPIC_API_KEY"] == "${{ secrets.ANTHROPIC_API_KEY }}"
    assert env["GHUS_AGENT_CONTACT_EMAIL"] == "${{ secrets.GHUS_AGENT_CONTACT_EMAIL }}"
    assert "VOYAGE_API_KEY" not in workflow_text


def test_weekly_workflow_validates_required_environment_before_discovery():
    workflow = yaml.safe_load(
        (PROJECT_ROOT / ".github" / "workflows" / "weekly-discovery.yml").read_text(
            encoding="utf-8"
        )
    )
    steps = workflow["jobs"]["weekly-discovery"]["steps"]
    names = [step.get("name") for step in steps]
    validate_index = names.index("Validate required environment")
    discovery_index = names.index("Run weekly discovery")
    validate_script = steps[validate_index]["run"]

    assert validate_index < discovery_index
    for name in ("DATABASE_URL", "ANTHROPIC_API_KEY", "GHUS_AGENT_CONTACT_EMAIL"):
        assert name in validate_script
    assert "Missing required environment variable(s):" in validate_script
    assert "${missing[*]}" in validate_script
    assert "printenv \"$name\"" in validate_script
    assert "${!name" not in validate_script
    assert 'printf "$' not in validate_script


def test_weekly_workflow_validates_anthropic_sdk_before_discovery():
    workflow = yaml.safe_load(
        (PROJECT_ROOT / ".github" / "workflows" / "weekly-discovery.yml").read_text(
            encoding="utf-8"
        )
    )
    steps = workflow["jobs"]["weekly-discovery"]["steps"]
    names = [step.get("name") for step in steps]
    compatibility_index = names.index("Validate Anthropic SDK compatibility")
    discovery_index = names.index("Run weekly discovery")
    compatibility_script = steps[compatibility_index]["run"]

    assert compatibility_index < discovery_index
    assert "tests/agent/test_agents_common_llm.py" in compatibility_script


def test_weekly_workflow_runs_all_sources_and_reports_outcomes_before_failure():
    workflow = yaml.safe_load(
        (PROJECT_ROOT / ".github" / "workflows" / "weekly-discovery.yml").read_text(
            encoding="utf-8"
        )
    )
    steps = workflow["jobs"]["weekly-discovery"]["steps"]
    run_step = next(step for step in steps if step.get("name") == "Run weekly discovery")
    upload_step = next(
        step for step in steps if step.get("name") == "Upload weekly discovery artifacts"
    )
    script = run_step["run"]

    assert "python -m agents.weekly_discovery" in script
    assert "python -m agents.discovery.run" not in script
    assert "python -m agents.enrichment.run" not in script
    assert "python -m agents.index.refresh" not in script
    assert "agents/runs/source-outcomes.md" in upload_step["with"]["path"]
    assert upload_step["if"] == "always()"


def test_weekly_orchestrator_runs_every_source_and_downstream_after_source_failure(tmp_path):
    commands = []

    def runner(command):
        commands.append(list(command))
        module = command[command.index("-m") + 1]
        if module == "agents.discovery.search.run":
            report_path = Path(command[command.index("--report-out") + 1])
            report_path.write_text("Status: **succeeded**\n", encoding="utf-8")
            return 0
        if module == "agents.discovery.run":
            source = command[command.index("--source") + 1]
            digest_path = Path(command[command.index("--digest-out") + 1])
            status = "failed" if source == "climate_week" else "succeeded"
            digest_path.write_text(f"**Status:** {status}\n", encoding="utf-8")
            return 1 if source == "climate_week" else 0
        return 0

    outcome = weekly_discovery.run_weekly(runs_dir=tmp_path, runner=runner)

    modules = [command[command.index("-m") + 1] for command in commands]
    discovery_sources = [
        command[command.index("--source") + 1]
        for command in commands
        if command[command.index("-m") + 1] == "agents.discovery.run"
    ]

    assert discovery_sources == ["climate_week", "unga_programme", "unga_guide"]
    assert modules[-2:] == ["agents.enrichment.run", "agents.index.refresh"]
    assert outcome.exit_code == 1
    summary = (tmp_path / "source-outcomes.md").read_text(encoding="utf-8")
    assert (
            "Discovery succeeded: open_web_event, unga_programme, unga_guide"
            in summary
        )
    assert "Discovery failed: climate_week(status=failed,exit=1)" in summary
    assert "Downstream succeeded: enrichment, index_refresh" in summary


def _assert_model_pricing_matches(model: str, pricing: dict[str, object]) -> None:
    expected = EXPECTED_MODEL_PRICING[str(model)]
    assert float(pricing["input_usd_per_million"]) == expected["input_usd_per_million"]
    assert float(pricing["output_usd_per_million"]) == expected["output_usd_per_million"]


def test_weekly_orchestrator_missing_digest_is_failure_but_continues(tmp_path):
    commands = []

    def runner(command):
        commands.append(list(command))
        module = command[command.index("-m") + 1]
        if module == "agents.discovery.search.run":
            report_path = Path(command[command.index("--report-out") + 1])
            report_path.write_text("Status: **succeeded**\n", encoding="utf-8")
            return 0
        if module == "agents.discovery.run":
            source = command[command.index("--source") + 1]
            if source != "climate_week":
                digest_path = Path(command[command.index("--digest-out") + 1])
                digest_path.write_text("**Status:** succeeded\n", encoding="utf-8")
        return 0

    outcome = weekly_discovery.run_weekly(runs_dir=tmp_path, runner=runner)

    assert len(commands) == 6
    assert outcome.exit_code == 1
    assert outcome.discovery[1].name == "climate_week"
    assert outcome.discovery[1].status == "missing_digest"
    summary = (tmp_path / "source-outcomes.md").read_text(encoding="utf-8")
    assert "climate_week(status=missing_digest,exit=1)" in summary


def test_weekly_orchestrator_no_longer_sweeps_for_actors(tmp_path):
    """Actors are discovered only for Discovery-page requests, never on a timer."""

    commands = []

    def runner(command):
        commands.append(list(command))
        if "--report-out" in command:
            Path(command[command.index("--report-out") + 1]).write_text(
                "Status: **succeeded**\n", encoding="utf-8")
        if "--digest-out" in command:
            Path(command[command.index("--digest-out") + 1]).write_text(
                "**Status:** succeeded\n", encoding="utf-8")
        return 0

    weekly_discovery.run_weekly(runs_dir=tmp_path, runner=runner)
    searched = [c[c.index("--entity") + 1] for c in commands
                if c[c.index("-m") + 1] == "agents.discovery.search.run"]
    assert searched == ["event"]


def test_weekly_orchestrator_passes_live_flag_to_all_commands(tmp_path):
    commands = []

    def runner(command):
        commands.append(list(command))
        module = command[command.index("-m") + 1]
        if module == "agents.discovery.search.run":
            report_path = Path(command[command.index("--report-out") + 1])
            report_path.write_text("Status: **succeeded**\n", encoding="utf-8")
            return 0
        if module == "agents.discovery.run":
            digest_path = Path(command[command.index("--digest-out") + 1])
            digest_path.write_text("**Status:** succeeded\n", encoding="utf-8")
        return 0

    outcome = weekly_discovery.run_weekly(live=True, runs_dir=tmp_path, runner=runner)

    assert outcome.exit_code == 0
    assert all("--live" in command for command in commands)


def test_weekly_orchestrator_required_env_names_missing_without_values():
    with pytest.raises(RuntimeError) as exc:
        weekly_discovery.validate_required_env(
            {
                "DATABASE_URL": "",
                "ANTHROPIC_API_KEY": "secret-value",
            }
        )

    message = str(exc.value)
    assert "DATABASE_URL" in message
    assert "GHUS_AGENT_CONTACT_EMAIL" in message
    assert "ANTHROPIC_API_KEY" not in message
    assert "secret-value" not in message


def test_code_imports_real_src_ml_package_casing_without_alias():
    checked_roots = [
        PROJECT_ROOT / "agents",
        PROJECT_ROOT / "scripts",
        PROJECT_ROOT / "src",
    ]
    offenders = []
    for root in checked_roots:
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), 1):
                if "src.ml" in line:
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{lineno}:{line}")

    assert offenders == []
    src_init = (PROJECT_ROOT / "src" / "__init__.py").read_text(encoding="utf-8")
    assert "sys.modules.setdefault" not in src_init


def test_agent_sql_contains_weekly_run_schema_changes():
    sql_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((PROJECT_ROOT / "agents" / "sql").glob("*.sql"))
    )

    assert "CREATE TABLE IF NOT EXISTS scrape_run" in sql_text
    assert "CREATE TABLE IF NOT EXISTS raw_document" in sql_text
    assert "CREATE TABLE IF NOT EXISTS staged_record" in sql_text
    assert "ADD COLUMN IF NOT EXISTS storage_path" in sql_text
    assert "ADD COLUMN IF NOT EXISTS sector_match" in sql_text
    assert "ADD COLUMN IF NOT EXISTS status_reason" in sql_text
    assert "CREATE TABLE IF NOT EXISTS index_dirty" in sql_text
    assert "CREATE TABLE IF NOT EXISTS event_review_queue" in sql_text
    assert "CREATE TABLE IF NOT EXISTS person_review_queue" in sql_text
    assert "CREATE TABLE IF NOT EXISTS search_candidate" in sql_text


def test_out_of_sector_index_filters_on_sector_match():
    migration = (PROJECT_ROOT / "agents" / "sql" / "080_stage_sector_match_index.sql").read_text(
        encoding="utf-8"
    )

    assert "WHERE sector_match = 'out_of_sector'" in migration
    assert "WHERE status = 'out_of_sector'" not in migration.split("DROP INDEX", 1)[-1]
