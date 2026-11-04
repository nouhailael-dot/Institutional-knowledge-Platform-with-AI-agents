"""The Light Pull reader: every box answered, nothing invented, three pages at most."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agents.collection.light_pull import CATEGORY_LIGHT_FIELDS, run_light_pull
from agents.collection.light_pull_reader import (
    COMMON_READ_FIELDS,
    FIELD_CRITERIA,
    LightPullReader,
    choose_pages,
    light_criteria_rows,
    quote_on_page,
)
from agents.discovery.sources.base import FetchedDoc

NOW = datetime(2026, 10, 15, tzinfo=UTC)
TOPIC_ID = "11111111-1111-1111-1111-111111111111"

HOME = ('<html><head><title>The Water Council</title></head><body>'
        '<a href="/about-us/">About</a><a href="/programs/brew/">BREW accelerator</a>'
        '<a href="/water-technology/">Water technology</a><a href="/donate">Donate</a>'
        '<p>The Water Council connects 150 members in Milwaukee, Wisconsin.</p></body></html>')
ABOUT = ('<p>The Water Council is a 501(c)(3) nonprofit in Milwaukee, Wisconsin. In March 2026 '
         'it launched BREW 2.0, a global accelerator for water technology startups. '
         'It received a $2 million grant from the Fund for Lake Michigan.</p>')
TOPIC = '<p>Members include A. O. Smith, Badger Meter and Veolia.</p>'
PAGES = {
    "https://thewatercouncil.com/": HOME,
    "https://thewatercouncil.com/about-us/": ABOUT,
    "https://thewatercouncil.com/water-technology/": TOPIC,
    "https://thewatercouncil.com/programs/brew/": "<p>BREW</p>",
}
fetched: list[str] = []


def _fetch(url):
    fetched.append(url)
    if url not in PAGES:
        raise RuntimeError(f"not found: {url}")
    return FetchedDoc.from_content(url=url, content=PAGES[url], content_type="text/html")


class Model:
    """Answers like the model would; one answer is invented, one breaks a rule."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = 0

    def extract_with_tool(self, **kwargs):
        self.calls += 1
        self.schema = kwargs["input_schema"]
        return self.answers


ABOUT_URL = "https://thewatercouncil.com/about-us/"
TOPIC_URL = "https://thewatercouncil.com/water-technology/"


def test_every_criterion_is_written_down_for_every_box():
    for category, fields in CATEGORY_LIGHT_FIELDS.items():
        for key in (*COMMON_READ_FIELDS, *fields):
            assert FIELD_CRITERIA[key].strip(), key
        assert [k for k, _ in light_criteria_rows(category)][:len(COMMON_READ_FIELDS)] \
            == list(COMMON_READ_FIELDS)


def test_three_pages_at_most_home_about_and_the_topic_page():
    fetched.clear()
    docs = choose_pages(_fetch, "https://thewatercouncil.com", topic_terms=["Water technology"],
                        actor_category="association_network")
    assert [d.url for d in docs] == ["https://thewatercouncil.com/", ABOUT_URL, TOPIC_URL]
    assert len(fetched) == 3


