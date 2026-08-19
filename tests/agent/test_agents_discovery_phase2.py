from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from agents.common.raw_storage import RawContentStore
from agents.common.run_log import InMemoryRunLog
from agents.discovery.extractors.event import EventExtractor
from agents.discovery.run import run_pipeline
from agents.discovery.sources.base import FetchedDoc
from agents.discovery.stage import InMemoryStageStore

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "agents"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


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


class NetworkUnavailableSource:
    name = "climate_week"
    entity_types = ("event",)
    rate_limit_s = 0.0

    def discover(self):
        raise AssertionError("replay must not discover URLs")

    def fetch(self, url: str):
        raise AssertionError("replay must not fetch from the network")


class CountingToolClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0
        self.usage = type("Usage", (), {"snapshot": lambda _: {"calls": self.calls, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}})()

    def extract_with_tool(self, **kwargs):
        self.calls += 1
        return self.payload


def fixture_payload():
    return json.loads((FIXTURE_ROOT / "climate_week_events.expected.json").read_text(encoding="utf-8"))


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
    }
    values.update(overrides)
    return Namespace(**values)


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
    seed_run_id = run_log.start_run(source_name="climate_week", entity_type="event", live=False, config={})
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
    assert client.calls == 0


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
        args(replay=first["run_id"], out=str(tmp_path / "replay.csv"), digest_out=str(tmp_path / "replay.md")),
        root=PROJECT_ROOT,
        run_log=run_log,
        stage_store=InMemoryStageStore(),
        source=NetworkUnavailableSource(),
        extractor=EventExtractor(replay_client),
        raw_store=raw_store,
    )

    assert routing_signature(replay) == routing_signature(first)
    assert replay_client.calls == first_client.calls
