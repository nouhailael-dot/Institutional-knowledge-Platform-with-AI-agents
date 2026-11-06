"""Research quality (6 Nov 2026): funding status, targeted follow-ups, richer values
kept, duplicates, next editions, speaker leads and fresh searches."""

from __future__ import annotations

from datetime import UTC, datetime

from agents.collection.light_pull_reader import (
    FOLLOWUP_MIN_LEFT_USD,
    LightPullReader,
    completeness_of,
    followup_targets,
)
from agents.common.fact_parts import compare_values, entry_value, funding_status
from agents.common.resolve_route import _exact_actor_matches, is_acronym_pair, route_actor
from agents.discovery.search.discovery_request import theme_synonyms
from agents.discovery.search.followup import next_edition_urls, same_series, waiting_actor
from agents.discovery.search.people_targets import (
    official_profile_hit,
    speaker_leads,
    speaker_page,
)
from agents.discovery.search.query_generation import _fresh_first
from agents.discovery.sources.base import FetchedDoc

NOW = datetime(2026, 11, 6, tzinfo=UTC)


# ------------------------------------------------------------------ funding

def test_old_funding_is_kept_with_its_status_never_not_found():
    year = 2026
    assert funding_status({"date": "2022-2027"}, today_year=year) == "active"
    assert funding_status({"date": "ongoing since 2015"}, today_year=year) == "active"
    assert funding_status({"date": "2019-2024"}, today_year=year) == "recently_completed"
    assert funding_status({"date": "awarded 2024"}, today_year=year) == "recent_award"
    assert funding_status({"date": "2016"}, today_year=year) == "historical"
    assert funding_status({"amount": "$1M"}, today_year=year) == "undated"
    value = entry_value([{"amount": "$1M", "funder": "NSF", "date": "2016"},
                         {"amount": "$3M", "funder": "DOE", "date": "2024-2028"}],
                        key="funding_signal", today_year=year)
    # Every documented grant stays, active first, each keeping amount, funder and dates.
    assert [(e["funder"], e["status"]) for e in value["entries"]] == [
        ("DOE", "active"), ("NSF", "historical")]
    # Other entry boxes still keep only recent entries.
    recent = entry_value([{"description": "x", "date": "2016"}, {"description": "y",
                                                                 "date": "2026"}],
                         key="recent_activity", today_year=year)
    assert [e["description"] for e in recent["entries"]] == ["y"]


def test_the_status_never_makes_a_known_grant_look_new():
    before = {"entries": [{"amount": "$3M", "funder": "DOE", "date": "2024-2028",
                           "status": "active"}]}
    after = {"entries": [{"amount": "$3M", "funder": "DOE", "date": "2024-2028"}]}
    assert compare_values("funding_signal", before, after)["outcome"] == "corroborated"


# ------------------------------------------------------------------ updates

def test_a_shorter_reading_never_replaces_a_richer_recorded_value():
    richer = {"parent_organization": "U.S. Department of Energy Office of Science"}
    out = compare_values("parent_and_center_type", richer,
                         {"parent_organization": "Department of Energy"})
    assert out["outcome"] == "corroborated" and out["merged"] == richer
    longer = compare_values("parent_and_center_type", {"parent_organization": "Energy Office"},
                            {"parent_organization": "U.S. Department of Energy Office"})
    assert longer["outcome"] == "additional"
    text = compare_values("topic_research_focus",
                          "Develops membrane desalination and brine management for utilities",
                          "Develops membrane desalination")
    assert text["outcome"] == "corroborated"
    # A different figure is still a change.
    assert compare_values("ownership_and_size", {"employees": 500},
                          {"employees": 600})["outcome"] == "changed"


# ------------------------------------------------------------------ follow-ups

HOME = ('<a href="/about/">About</a><a href="/contact-us/">Contact</a>'
        '<a href="/news/">News</a><a href="/projects/">Our projects</a>')


def test_follow_up_pages_are_chosen_for_the_missing_boxes():
    home = FetchedDoc.from_content(url="https://lab.example/", content=HOME,
                                   content_type="text/html")
    assert followup_targets(home, "lab.example", {"https://lab.example"}, ["location"],
                            limit=1) == ["https://lab.example/contact-us/"]
    assert followup_targets(home, "lab.example", {"https://lab.example"},
                            ["active_recent_projects"], limit=1) == [
        "https://lab.example/projects/"]


def test_completeness_counts_the_categorys_essential_boxes():
    evidence = {"location": {"collection_state": "found"},
                "why_matched": {"collection_state": "not_found"},
                "parent_and_center_type": {"collection_state": "found"}}
    wanted = ["location", "why_matched", "parent_and_center_type", "topic_research_focus",
              "active_recent_projects", "funding_signal"]
    out = completeness_of(evidence, "research_center", wanted)
    assert out["found"] == ["location", "parent_and_center_type"]
    assert out["missing"] == ["why_matched", "topic_research_focus", "active_recent_projects"]
    assert out["share"] == 0.4


