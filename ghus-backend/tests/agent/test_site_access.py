"""An organisation whose website refuses the agent: recorded, respected, read elsewhere.

Modelled on University of Arizona Mining & Geological Engineering (2026-10-21):
``mge.engineering.arizona.edu`` and ``www.arizona.edu`` answer 403, while the
College of Engineering site links to the department's own page.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from agents.collection.light_pull_reader import LightPullReader
from agents.collection.site_access import (
    BlockedSites,
    Fallback,
    distinct_terms,
    failure_of,
    names_this_organisation,
    source_type,
)
from agents.discovery.sources.base import FetchedDoc

NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)
NAME = "University of Arizona Mining & Geological Engineering"
SITE = "https://mge.engineering.arizona.edu"
COLLEGE = "https://engineering.arizona.edu/"
MAJOR = "https://engineering.arizona.edu/majors/mining"
NEWS = "https://news.engineering.arizona.edu/news/doe-award-mining"

PAGES = {
    COLLEGE: ('<a href="/majors/mining">UA Mining Engineering</a>'
              '<a href="https://news.engineering.arizona.edu/news/doe-award-mining">Mining '
              'research award</a><a href="/about">About the college</a>'
              '<p>The College of Engineering has 4,000 students.</p>'),
    MAJOR: ("<p>The Department of Mining and Geological Engineering prepares engineers for "
            "mineral resources. The department leads the Lowell Institute for Mineral "
            "Resources partnership.</p>"),
    # Names mining, not the department: about the college, not this organisation.
    NEWS: "<p>A $20M DOE award speeds mining research across the college.</p>",
}


def _status(url, code):
    request = httpx.Request("GET", url)
    return httpx.HTTPStatusError(f"Client error '{code}' for url '{url}'", request=request,
                                 response=httpx.Response(code, request=request))


def _fetch_factory(refuse=frozenset({"mge.engineering.arizona.edu", "www.arizona.edu",
                                     "arizona.edu"}), calls=None):
    def fetch(url):
        if calls is not None:
            calls.append(url)
        host = httpx.URL(url).host
        if host in refuse:
            raise _status(url, 403)
        if url not in PAGES:
            raise _status(url, 404)
        return FetchedDoc.from_content(url=url, content=PAGES[url], content_type="text/html")
    return fetch


class Model:
    def __init__(self, answers):
        self.answers = answers

    def extract_with_tool(self, **kwargs):
        self.kwargs = kwargs
        return self.answers


@pytest.fixture
def blocked(tmp_path):
    clock = {"now": NOW}
    return BlockedSites(tmp_path / "blocked.json", now=lambda: clock["now"]), clock


@pytest.mark.parametrize(("make", "kind", "words"), [
    (lambda: _status(SITE, 403), "forbidden", "refuses automated access"),
    (lambda: _status(SITE, 401), "forbidden", "refuses automated access"),
    (lambda: _status(SITE, 429), "rate_limited", "slow down"),
    (lambda: httpx.ReadTimeout("timed out"), "timeout", "too long"),
    (lambda: httpx.ConnectError("[Errno 11001] getaddrinfo failed"), "unreachable", "reached"),
    (lambda: RuntimeError(f"robots.txt disallows fetching {SITE}"), "robots", "respect"),
    (lambda: _status(SITE, 404), "not_found", "no longer exists"),
])
def test_every_refusal_is_named_in_plain_words(make, kind, words):
    failure = failure_of(make())
    assert failure["kind"] == kind
    assert words in failure["plain"]
    assert "HTTPStatusError" not in failure["plain"] and "Errno" not in failure["plain"]


def test_a_refusing_host_is_left_alone_for_its_cooldown(blocked):
    store, clock = blocked
    store.record(SITE, failure_of(_status(SITE, 403)))
    assert store.blocked(f"{SITE}/about")["kind"] == "forbidden"
    clock["now"] = NOW + timedelta(days=15)
    assert store.blocked(SITE) is None                         # tried again after 14 days
    store.record(SITE, failure_of(_status(SITE, 429)))
    clock["now"] += timedelta(hours=25)
    assert store.blocked(SITE) is None                         # 429: after a day
    store.record(SITE, failure_of(_status(SITE, 404)))         # a missing page is no refusal
    assert store.blocked(SITE) is None


def test_the_organisation_is_named_by_its_own_words_not_its_parents():
    assert distinct_terms(NAME, SITE) == ["mining", "geological"]
    assert names_this_organisation(PAGES[MAJOR], ["mining", "geological"])
    assert not names_this_organisation(PAGES[NEWS], ["mining", "geological"])
    assert source_type(MAJOR, SITE) == "official_parent"
    assert source_type("https://www.nsf.gov/awards/1", SITE) == "government"
    assert source_type("https://en.wikipedia.org/wiki/X", SITE) == "third_party"


def test_a_refused_site_is_read_through_its_parents_pages_that_name_it(blocked):
    store, _clock = blocked
    calls = []
    model = Model({
        "parent_and_center_type": {"stated": True, "page": MAJOR,
                                   "value": {"center_type": "academic department",
                                             "parent_organization": "College of Engineering"},
                                   "quotes": ["The Department of Mining and Geological Engineering"]},
        "relevant_centers_programs": {"stated": True, "page": MAJOR,
                                      "value": {"names": ["Lowell Institute for Mineral Resources"]},
                                      "quotes": ["The department leads the Lowell Institute for "
                                                 "Mineral Resources partnership."]},
    })
    reader = LightPullReader(model, _fetch_factory(calls=calls),
                             fallback=Fallback(blocked=store, search=None))
    read = reader.read(name=NAME, website=SITE, actor_category="university_academic",
                       read_at=NOW, fields=["relevant_centers_programs", "parent_and_center_type"])
    assert read.pages == [MAJOR]
    assert read.sources == {MAJOR: "official_parent"}
    found = read.evidence["relevant_centers_programs"]
    assert found["collection_state"] == "found"
    assert found["source_type"] == "official_parent" and found["confidence"] == "high"
    assert found["quotes"] and found["source_url"] == MAJOR
    # The college's page did not name the department; its parent's centre-type
    # answer quoted only the department name, which does not state "College of
    # Engineering": that part is dropped, never kept as a guess.
    assert "College of Engineering" not in str(read.evidence["parent_and_center_type"].get("value"))
    outcomes = [(a["url"], a["outcome"]) for a in read.attempts]
    assert (SITE, "refused") in outcomes
    assert len(calls) == 3 and NEWS not in calls
    assert (MAJOR, "used") in outcomes
    # The model is told which pages are not its own site.
    assert "not the organisation's own website" in model.kwargs["system"]
    # A second update does not knock on the refusing host again.
    calls.clear()
    LightPullReader(model, _fetch_factory(calls=calls),
                    fallback=Fallback(blocked=store, search=None)).read(
        name=NAME, website=SITE, actor_category="university_academic", read_at=NOW,
        fields=["relevant_centers_programs"])
    assert not any("mge.engineering" in url for url in calls)
    assert len(calls) <= 3


@dataclass
class Result:
    url: str


def test_one_web_search_only_when_the_parent_site_gives_nothing(blocked):
    store, _clock = blocked
    searches = []
    gov = "https://www.nsf.gov/awardsearch/mining-geological"
    PAGES[gov] = "<p>NSF award to the Mining and Geological Engineering department, $1.2M.</p>"

    def search(query):
        searches.append(query)
        return [Result("https://www.linkedin.com/company/x"), Result(gov)]

    refuse = {"mge.engineering.arizona.edu", "engineering.arizona.edu", "www.arizona.edu",
              "arizona.edu"}
    fallback = Fallback(blocked=store, search=search, max_searches=1)
    read = LightPullReader(Model({}), _fetch_factory(refuse=refuse), fallback=fallback).read(
        name=NAME, website=SITE, actor_category="university_academic", read_at=NOW,
        fields=["funding_signal"])
    assert searches == ['"University of Arizona Mining & Geological Engineering" arizona']
    assert read.sources == {gov: "government"}       # social sites are never sources
    # A government page's facts are medium confidence, not high.
    assert len(searches) == 1


@pytest.mark.parametrize("make", [
    lambda url: _status(url, 403), lambda url: _status(url, 429),
    lambda url: httpx.ReadTimeout("timed out"),
])
def test_nothing_open_anywhere_says_so_plainly(blocked, make):
    store, _clock = blocked

    def fetch(url):
        raise make(url)

    read = LightPullReader(Model({}), fetch, fallback=Fallback(blocked=store)).read(
        name=NAME, website=SITE, actor_category="university_academic", read_at=NOW,
        fields=["funding_signal"])
    assert read.pages == [] and read.evidence == {}
    assert "No other source open to the agent names it." in read.error
    assert "Error" not in read.error and "http" not in read.error


def test_a_page_shown_only_through_scripts_is_recorded_and_read_elsewhere(blocked):
    store, _clock = blocked
    PAGES["https://mge.engineering.arizona.edu/"] = "<script>render()</script>"

    def fetch(url):
        if url.startswith("https://mge.engineering.arizona.edu"):
            return FetchedDoc.from_content(url="https://mge.engineering.arizona.edu/",
                                           content="<script>render()</script>",
                                           content_type="text/html")
        return _fetch_factory()(url)

    read = LightPullReader(Model({}), fetch, fallback=Fallback(blocked=store)).read(
        name=NAME, website=SITE, actor_category="university_academic", read_at=NOW,
        fields=["funding_signal"])
    assert store.blocked(SITE)["kind"] == "no_text"
    assert read.sources == {MAJOR: "official_parent"}


DEGREE = "https://engineering.arizona.edu/majors/mining-degree"
DEGREE_HTML = ("<html><head><title>UA Mining Engineering Degree | University of Arizona College "
               "of Engineering</title></head><body><p>The mining engineering major has four "
               "tracks: Mine Operations, Geomechanics, Sustainable Resource Development and "
               "Mineral Processing.</p></body></html>")


def test_a_parent_page_titled_with_part_of_its_name_is_used_at_medium_confidence(blocked):
    """The real case: its degree page never writes "Geological"."""
    from agents.collection.site_access import identity

    store, _clock = blocked
    terms = distinct_terms(NAME, SITE)
    assert identity(DEGREE_HTML, "mining engineering tracks", terms) == "partial"
    assert identity("<p>mining</p>", "mining research", terms) is None      # no title naming it
    college = ('<a href="/majors/mining-degree">UA Mining Engineering</a>'
               '<p>The College of Engineering.</p>')

    def fetch(url):
        if url == COLLEGE:
            return FetchedDoc.from_content(url=url, content=college, content_type="text/html")
        if url == DEGREE:
            return FetchedDoc.from_content(url=url, content=DEGREE_HTML, content_type="text/html")
        raise _status(url, 403)

    model = Model({"relevant_centers_programs": {
        "stated": True, "page": DEGREE, "value": {"names": ["Mineral Processing"]},
        "quotes": ["Sustainable Resource Development and Mineral Processing."]}})
    read = LightPullReader(model, fetch, fallback=Fallback(blocked=store)).read(
        name=NAME, website=SITE, actor_category="university_academic", read_at=NOW,
        fields=["relevant_centers_programs"])
    assert read.sources == {DEGREE: "official_parent"}
    assert read.evidence["relevant_centers_programs"]["confidence"] == "medium"
    used = next(a for a in read.attempts if a["outcome"] == "used")
    assert used["identity"] == "partial" and "medium confidence" in used["plain"]


def test_a_partial_name_never_counts_off_its_parents_site(blocked):
    store, _clock = blocked
    other = "https://www.minesites.example/ua-mining"

    def fetch(url):
        if url == other:
            return FetchedDoc.from_content(url=url, content=DEGREE_HTML, content_type="text/html")
        raise _status(url, 403)

    read = LightPullReader(Model({}), fetch, fallback=Fallback(
        blocked=store, search=lambda q: [Result(other)])).read(
        name=NAME, website=SITE, actor_category="university_academic", read_at=NOW,
        fields=["funding_signal"])
    assert read.pages == []
    assert any(a["url"] == other and a["outcome"] == "not_about_it" for a in read.attempts)


def test_failed_requests_exhaust_the_same_fetch_budget():
    from agents.collection.site_access import BoundedFetch, FetchLimitReached

    calls = []

    def fail(url):
        calls.append(url)
        raise _status(url, 403)

    fetch = BoundedFetch(fail)
    for _ in range(3):
        with pytest.raises(httpx.HTTPStatusError):
            fetch(SITE)
    with pytest.raises(FetchLimitReached):
        fetch(COLLEGE)
    assert len(calls) == 3 and fetch.remaining == 0
