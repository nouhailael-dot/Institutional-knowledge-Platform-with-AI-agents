"""Quality gates for discovered people and events, against the labelled set."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from agents.discovery.page_facts import EVENT_FACT_FIELDS, PERSON_FACT_FIELDS, verify_facts
from agents.discovery.quality_gates import (
    cap_band,
    event_gate,
    held_event_match,
    linkedin_profile,
    person_gate,
    source_kind,
)

GOLD = [json.loads(line) for line in
        (Path(__file__).resolve().parents[2] / "evals" / "people_events_gold.jsonl")
        .read_text(encoding="utf-8").splitlines() if line.strip()]
RUN_DATE = date(2026, 10, 22)


def _rubric(flags: dict) -> dict:
    return {name: {"present": bool(on), "evidence": "stated" if on else None}
            for name, on in flags.items()}


def gate_of(case: dict):
    facts = dict(case.get("facts") or {})
    if case["entity_type"] == "person":
        linkedin = linkedin_profile(case.get("page_html") or "", case["record"]["name"])
        if linkedin:
            facts["linkedin_url"] = linkedin
        return person_gate(case["record"], facts=facts, page_url=case["page_url"],
                           page_text=case["page_text"], rubric=_rubric(case["rubric"]))
    return event_gate(case["record"], facts=facts, page_url=case["page_url"],
                      page_text=case["page_text"], rubric=_rubric(case["rubric"]),
                      run_date=RUN_DATE)


@pytest.mark.parametrize("case", GOLD, ids=[c["id"] for c in GOLD])
def test_every_labelled_case_gets_the_expected_decision(case):
    gate = gate_of(case)
    # The gate's own decision; Needs More Research ends excluded when no
    # official page resolves it (the follow-up is tested in test_phase2_followup).
    assert gate.decision == case.get("expected_gate", case["expected"]), (case["note"], gate.reasons)
    assert cap_band("auto_high", gate) == {"accept": "auto_high", "review": "review"}.get(
        case["expected"], "auto_low")
    assert gate.reasons                       # every decision says why, in words
    names = [c.name for c in gate.checks]
    assert "completeness" in names and "relevance" in names


def test_a_gate_only_lowers_a_band():
    exclude = gate_of(next(c for c in GOLD if c["id"] == "p08_news_only"))
    review = gate_of(next(c for c in GOLD if c["id"] == "e09_conflicting_dates"))
    accept = gate_of(next(c for c in GOLD if c["id"] == "p01_university_researcher"))
    assert cap_band("auto_high", exclude) == "auto_low"
    assert review.decision == "review" and cap_band("auto_high", review) == "review"
    assert cap_band("review", accept) == "review"          # never raised
    assert cap_band("auto_low", accept) == "auto_low"


def test_a_linkedin_profile_counts_only_when_the_official_page_links_this_persons_own():
    html = '<a href="https://www.linkedin.com/in/maria-lopez-water">LinkedIn</a>'
    assert linkedin_profile(html, "Dr. Maria Lopez") == "https://www.linkedin.com/in/maria-lopez-water"
    # A colleague's profile on the same page is never attached to her.
    assert linkedin_profile('<a href="https://linkedin.com/in/george-brown">x</a>', "Maria Lopez") is None
    # Two possible profiles: not a reliable match.
    two = ('<a href="https://linkedin.com/in/maria-lopez-1">a</a>'
           '<a href="https://linkedin.com/in/maria-lopez-2">b</a>')
    assert linkedin_profile(two, "Maria Lopez") is None
    assert linkedin_profile(html, "Lopez") is None          # one name part is not enough


@pytest.mark.parametrize(("url", "kind"), [
    ("https://phys.org/news/x", "news"), ("https://news.example.edu/story", "news"),
    ("https://www.example.edu/news/2026/award", "news"), ("https://10times.com/x", "listing"),
    ("https://www.linkedin.com/in/x", "social"), ("https://www.zoominfo.com/p/x", "directory"),
    ("https://cee.example.edu/people/x", "web"),
])
def test_where_a_page_comes_from_is_read_from_its_address(url, kind):
    assert source_kind(url) == kind


def test_an_event_already_on_the_map_is_not_read_again_but_a_new_edition_is():
    held = [{"event_id": "e1", "name": "2027 ARPA-E Energy Innovation Summit",
             "next_date": "2027-04-20"}]
    assert held_event_match("2027 ARPA-E Energy Innovation Summit | Agenda", held)["event_id"] == "e1"
    assert held_event_match("ARPA-E Energy Innovation Summit 2027 - Speakers", held)
    assert held_event_match("2028 ARPA-E Energy Innovation Summit", held) is None
    assert held_event_match("Energy Summit 2027", held) is None          # too generic
    series = [{"event_id": "s", "name": "Water Reuse Innovation Summit", "next_date": None}]
    assert held_event_match("Water Reuse Innovation Summit", series)["event_id"] == "s"
    assert held_event_match("2027 Water Reuse Innovation Summit", series) is None


def test_a_fact_is_kept_only_with_its_quote_on_the_page():
    html = ("<p>Maria Lopez is in the Department of Civil Engineering. She leads the "
            "Brackish Water Reuse Testbed.</p>")
    facts = verify_facts({
        "department": "Department of Civil Engineering",
        "relevant_work": ["Brackish Water Reuse Testbed"],
        "um6p_ocp_connection": "Visiting fellow at UM6P",       # invented
        "evidence": {"department": "She is in the Department of Civil Engineering",
                     "relevant_work": "She leads the Brackish Water Reuse Testbed.",
                     "um6p_ocp_connection": "She was a visiting fellow at UM6P"},
    }, html=html, source_url="https://x.example.edu/p", read_at=datetime(2026, 10, 22, tzinfo=UTC),
        fields=PERSON_FACT_FIELDS)
    assert facts["department"] == "Department of Civil Engineering"
    assert facts["relevant_work"] == ["Brackish Water Reuse Testbed"]
    assert "um6p_ocp_connection" not in facts and facts["dropped"] == ["um6p_ocp_connection"]
    assert facts["evidence"]["department"]["source_url"] == "https://x.example.edu/p"
    assert facts["evidence"]["department"]["date_read"].startswith("2026-10-22")
    # A registration link counts only if it is on the page.
    event = verify_facts({"registration_url": "https://e.example.org/register",
                          "page_kind": "official_event_site"},
                         html='<a href="https://e.example.org/register">Register</a>',
                         source_url="https://e.example.org", read_at=datetime.now(UTC),
                         fields=EVENT_FACT_FIELDS)
    assert event["registration_url"] and event["page_kind"] == "official_event_site"


def test_a_person_is_never_accepted_on_a_news_mention_even_with_a_high_score():
    case = next(c for c in GOLD if c["id"] == "p08_news_only")
    gate = gate_of(case)
    # Promising (named, relevant), so one official page is read first - but the
    # news article itself never qualifies the person.
    assert gate.decision == "research" and gate.identity_source is None
    assert gate.outcome == "needs_research" and cap_band("auto_high", gate) == "auto_low"
    assert "news" in " ".join(gate.reasons).casefold()


def test_page_text_reads_the_page_not_its_scripts():
    from agents.discovery.page_facts import page_text, reading_text

    html = (
        "<html><head><title>Grid Summit 2027</title>"
        "<script>" + "var x = 1;" * 3000 + "</script>"
        '<script type="application/ld+json">{"@type": "Event", "name": "Grid Summit 2027",'
        ' "startDate": "2027-05-04", "eventStatus": "https://schema.org/EventScheduled",'
        ' "organizer": {"@type": "Organization", "name": "Grid Institute"}}</script>'
        "</head><body><nav>Home</nav><main><h1>Grid Summit 2027</h1>"
        "<p>Three days on transmission planning in Denver.</p>"
        '<a href="https://grid.example.org/register">Register now</a></main>'
        "<footer>Organised by the Grid Institute</footer></body></html>"
    )
    text = page_text(html)
    assert "var x" not in text
    assert "transmission planning in Denver" in text
    assert '"startDate": "2027-05-04"' in text              # structured data kept
    assert "Register now: https://grid.example.org/register" in text
    assert "Footer: Organised by the Grid Institute" in text
    assert reading_text(html, "text/html") == text
    assert reading_text("plain notes", "text/plain") == "plain notes"
    # A footer quote now verifies: the organiser is no longer dropped.
    facts = verify_facts({"organizer": "Grid Institute",
                          "evidence": {"organizer": "Organised by the Grid Institute"}},
                         html=html, source_url="https://grid.example.org",
                         read_at=datetime(2026, 10, 22, tzinfo=UTC), fields=EVENT_FACT_FIELDS)
    assert facts["organizer"] == "Grid Institute" and "dropped" not in facts


def test_speakers_and_organizations_are_kept_item_by_item_only_when_on_the_page():
    html = ("<main><h1>Grid Summit 2027</h1><p>Speakers: Ana Lee, CTO, GridCo; "
            "Omar Haddad, Professor, Rice University.</p><p>Sponsors: GridCo, Rice University."
            "</p><p>The largest grid conference in Texas.</p></main>")
    facts = verify_facts({
        "speakers": ["Ana Lee, CTO, GridCo", "Invented Person, CEO, Nowhere"],
        "participating_organizations": ["GridCo", "Rice University"],
        "standing_claims": ["The largest grid conference in Texas."],
    }, html=html, source_url="https://grid.example.org",
        read_at=datetime(2026, 10, 23, tzinfo=UTC), fields=EVENT_FACT_FIELDS)
    assert facts["speakers"] == ["Ana Lee, CTO, GridCo"]          # the invented one is gone
    assert facts["evidence"]["speakers"]["items_dropped"] == 1
    assert facts["participating_organizations"] == ["GridCo", "Rice University"]
    assert facts["standing_claims"] == ["The largest grid conference in Texas."]


def test_the_gate_payload_is_plain_json_lists():
    import json

    gate = gate_of(next(c for c in GOLD if c["id"] == "p04_diaspora_professional_thin"))
    payload = gate.payload()
    for key in ("reasons", "missing_mandatory", "missing_priority", "conflicts", "checks"):
        assert isinstance(payload[key], list), key
    assert json.loads(json.dumps(payload)) == payload
