"""The Deep Pull reader: selected Deep boxes, read and checked like the Light Pull."""

from __future__ import annotations

from datetime import UTC, datetime

from agents.collection.deep_pull import DEEP_FIELDS, DeepPullRequest, validate_deep_request
from agents.collection.deep_pull_reader import (
    DEEP_FIELD_CRITERIA,
    MAX_DEEP_FIELDS,
    DeepPullReader,
    deep_schema,
    select_fields,
)
from agents.discovery.sources.base import FetchedDoc

NOW = datetime(2026, 10, 26, tzinfo=UTC)
HOME = ('<html><head><title>The Water Council</title></head><body>'
        '<a href="/about-us/">About</a><a href="/working-groups/">Working groups</a>'
        '<p>The Water Council connects 150 members in Milwaukee, Wisconsin.</p></body></html>')
ABOUT = '<p>The Water Council publishes the Water Technology Report 2026 every spring.</p>'
GROUPS = '<p>Its Smart Water Working Group sets data standards for utilities.</p>'
PAGES = {
    "https://thewatercouncil.com/": HOME,
    "https://thewatercouncil.com/about-us/": ABOUT,
    "https://thewatercouncil.com/working-groups/": GROUPS,
}
ABOUT_URL = "https://thewatercouncil.com/about-us/"
GROUPS_URL = "https://thewatercouncil.com/working-groups/"


def _fetch(url):
    if url not in PAGES:
        raise RuntimeError(f"not found: {url}")
    return FetchedDoc.from_content(url=url, content=PAGES[url], content_type="text/html")


class Model:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def extract_with_tool(self, **kwargs):
        self.calls.append(kwargs)
        return self.answers


def test_every_deep_box_has_a_written_criterion():
    keys = {k for fields in DEEP_FIELDS.values() for k in fields}
    assert keys == set(DEEP_FIELD_CRITERIA)
    assert all(text.strip() for text in DEEP_FIELD_CRITERIA.values())


def test_selection_is_never_exhaustive_and_takes_empty_boxes_first():
    for category, schema in DEEP_FIELDS.items():
        chosen = select_fields(category, {})
        assert 0 < len(chosen) <= MAX_DEEP_FIELDS and len(chosen) < len(schema)
        # What the Phase 10 writer accepts.
        validate_deep_request(DeepPullRequest(
            actor_id="11111111-1111-1111-1111-111111111111",
            topic_id="22222222-2222-2222-2222-222222222222", actor_category=category,
            selected_fields=tuple(chosen), requested_by="test",
            request_id="33333333-3333-3333-3333-333333333333"))
    filled = {"relevant_products": {"collection_state": "found", "retrieved_at": "2026-10-01"}}
    chosen = select_fields("company", filled)
    assert "relevant_products" not in chosen
    # A box a person asks for comes first, recorded or not; unknown ones are ignored.
    assert select_fields("company", filled, wanted=["relevant_products", "nope"])[0] \
        == "relevant_products"
    assert select_fields("no_such_category", {}) == [] and deep_schema(None) == []


def test_the_deep_reader_asks_only_the_selected_boxes_and_checks_every_quote():
    model = Model({
        "working_groups_standards": {
            "stated": True, "page": GROUPS_URL, "value": "Smart Water Working Group (data "
            "standards for utilities)",
            "quotes": ["Its Smart Water Working Group sets data standards for utilities."]},
        # Invented: the quote is on no page.
        "key_reports": {"stated": True, "page": ABOUT_URL, "value": "Global Water Atlas 2025",
                        "quotes": ["publishes the Global Water Atlas 2025"]},
    })
    fields = ["working_groups_standards", "key_reports"]
    read = DeepPullReader(model, _fetch).read(
        name="The Water Council", website="https://thewatercouncil.com/",
        actor_category="association_network", topic_terms=["Water technology"],
        read_at=NOW, fields=fields)
    call = model.calls[0]
    assert call["tool_name"] == "fill_deep_pull_boxes"
    assert "Deep Pull" in call["system"] and "selected" in call["system"]
    assert call["input_schema"]["required"] == fields
    assert call["input_schema"]["properties"]["key_reports"]["description"].startswith(
        DEEP_FIELD_CRITERIA["key_reports"])
    assert set(read.evidence) == set(fields)
    assert read.evidence["working_groups_standards"]["collection_state"] == "found"
    assert read.evidence["key_reports"]["collection_state"] == "not_found"
    assert "not on the page" in read.rejected["key_reports"]
    assert len(read.pages) <= 3
