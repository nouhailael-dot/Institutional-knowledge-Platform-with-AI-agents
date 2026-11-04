"""Why COMPASS identified an organization: the GHUS fit, from the scoring's own evidence."""

from src.review.postgres_source import ghus_fit


def _item(present, evidence=None):
    return {"present": present, "evidence": evidence}


RUBRIC = {
    "sector_codes": [{"code": "HEALTH", "evidence": "Digital-health and AI companies."}],
    "research_development_or_programmes": _item(False, "Investment activity only."),
    "own_organisational_page": _item(False, "A third-party registry page."),
    "real_operating_entity": _item(True, "Founded 2020 with named staff."),
    "partnership_precedent": _item(True, "Invests in DexCare Series B."),
    "open_programmes": _item(False, "None mentioned."),
    "use_cases": {"corporate_engagement": _item(True, "Corporate venture arm."),
                  "mentorship": _item(False)},
    "hub_matches": [{"name": "Boston- Cambridge Academic Medical Hub"}],
}


def test_the_fit_names_the_ghus_value_and_what_to_check_and_never_claims_the_absent():
    fit = ghus_fit(RUBRIC, {"priority.distinctiveness": 0.0375, "priority_score": 0.225}, "0.450")
    assert fit["strength"] == "weak" and fit["relevance"] == 0.45 and fit["priority"] == 0.225
    assert fit["fits"] == ["Works in HEALTH: Digital-health and AI companies."]
    assert "GHUS use cases: corporate engagement (Corporate venture arm.)" in fit["value"]
    assert "Partnership record: Invests in DexCare Series B." in fit["value"]
    assert "Near the GHUS hub Boston- Cambridge Academic Medical Hub" in fit["value"]
    assert "3 organizations already mapped in that hub and sector" in fit["value"]
    assert not any("Open programmes" in line or "mentorship" in line for line in fit["value"])
    assert "Read from a page about it on another site, not its own website" in fit["concerns"]
    assert "No research, development or programmes named on the page" in fit["concerns"]


def test_the_badge_follows_relevance_and_new_ground_is_said():
    assert ghus_fit(RUBRIC, {}, 0.85)["strength"] == "strong"
    assert ghus_fit(RUBRIC, {}, 0.65)["strength"] == "moderate"
    assert ghus_fit(RUBRIC, {}, None)["strength"] is None
    fit = ghus_fit(RUBRIC, {"priority.distinctiveness": 0.15}, 0.9)
    assert "New ground: no organization is mapped yet in that hub and sector" in fit["value"]
    assert ghus_fit({}, {}, 0.9) is None