def test_every_box_is_answered_and_only_checked_quotes_count():
    model = Model({
        "recent_activity": {"stated": True, "page": ABOUT_URL,
                            "value": {"date": "March 2026",
                                      "description": "Launched BREW 2.0, a global accelerator."},
                            "quote": "In March 2026 it launched BREW 2.0, a global accelerator"},
        "funding_signal": {"stated": True, "page": ABOUT_URL,
                           "value": "$2 million grant from the Fund for Lake Michigan.",
                           "quote": "received a $2 million grant from the Fund for Lake Michigan"},
        # Invented: the quote is on no page.
        "international_connection": {"stated": True, "page": ABOUT_URL,
                                     "value": "Partner of a Singapore water hub.",
                                     "quote": "partners with the Singapore Water Exchange hub"},
        "linked_members": {"stated": True, "page": TOPIC_URL,
                           "value": "A. O. Smith, Badger Meter, Veolia",
                           "quote": "Members include A. O. Smith, Badger Meter and Veolia."},
        # Breaks the Light Pull rule: recent activity must be dated.
        "current_initiative_working_group": {"stated": False},
        "location": {"stated": True, "page": ABOUT_URL,
                     "value": {"city": "Milwaukee", "state": "Wisconsin", "country": None},
                     "quote": "nonprofit in Milwaukee, Wisconsin"},
    })
    read = LightPullReader(model, _fetch).read(
        name="The Water Council", website="https://thewatercouncil.com/",
        actor_category="association_network", topic_terms=["Water technology"], read_at=NOW)

    wanted = {*COMMON_READ_FIELDS, *CATEGORY_LIGHT_FIELDS["association_network"]}
    assert set(read.evidence) == wanted                      # every box has an answer
    assert set(model.schema["required"]) == wanted           # and every box was asked
    assert model.calls == 1
    states = {k: v["collection_state"] for k, v in read.evidence.items()}
    assert "not_yet_collected" not in states.values()
    assert states["recent_activity"] == states["funding_signal"] == "found"
    assert states["linked_members"] == "found"
    assert read.evidence["linked_members"]["source_url"] == TOPIC_URL
    # The invented answer is not evidence, and the reason is kept.
    assert states["international_connection"] == "not_found"
    assert "not on the page" in read.rejected["international_connection"]
    # Not stated: recorded as not found on the pages that were read.
    assert states["um6p_ocp_connection"] == "not_found"
    assert read.pages == ["https://thewatercouncil.com/", ABOUT_URL, TOPIC_URL]


def test_an_answer_breaking_a_light_pull_rule_is_refused():
    model = Model({"recent_activity": {"stated": True, "page": ABOUT_URL,
                                       "value": {"date": "", "description": "Launched BREW 2.0"},
                                       "quote": "it launched BREW 2.0"}})
    read = LightPullReader(model, _fetch).read(
        name="The Water Council", website="https://thewatercouncil.com/",
        actor_category="association_network", read_at=NOW)
    assert read.evidence["recent_activity"]["collection_state"] == "not_found"
    assert "Light Pull rule" in read.rejected["recent_activity"]


def test_an_unreachable_site_reads_nothing_and_says_so():
    def down(url):
        raise RuntimeError("connection refused")

    model = Model({})
    read = LightPullReader(model, down).read(name="X", website="https://down.example/",
                                             actor_category="company", read_at=NOW)
    assert read.evidence == {} and model.calls == 0
    # Said plainly: no exception names, no status codes.
    assert read.error == ("Its website could not be reached (the address may be wrong, the "
                          "site down, or its security certificate broken).")


@pytest.mark.parametrize(("quote", "ok"), [
    ("In March 2026 it launched BREW 2.0", True),
    ("in march 2026 it LAUNCHED brew 2.0,", True),
    ("It opened an office in Casablanca", False),
])
def test_quotes_are_checked_against_the_page(quote, ok):
    assert quote_on_page(quote, ABOUT) is ok


def test_evidence_cannot_depend_on_a_quote_past_the_limit_that_would_be_discarded():
    # An entry box keeps eight quotes (several entries); a ninth would be discarded.
    model = Model({"funding_signal": {
        "stated": True, "page": ABOUT_URL, "value": {"amount": "$2 million"},
        "quotes": ["The Water Council"] * 8 + ["received a $2 million grant"],
    }})
    read = LightPullReader(model, _fetch).read(
        name="The Water Council", website="https://thewatercouncil.com",
        actor_category="association_network", read_at=NOW, fields=["funding_signal"])
    assert "funding_signal" in read.rejected
    assert read.evidence["funding_signal"]["collection_state"] != "found"


def test_promotion_uses_collected_boxes_but_the_reviewer_wins():
    evidence = {
        "description": {"collection_state": "found",
                        "value": "Agent-read description. It is long enough."},
        "funding_signal": {"collection_state": "found", "value": "$2 million grant.",
                           "source_url": ABOUT_URL},
        "um6p_ocp_connection": {"collection_state": "not_found", "value": None},
        # A box of another category: the reviewer changed the category.
        "linked_members": {"collection_state": "found", "value": "A, B"},
    }
    result = run_light_pull(
        payload={"name": "The Water Council", "website": "https://thewatercouncil.com/",
                 "description": "Reviewer-edited description of the council.",
                 "light_pull_evidence": evidence},
        actor_category="foundation_nonprofit", topic_id=TOPIC_ID,
        source_url="https://thewatercouncil.com/", date_read=NOW)
    facts = {f.field_key: f for f in result.facts}
    assert facts["description"].value == "Reviewer-edited description of the council."
    assert facts["funding_signal"].value == "$2 million grant."
    assert facts["um6p_ocp_connection"].collection_state == "not_found"
    assert "linked_members" not in facts


