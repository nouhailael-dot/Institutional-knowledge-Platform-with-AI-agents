"""6 Nov 2026: where an organisation is, whether it received the money, and what a
Light Pull read costs. The cases are the real pages and quotes that went wrong."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from agents.collection.light_pull_reader import (
    LightDocument,
    LightPullReader,
    _answer_schema,
    without_repeats,
)
from agents.common.funding_evidence import receipt_finding
from agents.common.llm import build_messages_create_kwargs
from agents.common.location_evidence import (
    check_location,
    name_state,
    place_statements,
    quote_places_it,
)
from agents.discovery.search.actor_quality import QualityConfig, assess_actor
from agents.discovery.search.actor_scoring import ActorPageAnalysis
from agents.discovery.search.phase2 import checked_location
from agents.discovery.sources.base import FetchedDoc

NOW = datetime(2026, 11, 6, tzinfo=UTC)

SEVEN_SEAS = (
    "Water & Wastewater Solutions for Arizona | Seven Seas Water Group\n"
    "Seven Seas' solutions are built to keep pace with Arizona's growth.\n"
    "Planning a Project in Arizona? Schedule a Consultation\n"
    "Arizona faces unique pressures, from aquifer depletion to rapid suburban growth.")
SEVEN_SEAS_FOOTER = "14400 Carlson Circle Tampa, Florida 33626 +1 (813) 855-8636"


# ------------------------------------------------------------------ location

def test_a_page_written_for_a_state_does_not_place_the_organisation_there():
    check = check_location(name="Seven Seas Water Group", claimed_state="Arizona",
                           text=SEVEN_SEAS, footer=SEVEN_SEAS_FOOTER)
    assert (check.state, check.city, check.basis, check.changed) == ("FL", "Tampa", "address", True)
    assert "Tampa, Florida 33626" in check.reason


def test_a_state_only_talked_about_is_withheld_for_a_person():
    check = check_location(name="Global Water Resources, Inc.", claimed_state="Arizona",
                           text="Protecting Arizona's Water. We serve Pinal, Pima and "
                                "Maricopa Counties.")
    assert check.state is None and check.basis == "unconfirmed"
    assert "never says the organisation is based" in check.reason


@pytest.mark.parametrize(("name", "state", "text", "basis"), [
    ("WateReuse Arizona", "Arizona", "WateReuse Association, 610 Madison Street, "
                                     "Alexandria, VA 22314", "name"),
    ("VA Phoenix Health Care System", "Arizona", "Care for veterans.", "name"),
    ("Water Resiliency Program", "AZ", "WateResiliency | University of Arizona | 2959 W Calle "
                                       "Agua Nueva, Tucson, AZ, USA", "address"),
    ("ProChemTech", "Pennsylvania", "ProChemTech was started as a privately owned "
                                    "Pennsylvania-based corporation in 1987.", "based"),
    ("Water For Tomorrow Project", "Arizona", "Footer: Arizona 501(c)(3) Initiative", "based"),
    ("The Water Council", "Wisconsin", "The Water Council is a 501(c)(3) nonprofit in "
                                       "Milwaukee, Wisconsin.", "based"),
])
def test_a_state_the_page_ties_to_it_is_kept(name, state, text, basis):
    check = check_location(name=name, claimed_state=state, text=text)
    assert check.basis == basis and not check.changed


def test_a_story_about_a_place_never_sets_a_location():
    # A case study on the company's own site: where it worked, not where it is.
    check = check_location(name="Grundfos", claimed_state=None,
                           text="Grundfos supported the water innovation challenge in "
                                "Pima County, Arizona.")
    assert check.state is None
    assert check_location(name="X", claimed_state=None,
                          text="registered in the states of Arizona, Nevada, and "
                               "Pennsylvania").state is None


def test_an_address_fills_a_missing_state():
    check = check_location(name="Imagine H2O", claimed_state=None,
                           text="Imagine H2O, 1 Ferry Building, San Francisco, CA 94111")
    assert (check.state, check.city) == ("CA", "San Francisco")


def test_someone_elses_footer_is_its_publishers_address():
    check = check_location(name="Acme Water", claimed_state="Arizona", own_site=False,
                           text="Acme Water helps Arizona farms.",
                           footer="News Corp, 1 Main St, Austin, TX 78701")
    assert check.state is None and check.basis == "unconfirmed"


def test_a_city_word_inside_a_name_is_not_a_city():
    # Center, North Dakota exists; the Energy & Environmental Research Center is
    # not named after it.
    assert check_location(name="Energy & Environmental Research Center",
                          claimed_state="ND", text="Research for energy.").basis == "unconfirmed"
    assert name_state("Washington University in St. Louis") is None
    assert name_state("Kansas City Water") is None


def test_the_light_pull_location_quote_must_say_where_it_is():
    assert quote_places_it("Seven Seas", ["14400 Carlson Circle Tampa, Florida 33626"],
                           state="FL", city="Tampa")
    assert quote_places_it("The Water Council", ["nonprofit in Milwaukee, Wisconsin"],
                           state="Wisconsin", city="Milwaukee")
    assert not quote_places_it("Seven Seas", ["Arizona-ready water and wastewater solutions"],
                               state="AZ")
    assert not quote_places_it("X", ["We helped a company in Phoenix, Arizona"],
                               state="AZ", city="Phoenix")
    # Outside the US the quote must still give the place it is stored as.
    assert quote_places_it("T", ["T is a nonprofit in Toronto, Ontario"],
                           state="Ontario", city="Toronto")
    assert not quote_places_it("T", ["nonprofit in Milwaukee, Wisconsin"],
                               state="Ontario", city="Toronto")


def test_discovery_keeps_only_the_location_its_page_ties_to_it():
    html = (f"<html><head><title>Seven Seas</title></head><body><main><p>{SEVEN_SEAS}</p>"
            f"</main><footer>{SEVEN_SEAS_FOOTER}</footer></body></html>")
    doc = FetchedDoc.from_content(url="https://sevenseas.example/arizona/", content=html,
                                  content_type="text/html")
    analysis = ActorPageAnalysis(rubric={}, record={
        "name": "Seven Seas Water Group", "state": "Arizona",
        "website": "https://sevenseas.example/arizona/"})
    record = checked_location(analysis, doc).record
    assert record["state"] == "Florida" and record["location_city"] == "Tampa"
    assert record["location_check"]["claimed_state"] == "AZ"


def test_an_unconfirmed_location_is_never_accepted_unseen():
    record = {"name": "Global Water Resources", "website": "https://gw.example",
              "description": "A water utility. It runs recycled water services for towns.",
              "actor_type": "company",
              "location_check": {"basis": "unconfirmed",
                                 "reason": "The page talks about Arizona but never says "
                                           "the organisation is based or has an office there."}}
    verdict = assess_actor(score=0.95, page_url="https://gw.example", record=record,
                           rubric={}, config=QualityConfig())
    assert "location_unconfirmed" in verdict.gates_failed
    assert verdict.band != "accept"


def test_statements_are_found_in_footer_lines():
    found = place_statements("About us", footer="Western Regions 2475 Dallas Ave "
                                                "Apache Junction, AZ 85120")
    assert found[0].state == "AZ" and found[0].kind == "address"


# ------------------------------------------------------------------ funding

@pytest.mark.parametrize(("entry", "quote", "name", "own_site", "kept"), [
    # Kept: the quote shows it receiving.
    ({"funder": "The Fund", "amount": "$500,000"},
     "The Fund awarded The Water Council a $500,000 grant in 2026.", "The Water Council", True,
     True),
    ({"amount": "$25 million"}, "Renewal of the DOE-EERC cooperative agreement, providing up to "
     "$25 million over 5 years", "Energy & Environmental Research Center", True, True),
    ({"amount": "$5 million"}, "a $5 million DOE investment that expands the EERC's technical "
     "assistance capabilities", "Energy & Environmental Research Center", True, True),
    ({"funder": "Department of Energy", "amount": "up to $57 million"},
     "Department of Energy Selects CEG and Partners for up to $57 million",
     "Clean Energy Group", True, True),
    ({"amount": "$1 billion"}, "Base Power, a Battery-Focused Power Company, Raises $1 Billion",
     "Base Power", True, True),
    ({"funder": "Fund for Lake Michigan", "amount": "$2 million"},
     "received a $2 million grant from the Fund for Lake Michigan", "The Water Council", True,
     True),
    ({"funder": "USDA"}, "This project is funded by the USDA.", "Acme Water", True, True),
    # Dropped: given, offered, run, reported, or someone else's.
    ({"amount": "$59,500"}, "The program will provide $59,500 in grants to 13 organizations.",
     "FirstLight Power", True, False),
    ({"amount": "$3.6 Million"}, "Clean Energy Group Helps Massachusetts Low-Income Communities "
     "Access $3.6 Million for Backup Power", "Clean Energy Group", True, False),
    ({"amount": "$3.3 Million"}, "The Kresge Foundation Makes $3.3 Million Commitment in "
     "Partnership with Clean Energy Group", "Clean Energy Group", True, False),
    ({"amount": "$36 million"}, "Crack the Code 2.0, a $36 million DOE initiative to advance "
     "technologies", "Energy & Environmental Research Center", True, False),
    ({"funder": "Kirt Brooks Scholarship Fund"}, "Congratulations to Fernando Ruelas and Mason "
     "Miazga on winning the 2026 Kirt Brooks Memorial Scholarship.",
     "California Water Environment Association", True, False),
    ({"amount": "$1M"}, "Applications are now open for the $1M DOE funding opportunity.",
     "Acme Water", True, False),
    ({"amount": "$300,000"}, "Acme Water administers the $300,000 State program on behalf of "
     "the Department.", "Acme Water", True, False),
    ({"amount": "$750,000"}, "NSF awarded $750,000 to the University of Somewhere.",
     "Acme Water", False, False),
])
def test_a_grant_is_kept_only_when_its_own_quote_shows_it_was_received(
        entry, quote, name, own_site, kept):
    assert (receipt_finding(entry, [quote], name=name, own_site=own_site) is None) is kept


def test_another_grants_receipt_does_not_carry_this_one():
    quotes = ["Department of Energy Selects CEG and Partners for up to $57 million",
              "Clean Energy Group Helps Communities Access $3.6 Million"]
    assert receipt_finding({"amount": "$3.6 Million"}, quotes, name="Clean Energy Group")
    assert receipt_finding({"amount": "up to $57 million"}, quotes,
                           name="Clean Energy Group") is None


def test_the_light_pull_refuses_a_received_label_its_quote_does_not_show():
    home = "https://cleane.example/"
    page = ("<title>Clean Energy Group</title><p>Clean Energy Group Helps Communities "
            "Access $3.6 Million for Backup Power.</p>")

    class Client:
        cost_meter = None

        def extract_with_tool(self, **kwargs):
            return {"funding_signal": {
                "stated": True, "page": home,
                "value": [{"amount": "$3.6 Million", "funder": "the State", "role": "received"}],
                "quotes": ["Clean Energy Group Helps Communities Access $3.6 Million for "
                           "Backup Power"]}}

    def fetch(url):
        if url != home:
            raise RuntimeError("not found")
        return FetchedDoc.from_content(url=url, content=page, content_type="text/html")

    read = LightPullReader(Client(), fetch).read(
        name="Clean Energy Group", website=home, actor_category="foundation_nonprofit",
        read_at=NOW, fields=["funding_signal"])
    assert read.evidence["funding_signal"]["collection_state"] == "not_found"
    assert "not confirmed as funding it received" in read.rejected["funding_signal"]


# ------------------------------------------------------------------ cost

def test_repeated_menu_and_footer_lines_are_sent_once():
    docs = [LightDocument(url="a", text="Home\nAbout\nWe run a lab.\nFooter: 1 Main St",
                          date_read=NOW),
            LightDocument(url="b", text="Home\nAbout\nOur grants.\nFooter: 1 Main St",
                          date_read=NOW)]
    out = without_repeats(docs)
    assert out[0].text == docs[0].text
    assert out[1].text == "Our grants."


def test_the_light_pull_tool_is_the_same_for_every_organisation_of_a_category():
    a = _answer_schema(["location", "funding_signal"], ["https://a.example/"])
    b = _answer_schema(["location", "funding_signal"], ["https://b.example/", "https://b/x"])
    assert a == b                     # so its prompt can be cached across organisations


def test_a_cached_prefix_marks_the_system_prompt_and_tool():
    kwargs = build_messages_create_kwargs(
        model="m", system="rules", user="pages", tool_name="t", tool_description="d",
        input_schema={"type": "object"}, cache_prefix=True)
    assert kwargs["tools"][0]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["messages"] == [{"role": "user", "content": "pages"}]
    plain = build_messages_create_kwargs(
        model="m", system="rules", user="pages", tool_name="t", tool_description="d",
        input_schema={"type": "object"})
    assert "cache_control" not in plain["tools"][0] and plain["system"] == "rules"


def test_the_light_pull_main_read_asks_for_the_cached_prefix():
    calls = []

    @dataclass
    class Client:
        cost_meter = None

        def extract_with_tool(self, **kwargs):
            calls.append(kwargs)
            return {}

    def fetch(url):
        return FetchedDoc.from_content(url=url, content="<p>Acme Water runs a lab.</p>",
                                       content_type="text/html")

    LightPullReader(Client(), fetch).read(name="Acme Water", website="https://acme.example/",
                                          actor_category="company", read_at=NOW,
                                          fields=["location"])
    assert calls and calls[0].get("cache_prefix") is True


def test_money_raised_and_passed_on_is_not_funding_it_received():
    quote = ("In response to SB 918, WRF and WateReuse California launched a DPR Research "
             "Initiative (2012-2016) that raised more than $6M, which funded 34 projects.")
    assert receipt_finding({"amount": "more than $6M"}, [quote], name="WateReuse California")


def test_money_to_another_company_trading_under_the_name_is_not_kept():
    # 8 Nov 2026 validation: a Missouri electric sibling's grant, read for Liberty's
    # Arizona water utility on the parent company's site.
    quotes = ["The U.S. Department of Energy has selected The Empire District Electric Company "
              "d/b/a Liberty to receive up to $47.5 million in federal funding.",
              "This material is based upon work supported by the Department of Energy."]
    reason = receipt_finding({"amount": "up to $47.5 million", "funder": "U.S. Department of Energy"},
                             quotes, name="Liberty", own_site=False)
    assert reason and "The Empire District Electric Company" in reason
    # Its own legal name before the d/b/a is still its own grant.
    own = ["The DOE selected Liberty Utilities Corp. d/b/a Liberty to receive $2 million."]
    assert receipt_finding({"amount": "$2 million"}, own, name="Liberty") is None


def test_a_shared_line_is_credited_to_the_page_it_was_shown_on():
    # The newsletter page lists the press-release headline too; it is shown once,
    # on the page read first, and an answer naming the other page still counts.
    home = "https://cleane.example/"
    news = "https://cleane.example/newsletters/"
    press = "https://cleane.example/press-releases/"
    headline = "Department of Energy Selects CEG and Partners for up to $57 million"
    pages = {home: ('<title>Clean Energy Group</title><a href="/newsletters/">News</a>'
                    '<a href="/press-releases/">Press</a><p>Clean energy for all.</p>'),
             news: f"<p>{headline}</p><p>Our newsletter.</p>",
             press: f"<p>{headline}</p><p>Press releases.</p>"}

    class Client:
        cost_meter = None

        def extract_with_tool(self, **kwargs):
            return {"funding_signal": {
                "stated": True, "page": press,
                "value": [{"amount": "up to $57 million", "funder": "Department of Energy",
                           "role": "received"}],
                "quotes": [headline]}}

    def fetch(url):
        if url not in pages:
            raise RuntimeError("not found")
        return FetchedDoc.from_content(url=url, content=pages[url], content_type="text/html")

    read = LightPullReader(Client(), fetch).read(
        name="Clean Energy Group", website=home, actor_category="foundation_nonprofit",
        topic_terms=["energy"], read_at=NOW, fields=["funding_signal"])
    found = read.evidence["funding_signal"]
    assert found["collection_state"] == "found", read.rejected
    assert headline not in read.texts.get(press, "") or found["source_url"] == press


def test_a_units_own_page_on_its_parents_site_speaks_for_it():
    # Scottsdale Water Resources' website is a page of scottsdaleaz.gov: what that
    # page says is its own; the city's other pages still need to name it.
    home = "https://city.example/"
    unit = "https://city.example/water/advanced-water-purification/"
    pages = {home: "<title>City of Scottsdale</title><p>Welcome to the City.</p>",
             unit: "<p>The Advanced Water Treatment Facility purifies recycled water for "
                   "drinking water supply.</p>"}

    class Client:
        cost_meter = None

        def extract_with_tool(self, **kwargs):
            return {"topic_mandate_program": {
                "stated": True, "page": unit,
                "value": "Purifies recycled water for drinking water supply",
                "quotes": ["The Advanced Water Treatment Facility purifies recycled water for "
                           "drinking water supply."]}}

    def fetch(url):
        if url not in pages:
            raise RuntimeError("not found")
        return FetchedDoc.from_content(url=url, content=pages[url], content_type="text/html")

    read = LightPullReader(Client(), fetch).read(
        name="Scottsdale Water Resources", website=unit, actor_category="government",
        read_at=NOW, fields=["topic_mandate_program"])
    assert read.evidence["topic_mandate_program"]["collection_state"] == "found", read.rejected


# ------------------------------------------------------------------ head office vs where it works

def _verdict(record):
    from agents.discovery.search.actor_quality import Scope

    return assess_actor(score=0.95, page_url="https://x.example/", record=record, rubric={},
                        config=QualityConfig(), scope=Scope(states=("AZ",)))


def test_a_head_office_elsewhere_with_work_in_the_area_goes_to_review():
    check = check_location(name="Seven Seas Water Group", claimed_state="Arizona",
                           text=SEVEN_SEAS, footer=SEVEN_SEAS_FOOTER)
    assert check.state == "FL"
    assert [o["state"] for o in check.operates_in] == ["AZ"]
    verdict = _verdict({"name": "Seven Seas Water Group", "state": "Florida",
                        "location_check": check.as_record()})
    assert "outside_requested_region" not in verdict.gates_failed
    assert "operates_in_area_based_elsewhere" in verdict.gates_failed
    assert any("describes work in AZ" in r for r in verdict.reasons)


def test_an_office_in_the_area_is_named_as_an_office():
    check = check_location(
        name="ProChemTech", claimed_state="Pennsylvania",
        text="ProChemTech was started as a privately owned Pennsylvania-based corporation. "
             "ProChemTech operates its western office at 2475 Dallas Avenue in Apache "
             "Junction, Arizona.",
        footer="Western Regions 2475 Dallas Ave Apache Junction, AZ 85120")
    assert check.state == "PA" and check.headquarters["state"] == "PA"
    office = [o for o in check.operates_in if o["state"] == "AZ"]
    assert office and office[0]["kind"] == "office"
    verdict = _verdict({"name": "ProChemTech", "state": "Pennsylvania",
                        "location_check": check.as_record()})
    assert any("gives an office in AZ" in r for r in verdict.reasons)


def test_a_page_that_never_names_the_area_is_still_rejected():
    check = check_location(name="Imagine H2O", claimed_state=None,
                           text="Imagine H2O, 1 Ferry Building, San Francisco, CA 94111. "
                                "We accelerate water startups worldwide.")
    verdict = _verdict({"name": "Imagine H2O", "state": "California",
                        "location_check": check.as_record()})
    assert "outside_requested_region" in verdict.gates_failed


def test_the_head_office_is_told_apart_from_the_place_kept():
    check = check_location(
        name="Acme Water", claimed_state="Arizona",
        text="Our Phoenix office: 100 Main St, Phoenix, AZ 85004. Acme Water is "
             "headquartered in Denver, Colorado.")
    assert check.state == "AZ" and check.headquarters["state"] == "CO"
    verdict = _verdict({"name": "Acme Water", "state": "Arizona",
                        "location_check": check.as_record()})
    assert "outside_requested_region" not in verdict.gates_failed
    assert any("head office in CO" in r for r in verdict.reasons)
