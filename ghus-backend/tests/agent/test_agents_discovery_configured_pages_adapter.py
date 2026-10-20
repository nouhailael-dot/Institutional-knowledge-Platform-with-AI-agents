from __future__ import annotations

from pathlib import Path

import pytest

from agents.common.config import load_sources_config
from agents.discovery.run import SOURCE_ADAPTERS, build_source
from agents.discovery.sources.configured_pages import ConfiguredPagesAdapter

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_configured_pages_adapter_fetches_configured_file_url(tmp_path):
    page = tmp_path / "people.html"
    page.write_text(
        "<html><body><h1>Faculty</h1><h2>Pr. Sarah Alami</h2>"
        "<p>Assistant Professor</p></body></html>",
        encoding="utf-8",
    )
    url = page.as_uri()
    adapter = ConfiguredPagesAdapter(
        {
            "source_name": "tmp_people",
            "entity_types": ["person"],
            "seed_urls": [url],
        },
        project_root=PROJECT_ROOT,
    )

    assert list(adapter.discover()) == [url]
    doc = adapter.fetch(url)

    assert "Sarah Alami" in doc.content
    assert doc.meta["source_name"] == "tmp_people"
    assert doc.content_type == "text/html"


def test_build_source_loads_configured_adapter_without_registry_entry(tmp_path):
    page = tmp_path / "people.html"
    page.write_text("<html><body><h2>Pr. Fatima ZAMBA</h2></body></html>", encoding="utf-8")
    url = page.as_uri()
    config = {
        "sources": {
            "tmp_people": {
                "adapter": "agents.discovery.sources.configured_pages:ConfiguredPagesAdapter",
                "entity_types": ["person"],
                "seed_urls": [url],
            }
        }
    }

    source, source_config = build_source("tmp_people", config, PROJECT_ROOT)

    assert "tmp_people" not in SOURCE_ADAPTERS
    assert source_config["source_name"] == "tmp_people"
    assert source.name == "tmp_people"
    assert source.entity_types == ("person",)
    assert list(source.discover()) == [url]


def test_build_source_rejects_disabled_source(tmp_path):
    page = tmp_path / "people.html"
    page.write_text("<html><body><h2>Pr. Fatima ZAMBA</h2></body></html>", encoding="utf-8")
    config = {
        "sources": {
            "tmp_people": {
                "disabled": True,
                "disabled_reason": "personal-data approval pending",
                "adapter": "agents.discovery.sources.configured_pages:ConfiguredPagesAdapter",
                "entity_types": ["person"],
                "seed_urls": [page.as_uri()],
            }
        }
    }

    with pytest.raises(RuntimeError, match="personal-data approval pending"):
        build_source("tmp_people", config, PROJECT_ROOT)


def test_sources_config_keeps_sci_people_disabled_and_event_sources_event_only():
    config = load_sources_config(PROJECT_ROOT)
    sources = config["sources"]

    assert sources["sci_people"]["disabled"] is True
    assert "TARGETING_POLICY.md section 6" in sources["sci_people"]["disabled_reason"]
    for source_name in ("climate_week", "unga_programme", "unga_guide"):
        assert sources[source_name]["entity_types"] == ["event"]