@pytest.mark.parametrize(("date", "accepted"), [
    ("October 2026", True), ("2025", True), ("November 2024", True),
    ("October 20, 2021", False),     # NEW Water's 2021 launch, read as "recent"
    ("recently", False),
    ("July 5, 2024", False),         # ExxonMobil, read October 2026: 27 months
    ("not specified, listed under October 2026 newsroom items", False),   # Chevron
])
def test_recent_activity_must_be_dated_and_recent(date, accepted):
    model = Model({"recent_activity": {
        "stated": True, "page": ABOUT_URL,
        "value": {"date": date, "description": "Launched BREW 2.0, a global accelerator."},
        "quote": "In March 2026 it launched BREW 2.0, a global accelerator"}})
    read = LightPullReader(model, _fetch).read(
        name="The Water Council", website="https://thewatercouncil.com/",
        actor_category="association_network", read_at=NOW)
    state = read.evidence["recent_activity"]["collection_state"]
    assert state == ("found" if accepted else "not_found")
    if not accepted:
        assert "recent" in read.rejected["recent_activity"]


def test_the_website_publishing_content_is_not_recent_activity():
    model = Model({"recent_activity": {
        "stated": True, "page": ABOUT_URL,
        "value": {"date": "March 2026", "description": "Published content on risk management"},
        "quote": "In March 2026 it launched BREW 2.0, a global accelerator"}})
    read = LightPullReader(model, _fetch).read(
        name="The Water Council", website="https://thewatercouncil.com/",
        actor_category="association_network", read_at=NOW)
    assert read.evidence["recent_activity"]["collection_state"] == "not_found"
    assert "website's content" in read.rejected["recent_activity"]


@pytest.mark.parametrize(("stated", "stored"), [
    ({"city": "Milwaukee", "state": "Wisconsin", "country": None},
     {"city": "Milwaukee", "state": "WI", "country": "US"}),
    ({"city": "Milwaukee", "state": "WI"}, {"city": "Milwaukee", "state": "WI", "country": "US"}),
    # Not a US state: kept as the page says it, never placed in the US.
    ({"city": "Toronto", "state": "Ontario", "country": "Canada"},
     {"city": "Toronto", "state": "Ontario", "country": "Canada"}),
])
def test_a_location_is_stored_in_one_shape(stated, stored):
    model = Model({"location": {"stated": True, "page": ABOUT_URL, "value": stated,
                                "quote": "nonprofit in Milwaukee, Wisconsin"}})
    read = LightPullReader(model, _fetch).read(
        name="The Water Council", website="https://thewatercouncil.com/",
        actor_category="association_network", read_at=NOW, fields=["location"])
    assert read.evidence["location"]["value"] == stored


CORP = {
    "https://corp.example/": ('<a href="/what-we-do/energy">Energy</a>'
                              '<a href="/contact-us">Contact us</a><p>Energy for the world.</p>'),
    "https://corp.example/what-we-do/energy": "<p>Oil, gas and lower carbon energy.</p>",
    "https://corp.example/contact-us": "<p>Headquarters: 1 Main St, Houston, TX 77002</p>",
}


def _corp_fetch(url):
    fetched.append(url)
    if url not in CORP:
        raise RuntimeError(f"not found: {url}")
    return FetchedDoc.from_content(url=url, content=CORP[url], content_type="text/html")


def test_a_free_third_page_goes_to_the_contact_page_when_the_location_is_asked():
    fetched.clear()
    docs = choose_pages(_corp_fetch, "https://corp.example", topic_terms=["energy"],
                        actor_category="company", want_location=True)
    assert [d.url for d in docs] == ["https://corp.example/",
                                     "https://corp.example/what-we-do/energy",
                                     "https://corp.example/contact-us"]
    # Not asked for the location: the same two pages, nothing more fetched.
    docs = choose_pages(_corp_fetch, "https://corp.example", topic_terms=["energy"],
                        actor_category="company")
    assert len(docs) == 2


