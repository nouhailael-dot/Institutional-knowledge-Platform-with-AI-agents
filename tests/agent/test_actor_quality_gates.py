"""The actor quality decision: three bands, scored AND gated.

Each case below is drawn from a real candidate that the old 0.30 / 0.70 rule
auto-accepted, measured on the isolated demo database in October 2026.
"""

from __future__ import annotations

import pytest

from agents.discovery.search.actor_quality import (
    ACCEPT,
    REJECT,
    REVIEW,
    QualityConfig,
    Scope,
    assess_actor,
    quality_config,
    registrable_domain,
)

CONFIG = QualityConfig()

FULL_RUBRIC = {
    name: {"present": True, "evidence": f"Specific evidence for {name}."}
    for name in (
        "own_organisational_page", "real_operating_entity", "use_cases",
        "research_development_or_programmes", "partnerships_or_tech_transfer",
        "sector_coverage", "open_programmes",
    )
}
GOOD_DESCRIPTION = (
    "Urban Future Lab is a clean-energy incubator at NYU Tandon. It runs accelerator "
    "programmes for climate-technology startups and operates a shared lab in Brooklyn."
)


def _record(**overrides):
    return {
        "name": "Urban Future Lab",
        "website": "https://www.ufl.nyc",
        "description": GOOD_DESCRIPTION,
        **overrides,
    }


def test_a_genuinely_strong_actor_is_accepted():
    verdict = assess_actor(score=0.96, page_url="https://www.ufl.nyc/about",
                           record=_record(), rubric=FULL_RUBRIC, config=CONFIG)
    assert verdict.band == ACCEPT
    assert verdict.gates_failed == ()


def test_accept_never_means_verified():
    """The band names a creation route; it is never a verification status."""
    verdict = assess_actor(score=0.99, page_url="https://www.ufl.nyc/",
                           record=_record(), rubric=FULL_RUBRIC, config=CONFIG)
    assert verdict.band == "auto_high"
    assert "verified" not in verdict.band


# ------------------------------------------------- the old rule's real mistakes

def test_a_page_about_an_organisation_on_someone_elses_site_is_held():
    """'Texas Medical Center Innovation' scored 0.96 - read from edegan.com."""
    verdict = assess_actor(
        score=0.96, page_url="https://www.edegan.com/wiki/Texas_Medical_Center",
        record=_record(name="Texas Medical Center Innovation",
                       website="http://www.tmcinnovation.org/"),
        rubric=FULL_RUBRIC, config=CONFIG,
    )
    assert verdict.band == REVIEW
    assert "third_party_page" in verdict.gates_failed
    assert any("edegan.com" in reason for reason in verdict.reasons)


def test_an_organisation_with_no_stated_site_cannot_be_auto_accepted():
    """'University of California, Davis' scored 0.84 on empowerinnovation.net."""
    verdict = assess_actor(
        score=0.95, page_url="https://empowerinnovation.net/uc-davis",
        record=_record(name="University of California, Davis", website=None),
        rubric=FULL_RUBRIC, config=CONFIG,
    )
    assert verdict.band == REVIEW
    assert "website_unverified" in verdict.gates_failed


@pytest.mark.parametrize("name", [
    "California Agricultural Tourism Directory",
    "Great Lakes Drinking Water Advocates Database",
    "Top 10 Clean Energy Startups in Boston",
])
def test_a_list_or_directory_is_rejected_whatever_it_scored(name):
    verdict = assess_actor(score=0.99, page_url="https://example.org/",
                           record=_record(name=name), rubric=FULL_RUBRIC, config=CONFIG)
    assert verdict.band == REJECT
    assert "not_an_organisation" in verdict.gates_failed


@pytest.mark.parametrize("path", ["/events/2026-summit", "/news/press-release", "/careers/"])
def test_event_news_and_careers_pages_are_rejected(path):
    verdict = assess_actor(score=0.95, page_url=f"https://www.ufl.nyc{path}",
                           record=_record(), rubric=FULL_RUBRIC, config=CONFIG)
    assert verdict.band == REJECT


# ------------------------------------------------------------------- the bands

@pytest.mark.parametrize(("score", "band"), [
    (0.00, REJECT), (0.44, REJECT),          # below 0.45: never picked
    (0.45, REVIEW), (0.79, REVIEW),          # the review band
    (0.80, ACCEPT), (1.00, ACCEPT),          # accept, when every gate holds
])
def test_the_three_bands(score, band):
    verdict = assess_actor(score=score, page_url="https://www.ufl.nyc/",
                           record=_record(), rubric=FULL_RUBRIC, config=CONFIG)
    assert verdict.band == band