class _Meter:
    def __init__(self, spent, cap):
        self.spent_usd, self.max_usd = spent, cap


class _Client:
    def __init__(self, meter):
        self.cost_meter = meter
        self.calls = 0

    def extract_with_tool(self, **kwargs):
        self.calls += 1
        return {}


def test_follow_ups_stop_when_the_budget_is_reached():
    pages = {"https://lab.example/": HOME,
             "https://lab.example/about/": "<p>The Lab is a research centre.</p>",
             "https://lab.example/contact-us/": "<p>Tucson, Arizona</p>"}

    def fetch(url):
        if url not in pages:
            raise RuntimeError("not found")
        return FetchedDoc.from_content(url=url, content=pages[url], content_type="text/html")

    poor = _Client(_Meter(spent=1.0 - FOLLOWUP_MIN_LEFT_USD / 2, cap=1.0))
    read = LightPullReader(poor, fetch).read(
        name="The Lab", website="https://lab.example/", actor_category="research_center",
        read_at=NOW, fields=["location", "why_matched"])
    assert poor.calls == 1                                   # the first read only
    assert read.followups and read.followups[0]["stopped"] == "budget"
    rich = _Client(_Meter(spent=0.0, cap=1.0))
    read = LightPullReader(rich, fetch).read(
        name="The Lab", website="https://lab.example/", actor_category="research_center",
        read_at=NOW, fields=["location", "why_matched"])
    assert rich.calls == 2 and read.followups[0]["step"] == "own_site"
    assert read.completeness["essential"] == ["location", "why_matched"]


# ------------------------------------------------------------------ duplicates

class _NoResolver:
    HIGH, LOW = 0.9, 0.5

    def _candidates(self, name):
        import pandas as pd
        return pd.DataFrame(columns=["actor_id", "name"])


def test_an_acronym_or_a_unit_on_its_parents_site_goes_to_review_never_merged():
    lab = {"actor_id": "a1", "name": "National Renewable Energy Laboratory",
           "website": "https://www.nrel.gov", "alternate_names": []}
    acronym = route_actor({"name": "NREL", "website": "https://nrel.example"},
                          _NoResolver(), [lab])
    assert acronym.zone == "review" and acronym.metadata["match_rule"] == "acronym"
    assert is_acronym_pair("ASU", "Arizona State University")
    assert not is_acronym_pair("Asu", "Arizona State University")
    university = {"actor_id": "u1", "name": "Arizona State University",
                  "website": "https://www.asu.edu/", "alternate_names": []}
    unit = route_actor({"name": "ASU Water Innovation Center",
                        "website": "https://asu.edu/centers/water"}, _NoResolver(), [university])
    assert unit.zone == "review" and unit.metadata["match_rule"] == "same_site_other_unit"
    # The same organisation on its own site (any page of it) is still appended.
    same = _exact_actor_matches({"name": "Other Name", "website": "https://asu.edu/about"},
                                [university])
    assert same[0]["_match_rule"] == "website_domain"


def test_a_find_waiting_in_review_is_not_read_again():
    pending = [{"url": "https://www.asu.edu/", "website": "https://www.asu.edu",
                "name": "Arizona State University"}]
    assert waiting_actor("https://asu.edu/about", None, pending) is not None
    assert waiting_actor("https://asu.edu/centers/water", None, pending) is None
    assert waiting_actor("", "The Arizona State University", pending) is not None


# ------------------------------------------------------------------ events

def test_the_next_edition_is_looked_for_on_a_past_editions_page():
    html = ('<a href="/2027-summit">2027 Summit</a><a href="/recap">2025 recap</a>'
            '<a href="https://other.org/2027">elsewhere</a>')
    urls = next_edition_urls({"start_date": "2025-10-01"}, "https://watersummit.org/2025",
                             html, run_year=2026)
    assert urls == ["https://watersummit.org/2027-summit"]
    assert same_series("2025 Water Innovation Summit", "Water Innovation Summit 2027")
    assert not same_series("Water Innovation Summit", "AgTech Expo")


# ------------------------------------------------------------------ people