def test_no_contact_page_is_read_when_a_page_already_states_an_address():
    docs = choose_pages(_fetch, "https://thewatercouncil.com", topic_terms=["Water technology"],
                        actor_category="association_network", want_location=True)
    assert len(docs) == 3 and docs[-1].url == TOPIC_URL


class _Hit:
    def __init__(self, url):
        self.url = url


class _TwoReads:
    """First call: the own pages state no funding. Second: the funder's page does."""

    def __init__(self, second):
        self.answers = [{"funding_signal": {"stated": False}}, second]
        self.calls = []

    def extract_with_tool(self, **kwargs):
        self.calls.append(kwargs)
        return self.answers[min(len(self.calls), len(self.answers)) - 1]


def _searching_fallback(tmp_path, hits, searches):
    from agents.collection.site_access import BlockedSites, Fallback

    def search(query):
        searches.append(query)
        return [_Hit(u) for u in hits]
    return Fallback(blocked=BlockedSites(tmp_path / "blocked.json"), search=search, max_searches=1)


FUNDER = "https://fundforlakemichigan.org/grants-2026"


def test_funding_its_own_pages_do_not_state_is_searched_for_and_checked(tmp_path, monkeypatch):
    monkeypatch.setitem(PAGES, FUNDER, "<p>The Fund awarded The Water Council a $500,000 grant "
                                       "in 2026 for its BREW accelerator.</p>")
    monkeypatch.setitem(PAGES, "https://www.linkedin.com/company/x", "<p>The Water Council</p>")
    searches: list[str] = []
    model = _TwoReads({"funding_signal": {
        "stated": True, "page": FUNDER, "value": "$500,000 grant, 2026",
        "quote": "The Fund awarded The Water Council a $500,000 grant in 2026"}})
    read = LightPullReader(model, _fetch, fallback=_searching_fallback(
        tmp_path, ["https://www.linkedin.com/company/x", FUNDER], searches)).read(
        name="The Water Council", website="https://thewatercouncil.com", actor_category=None,
        read_at=NOW, fields=["funding_signal"])
    assert searches == ['"The Water Council" grant OR award OR funding OR funded OR raised']
    box = read.evidence["funding_signal"]
    assert box["collection_state"] == "found" and box["source_url"] == FUNDER
    # Another site than its own: medium confidence, and the page is listed as read.
    assert box["confidence"] == "medium" and box["source_type"] == "third_party"
    assert FUNDER in read.pages and len(model.calls) == 2


def test_a_search_result_that_does_not_name_it_is_never_read_for_it(tmp_path, monkeypatch):
    other = "https://example.org/water-news"
    # "Water" alone is its only distinct word: a page about another water body is not about it.
    monkeypatch.setitem(PAGES, other, "<p>A $3 million grant went to Milwaukee Water Works.</p>")
    model = _TwoReads({"funding_signal": {"stated": True, "page": other, "value": "$3 million",
                                          "quote": "A $3 million grant"}})
    read = LightPullReader(model, _fetch, fallback=_searching_fallback(tmp_path, [other], [])).read(
        name="The Water Council", website="https://thewatercouncil.com", actor_category=None,
        read_at=NOW, fields=["funding_signal"])
    assert read.evidence["funding_signal"]["collection_state"] == "not_found"
    assert len(model.calls) == 1 and other not in read.pages


def test_no_search_when_its_own_pages_state_it(tmp_path):
    searches: list[str] = []
    model = Model({"funding_signal": {
        "stated": True, "page": ABOUT_URL, "value": "$2 million grant from the Fund for Lake Michigan.",
        "quote": "received a $2 million grant from the Fund for Lake Michigan"}})
    read = LightPullReader(model, _fetch, fallback=_searching_fallback(tmp_path, [FUNDER], searches)).read(
        name="The Water Council", website="https://thewatercouncil.com", actor_category=None,
        read_at=NOW, fields=["funding_signal"])
    assert read.evidence["funding_signal"]["collection_state"] == "found" and searches == []