def test_a_rejected_candidate_says_why():
    verdict = assess_actor(score=0.20, page_url="https://www.ufl.nyc/",
                           record=_record(), rubric=FULL_RUBRIC, config=CONFIG)
    assert verdict.reasons and "0.20" in verdict.reasons[0]


@pytest.mark.parametrize(("override", "gate"), [
    ({"description": None}, "weak_description"),
    ({"description": "Innovating for a better tomorrow"}, "weak_description"),
    ({"description": "Short."}, "weak_description"),
])
def test_a_weak_description_holds_a_high_scorer_for_review(override, gate):
    verdict = assess_actor(score=0.95, page_url="https://www.ufl.nyc/",
                           record=_record(**override), rubric=FULL_RUBRIC, config=CONFIG)
    assert verdict.band == REVIEW
    assert gate in verdict.gates_failed


def test_thin_evidence_holds_a_high_scorer_for_review():
    thin = {k: v for k, v in list(FULL_RUBRIC.items())[:3]}
    verdict = assess_actor(score=0.95, page_url="https://www.ufl.nyc/",
                           record=_record(), rubric=thin, config=CONFIG)
    assert verdict.band == REVIEW
    assert "thin_evidence" in verdict.gates_failed


def test_no_concrete_work_holds_a_high_scorer_for_review():
    vague = {k: v for k, v in FULL_RUBRIC.items()
             if k not in ("use_cases", "research_development_or_programmes")}
    vague.update({f"extra_{i}": {"present": True, "evidence": "x" * 30} for i in range(3)})
    verdict = assess_actor(score=0.95, page_url="https://www.ufl.nyc/",
                           record=_record(), rubric=vague, config=CONFIG)
    assert "no_substantive_work" in verdict.gates_failed


# --------------------------------------------------------- the user's request

def test_an_actor_outside_the_requested_sector_is_rejected():
    verdict = assess_actor(score=0.95, page_url="https://www.ufl.nyc/",
                           record=_record(), rubric=FULL_RUBRIC, config=CONFIG,
                           scope=Scope(sector_codes=("AGRI",)), record_sector_codes=("ENERGY",))
    assert verdict.band == REJECT
    assert "outside_requested_sector" in verdict.gates_failed


def test_an_actor_outside_the_requested_region_is_rejected():
    verdict = assess_actor(score=0.95, page_url="https://www.ufl.nyc/",
                           record=_record(state_code="TX"), rubric=FULL_RUBRIC, config=CONFIG,
                           scope=Scope(sector_codes=("ENERGY",), states=("NY", "MA")),
                           record_sector_codes=("ENERGY",))
    assert verdict.band == REJECT
    assert "outside_requested_region" in verdict.gates_failed


def test_an_actor_inside_the_request_is_judged_on_quality():
    verdict = assess_actor(score=0.95, page_url="https://www.ufl.nyc/",
                           record=_record(state_code="NY"), rubric=FULL_RUBRIC, config=CONFIG,
                           scope=Scope(sector_codes=("ENERGY",), states=("NY", "MA")),
                           record_sector_codes=("ENERGY", "SUSTAIN"))
    assert verdict.band == ACCEPT


# --------------------------------------------------------------- the plumbing

@pytest.mark.parametrize(("url", "domain"), [
    ("https://www.umb.edu/ssl/", "umb.edu"),
    ("https://meet.nyu.edu/academics/", "nyu.edu"),
    ("ufl.nyc", "ufl.nyc"),
    ("https://www.ox.ac.uk/research", "ox.ac.uk"),
    ("", None),
    ("not a url", None),
])
def test_registrable_domain(url, domain):
    assert registrable_domain(url) == domain


def test_a_university_unit_on_the_university_domain_is_its_own_site():
    """A lab at umb.edu/ssl is on its parent's domain - that is not third-party."""
    verdict = assess_actor(
        score=0.90, page_url="https://www.umb.edu/ssl/",
        record=_record(name="Sustainable Solutions Lab", website="https://www.umb.edu/ssl/"),
        rubric=FULL_RUBRIC, config=CONFIG,
    )
    assert "third_party_page" not in verdict.gates_failed


def test_thresholds_come_from_configuration():
    config = quality_config({"actor_score_thresholds": {"auto_low": 0.5, "auto_high": 0.9},
                             "actor_quality": {"min_evidence_items": 3}})
    assert (config.auto_low, config.auto_high, config.min_evidence_items) == (0.5, 0.9, 3)


def test_an_incoherent_configuration_is_refused():
    with pytest.raises(ValueError):
        QualityConfig(auto_low=0.9, auto_high=0.5)
