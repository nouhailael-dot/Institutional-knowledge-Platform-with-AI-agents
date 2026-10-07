"""Architecture V2: open-web actors carry the topic they were found for."""

from __future__ import annotations

from agents.discovery.search.phase2 import _with_found_for_topic
from agents.discovery.search.run import _candidate_topics
from agents.discovery.sources.base import FetchedDoc

WATER = {"topic_id": "11111111-1111-1111-1111-111111111111", "code": "WATER",
         "hub_name": "Texas Water Systems Hub"}


def test_found_for_topic_is_strong_when_the_page_evidences_it():
    record = _with_found_for_topic({"name": "Fort Worth Water Lab"},
                                   {"candidate_topics": {"https://x.org": WATER}},
                                   "https://x.org", ("WATER",))
    assert record["topic_id"] == WATER["topic_id"]
    assert record["match_strength"] == "strong"
    assert "Texas Water Systems Hub" in record["match_reason"]


def test_found_for_topic_is_moderate_without_page_evidence_and_absent_without_a_hub():
    context = {"candidate_topics": {"https://x.org": WATER}}
    assert _with_found_for_topic({"name": "A"}, context, "https://x.org", ("SUSTAIN",))[
        "match_strength"] == "moderate"
    assert "topic_id" not in _with_found_for_topic({"name": "A"}, context, "https://y.org", ())
    assert _with_found_for_topic(None, context, "https://x.org", ()) is None


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _Session:
    def execute(self, statement, params=None):
        sql = str(statement)
        if "to_regclass" in sql:
            return _Rows([{"present": True}])
        return _Rows([{"name": "Texas Water Systems Hub", "topic_id": WATER["topic_id"],
                       "code": "WATER"}])


def test_candidate_topic_comes_from_the_hub_the_query_targeted():
    topics = _candidate_topics(_Session(), {
        "https://x.org": ("Texas Water Systems Hub",),
        "https://y.org": ("Unknown Hub",),
    })
    assert topics == {"https://x.org": WATER}
    assert _candidate_topics(None, {"https://x.org": ("Texas Water Systems Hub",)}) == {}


def test_fetched_content_drops_nul_bytes_before_hashing():
    doc = FetchedDoc.from_content(url="https://x.org/report.pdf", content="water\x00 report")
    assert doc.content == "water report"
    assert doc.content_hash == FetchedDoc.from_content(url="u", content="water report").content_hash