def test_a_speaker_list_gives_leads_and_only_an_official_profile_is_kept():
    html = ('<div><h3>Jane Q. Smith</h3><p>Professor, Arizona State University</p></div>'
            '<div><h3>Register Now Today</h3></div>'
            '<div><h3>Pat Lee</h3><p>Consultant</p></div>')
    assert speaker_page("https://summit.org/2026/speakers/")
    leads = speaker_leads(html, "https://summit.org/speakers", ["water"])
    assert [(l["name"], l["affiliation"]) for l in leads] == [
        ("Jane Q. Smith", "Arizona State University")]

    class Hit:
        def __init__(self, url, title):
            self.url, self.title, self.snippet = url, title, ""

    hits = [Hit("https://news.asu.edu/story/1", "Jane Smith wins award"),
            Hit("https://www.linkedin.com/in/janesmith", "Jane Smith"),
            Hit("https://search.asu.edu/profile/12345", "Jane Smith | ASU")]
    assert official_profile_hit(hits, "Jane Q. Smith").url == "https://search.asu.edu/profile/12345"
    # Seen on a real speaker list (6 Nov 2026): an aggregator ranked above the
    # university's own page; the page carrying the name on the institution's site wins.
    real = [Hit("https://sciprofiles.com/profile/583026", "Jana Pisk"),
            Hit("https://www.pmf.unizg.hr/chem/en/jana.pisk", "Jana Pisk"),
            Hit("https://www.linkedin.com/in/jana-pisk", "Jana Pisk")]
    assert official_profile_hit(real, "Jana Pisk").url == "https://www.pmf.unizg.hr/chem/en/jana.pisk"
    assert official_profile_hit(real[:1], "Jana Pisk") is None


# ------------------------------------------------------------------ queries

def test_synonyms_only_extend_the_requests_own_topics():
    assert theme_synonyms(["battery storage"]) == ["energy storage", "grid-scale batteries"]
    assert theme_synonyms(["something unlisted"]) == []
    assert "energy storage" not in theme_synonyms(["battery storage", "energy storage"])


def test_a_repeat_search_gives_way_to_a_fresh_one():
    base = ["a", "b", "c"]
    pool = ["a", "b", "c", "d", "e"]
    assert _fresh_first(base, pool, set(), 3) == ["a", "b", "c"]       # first run unchanged
    meta: dict = {}
    assert _fresh_first(base, pool, {"a", "b"}, 3, meta) == ["c", "d", "e"]
    assert meta == {"queries_skipped_as_repeats": 2, "queries_repeated": 0}
    assert _fresh_first(base, ["a", "b", "c"], {"a", "b", "c"}, 3) == ["a", "b", "c"]


# ------------------------------------------------------------------ found on real pages

def test_fiscal_years_and_the_announcing_pages_date_give_a_status():
    assert funding_status({"date": "FY25"}, today_year=2026) == "recent_award"
    assert funding_status({"date": "FY2026"}, today_year=2026) == "active"
    assert funding_status({"amount": "$5M", "reported": "2026-07"}, today_year=2026) == "active"
    assert funding_status({"amount": "$5M", "reported": "2019-03"}, today_year=2026) == "historical"


def _one_page_reader(page_url, html, answers):
    class Client:
        cost_meter = None

        def extract_with_tool(self, **kwargs):
            return answers

    def fetch(url):
        if url != page_url:
            raise RuntimeError("not found")
        return FetchedDoc.from_content(url=url, content=html, content_type="text/html")

    return LightPullReader(Client(), fetch)


def test_funding_the_organisation_gives_is_not_funding_it_received():
    page = "https://firstlight.example/"
    html = ("<p>FirstLight Power awarded $59,500 through the FirstLight Sustains Grant "
            "Program. FirstLight Power received a $2 million grant from the State of "
            "Connecticut in 2025.</p>")
    answers = {"funding_signal": {"stated": True, "page": page, "value": [
        {"amount": "$59,500", "funder": "FirstLight Power",
         "program": "FirstLight Sustains Grant Program"},
        {"amount": "$2 million", "funder": "State of Connecticut", "date": "2025"}],
        "quotes": ["FirstLight Power awarded $59,500 through the FirstLight Sustains Grant Program",
                   "FirstLight Power received a $2 million grant from the State of Connecticut in 2025"]}}
    read = _one_page_reader(page, html, answers).read(
        name="FirstLight Power", website=page, actor_category="company", read_at=NOW,
        fields=["funding_signal"])
    entries = read.evidence["funding_signal"]["value"]["entries"]
    assert [e["funder"] for e in entries] == ["State of Connecticut"]
    assert "funding it gives" in read.evidence["funding_signal"]["dropped_entries"][0]


def test_activity_dated_after_the_read_is_upcoming_not_recent():
    page = "https://ceg.example/"
    html = "<p>On January 13, 2027 Clean Energy Group hosts the webinar Beyond Lithium.</p>"
    answers = {"recent_activity": {"stated": True, "page": page, "value": [
        {"date": "January 13, 2027", "description": "Clean Energy Group hosts the webinar Beyond Lithium"}],
        "quotes": ["On January 13, 2027 Clean Energy Group hosts the webinar Beyond Lithium"]}}
    read = _one_page_reader(page, html, answers).read(
        name="Clean Energy Group", website=page, actor_category="foundation_nonprofit",
        read_at=NOW, fields=["recent_activity"])
    assert read.evidence["recent_activity"]["collection_state"] == "not_found"
    assert "upcoming" in read.rejected["recent_activity"]