def test_an_entry_box_keeps_every_quoted_entry_and_refuses_one_riding_on_another_quote():
    model = Model({"funding_signal": {
        "stated": True, "page": ABOUT_URL,
        "value": [{"amount": "$2 million", "funder": "Fund for Lake Michigan"},
                  {"amount": "$5 million", "funder": "National Science Foundation"}],
        "quotes": ["It received a $2 million grant from the Fund for Lake Michigan."]}})
    read = LightPullReader(model, _fetch).read(
        name="The Water Council", website="https://thewatercouncil.com",
        actor_category="association_network", read_at=NOW, fields=["funding_signal"])
    value = read.evidence["funding_signal"]["value"]
    assert value == {"entries": [{"amount": "$2 million", "funder": "Fund for Lake Michigan"}]}
    assert read.evidence["funding_signal"]["dropped_entries"]


PARENT = {
    "https://www.bighealth.org/": ('<title>Big Health System</title><a href="/about">About</a>'
                                   '<p>Big Health System serves Greater Boston.</p>'),
    "https://www.bighealth.org/about": ('<p>Big Health System has 20 hospitals across '
                                        'Massachusetts. The Big Health Innovation Fund invests '
                                        '$1 million in digital health startups.</p>'),
}


def test_on_a_parents_site_only_facts_whose_quotes_name_the_unit_are_kept():
    def fetch(url):
        if url not in PARENT:
            raise RuntimeError(f"not found: {url}")
        return FetchedDoc.from_content(url=url, content=PARENT[url], content_type="text/html")

    model = Model({
        "geographic_focus": {"stated": True, "page": "https://www.bighealth.org/about",
                             "value": {"places": ["Massachusetts"]},
                             "quotes": ["Big Health System has 20 hospitals across Massachusetts."]},
        "published_fund_size": {"stated": True, "page": "https://www.bighealth.org/about",
                                "value": {"amount": "$1 million"},
                                "quotes": ["The Big Health Innovation Fund invests $1 million in "
                                           "digital health startups."]}})
    read = LightPullReader(model, fetch).read(
        name="Big Health Innovation Fund", website="https://www.bighealth.org/",
        actor_category="investor", read_at=NOW,
        fields=["geographic_focus", "published_fund_size"])
    assert read.evidence["geographic_focus"]["collection_state"] == "not_found"
    assert "parent" in read.rejected["geographic_focus"]
    assert read.evidence["published_fund_size"]["collection_state"] == "found"


def test_an_unreachable_address_is_tried_under_its_other_spelling():
    from agents.collection.light_pull_reader import address_variants

    assert address_variants("http://example.org/") == ["https://www.example.org/",
                                                       "https://example.org/"]
    assert address_variants("https://www.example.org") == ["https://example.org/"]

    def fetch(url):
        if url.startswith("https://www.thewatercouncil.com"):
            return _fetch(url.replace("https://www.", "https://"))
        raise RuntimeError("ConnectError: getaddrinfo failed")

    read = LightPullReader(Model({}), fetch).read(
        name="The Water Council", website="https://thewatercouncil.com/",
        actor_category="association_network", read_at=NOW, fields=["um6p_ocp_connection"])
    assert read.error is None and read.pages


def test_a_news_or_funding_page_is_read_beside_home_about_and_topic():
    site = {
        "https://lab.example/": ('<title>Lab Example</title><a href="/about">About</a>'
                                 '<a href="/research">Research</a><a href="/news">News</a>'
                                 '<a href="/funding">Funding</a><p>Lab Example.</p>'),
        "https://lab.example/about": "<p>About Lab Example.</p>",
        "https://lab.example/research": "<p>Water research.</p>",
        "https://lab.example/news": "<p>In 2026 Lab Example won a $1M award.</p>",
        "https://lab.example/funding": "<p>Funded by NSF.</p>",
    }

    def fetch(url):
        return FetchedDoc.from_content(url=url, content=site[url], content_type="text/html")

    docs = choose_pages(fetch, "https://lab.example", topic_terms=["water research"],
                        actor_category="research_center")
    urls = [d.url for d in docs]
    assert urls[:3] == ["https://lab.example/", "https://lab.example/about",
                        "https://lab.example/research"]
    assert "https://lab.example/news" in urls and len(urls) <= 5
