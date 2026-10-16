"""The Intern Guide catalog is identical in the API, the UI and the brief.

Three copies of the taxonomy exist for good reasons: Python validates writes,
JavaScript drives the dropdowns, and Appendix A of the implementation brief is
what GHUS signed off. These tests make drift between them impossible to merge.

APPENDIX_A below is transcribed from the brief, which in turn quotes "Actor
Categories and Link Types - Intern Guide". Labels are compared byte for byte.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.review.taxonomy import (  # noqa: E402
    CATEGORIES,
    LINK_TYPE_ALIASES,
    LINK_TYPE_LABELS,
    LINK_TYPES,
    MISSING,
    NON_US_REGION,
    NOT_APPLICABLE,
    PARENT_LINK_TYPES,
    REGIONS,
    RETIRED_CATCH_ALL,
    STATE_NAMES,
    TaxonomyError,
    catalog_payload,
    category_label,
    is_valid_pair,
    region_for_state,
    type_label,
    validate_pair,
)

ROOT = Path(__file__).resolve().parents[1]
TAXONOMY_JS = ROOT / "frontend" / "taxonomy.js"

# Appendix A, in order: (category code, category label, ((type code, type label), ...))
APPENDIX_A = (
    ("university_academic", "University / Academic Institution", (
        ("university_system", "Main Institution"),
        ("academic_department", "Department"),
        ("college_school", "College / School"),
        ("research_lab_center", "Research Lab / Center"),
        ("tech_transfer_office", "Tech Transfer Office"),
        ("professional_executive_education", "Professional / Executive Education"),
        ("accelerator_incubator", "Accelerator / Incubator"),
        ("medical_school", "Medical School"),
        ("applied_facility_testbed_field_site", "Applied Facility / Testbed / Field Site"),
        ("extension_outreach_program", "Extension / Outreach Program"),
        ("not_applicable", "Not Applicable"),
    )),
    ("research_center", "Research Center / Institute / Laboratory", (
        ("independent_institute", "Independent"),
        ("nonprofit_operated", "Nonprofit-Operated"),
        ("corporate_operated", "Corporate-Operated"),
        ("government_affiliated", "Government-Affiliated"),
        ("not_applicable", "Not Applicable"),
    )),
    ("national_laboratory", "National Laboratory", (
        ("university_operated_affiliated", "University-Operated / Affiliated"),
        ("corporate_operated", "Corporate-Operated"),
        ("consortium_operated", "Consortium-Operated"),
        ("government_direct", "Government-Direct"),
        ("not_applicable", "Not Applicable"),
    )),
    ("applied_facility", "Applied Research Facility / Testbed / Field Site", (
        ("independent", "Independent"),
        ("government_operated", "Government-Operated"),
        ("corporate_operated", "Corporate-Operated"),
        ("nonprofit_operated", "Nonprofit-Operated"),
        ("not_applicable", "Not Applicable"),
    )),
    ("hospital_clinical", "Hospital / Clinical System / Medical Center", (
        ("independent_standalone", "Independent-Standalone"),
        ("nonprofit_health_system", "Nonprofit Health System"),
        ("for_profit_health_system", "For-Profit Health System"),
        ("public_government_hospital", "Public or Government Hospital"),
        ("academic_medical_center", "University-Affiliated"),
        ("not_applicable", "Not Applicable"),
    )),
    ("company", "Company / Corporate Actor", (
        ("public_company", "Public Company"),
        ("private_company", "Private Company"),
        ("small_mid_size", "SME"),
        ("business_unit_subsidiary", "Subsidiary / Business Unit"),
        ("joint_venture", "Joint Venture"),
        ("not_applicable", "Not Applicable"),
    )),
    ("startup", "Startup / Emerging Technology Company", (
        ("independent_startup", "Independent"),
        ("university_spinout", "University Spinout"),
        ("corporate_spinout", "Corporate Spinout"),
        ("accelerator_portfolio_company", "Accelerator Portfolio Company"),
        ("not_applicable", "Not Applicable"),
    )),
    ("innovation_platform", "Innovation & Entrepreneurship (E&I) Platform", (
        ("incubator", "Incubator"),
        ("accelerator", "Accelerator"),
        ("venture_studio", "Venture Studio"),
        ("not_applicable", "Not Applicable"),
    )),
    ("investor", "Investor / Funding Platform", (
        ("venture_capital", "Venture Capital Firm"),
        ("corporate_venture", "Corporate Venture Arm"),
        ("public_investment_fund", "Government Fund"),
        ("angel_group", "Family Office / Angel Network"),
        ("not_applicable", "Not Applicable"),
    )),
    ("government", "Government Agency / Public Authority", (
        ("federal_agency", "Federal"),
        ("state_agency", "State"),
        ("local_municipal", "Local / Municipal"),
        ("public_utility", "Public Utility"),
        ("not_applicable", "Not Applicable"),
    )),
    ("foundation_nonprofit", "Foundation / Nonprofit", (
        ("private_foundation", "Private Foundation"),
        ("operating_nonprofit", "Operating Nonprofit"),
        ("corporate_foundation", "Corporate Foundation"),
        ("community_foundation", "Community Foundation"),
        ("not_applicable", "Not Applicable"),
    )),
    ("association_network", "Association / Consortium / Network", (
        ("trade_association", "Trade Association"),
        ("research_consortium", "Research Consortium"),
        ("innovation_consortium", "Innovation Consortium"),
        ("multi_location_network", "Statewide / Multi-Location Network"),
        ("professional_network", "Professional Network"),
        ("diaspora_network", "Diaspora Network"),
        ("not_applicable", "Not Applicable"),
    )),
)

# Appendix C, verbatim.
APPENDIX_C = {
    "Northeast": {"CT", "ME", "MA", "NH", "NY", "RI", "VT"},
    "Mid-Atlantic": {"DE", "MD", "NJ", "PA", "VA", "WV", "DC"},
    "Southeast": {"AL", "FL", "GA", "KY", "MS", "NC", "SC", "TN"},
    "Midwest / Great Lakes": {"IL", "IN", "IA", "KS", "MI", "MN", "MO", "NE", "ND", "OH", "SD", "WI"},
    "South Central / Texas Gulf": {"AR", "LA", "OK", "TX"},
    "Mountain West / Rocky Mountain": {"AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY"},
    "West Coast / Pacific": {"AK", "CA", "HI", "OR", "WA"},
}


def _python_catalog() -> list[dict[str, object]]:
    return [
        {
            "code": code,
            "label": label,
            "types": [
                {"code": type_code, "label": type_label_, "meaning": meaning}
                for type_code, type_label_, meaning in types
            ],
        }
        for code, label, types in CATEGORIES
    ]


def _javascript_catalog() -> dict[str, object] | None:
    """Load frontend/taxonomy.js through Node and dump it as JSON.

    Skipped rather than failed when Node is absent, so a Python-only
    environment still runs the rest of the suite. CI has Node.
    """

    node = shutil.which("node")
    if node is None:
        return None
    script = (
        "import('file:///' + process.argv[1].replace(/\\\\/g, '/')).then(module => {"
        "  const out = {"
        "    categories: module.CATEGORIES.map(([code, label, types]) => ({"
        "      code, label,"
        "      types: types.map(([c, l, m]) => ({code: c, label: l, meaning: m})),"
        "    })),"
        "    regions: module.REGIONS.map(([code, label, states]) => ({code, label, states})),"
        "    states: module.STATE_NAMES,"
        "    link_types: module.LINK_TYPES.map(([code, label, isParent]) => ({code, label, isParent})),"
        "    missing: module.MISSING,"
        "    not_applicable: module.NOT_APPLICABLE,"
        "    retired_catch_all: module.RETIRED_CATCH_ALL,"
        "    non_us_region: module.NON_US_REGION,"
        "    thematic: module.THEMATIC_SECTORS.map(([code, label]) => ({code, label})),"
        "  };"
        "  process.stdout.write(JSON.stringify(out));"
        "});"
    )
    completed = subprocess.run(
        [node, "--input-type=module", "-e", script, str(TAXONOMY_JS)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
        cwd=str(ROOT), env={**os.environ, "NODE_OPTIONS": ""},
    )
    if completed.returncode != 0:
        raise AssertionError(f"could not load {TAXONOMY_JS.name}: {completed.stderr.strip()}")
    return json.loads(completed.stdout)


# --------------------------------------------------------------- Appendix A

def test_python_catalog_is_appendix_a_byte_for_byte():
    assert len(CATEGORIES) == len(APPENDIX_A) == 12
    for (code, label, types), (expected_code, expected_label, expected_types) in zip(
        CATEGORIES, APPENDIX_A, strict=True
    ):
        assert code == expected_code
        assert label == expected_label, f"{code}: category label drifted from Appendix A"
        actual = tuple((item[0], item[1]) for item in types)
        assert actual == expected_types, f"{code}: types drifted from Appendix A"


def test_catalog_has_sixty_nine_types_and_one_not_applicable_each():
    assert sum(len(types) for _code, _label, types in CATEGORIES) == 69
    for code, _label, types in CATEGORIES:
        codes = [item[0] for item in types]
        assert codes.count(NOT_APPLICABLE) == 1, code
        assert codes[-1] == NOT_APPLICABLE, f"{code} must list Not Applicable last"
        assert RETIRED_CATCH_ALL not in codes, f"{code} still offers the retired catch-all"
        assert len(set(codes)) == len(codes), code
        assert all(item[2].strip() for item in types), f"{code} has a type with no meaning"


def test_javascript_catalog_matches_python_exactly():
    """The dropdowns and the validator can never disagree."""

    catalog = _javascript_catalog()
    if catalog is None:
        pytest.skip("Node is not available in this environment")
    assert catalog["categories"] == _python_catalog()
    assert catalog["not_applicable"] == NOT_APPLICABLE
    assert catalog["retired_catch_all"] == RETIRED_CATCH_ALL
    assert catalog["non_us_region"] == NON_US_REGION
    assert catalog["states"] == STATE_NAMES
    assert catalog["missing"] == {
        "notFound": MISSING["not_found"],
        "notYetChecked": MISSING["not_yet_checked"],
        "notProvided": MISSING["not_provided"],
        "pending": MISSING["pending"],
        "notAvailable": MISSING["not_available"],
        "notApplicable": MISSING["not_applicable"],
    }
    assert [(row["code"], row["label"], row["isParent"]) for row in catalog["link_types"]] == [
        list(item) and (item[0], item[1], item[2]) for item in LINK_TYPES
    ]
    assert [(row["code"], row["label"], tuple(row["states"])) for row in catalog["regions"]] == [
        (code, label, states) for code, label, states in REGIONS
    ]


def test_served_catalog_payload_is_complete():
    payload = catalog_payload()
    assert [row["code"] for row in payload["categories"]] == [code for code, _l, _t in CATEGORIES]
    assert len(payload["states"]) == 51, "50 states plus DC"
    assert payload["missing"] == MISSING
    assert payload["trl_category"] == "startup"
    assert payload["ranking_category"] == "university_academic"
    assert [row["code"] for row in payload["sectors"]["thematic"]] == [
        "AGRI", "WATER", "AI", "ENERGY", "MINING", "CHEM", "HEALTH", "SUSTAIN"
    ]


# ------------------------------------------------------------ pair validation

@pytest.mark.parametrize(
    ("category", "type_code"),
    [(code, type_code) for code, _label, types in APPENDIX_A for type_code, _tl in types],
)
def test_every_appendix_a_pair_validates(category, type_code):
    validate_pair(category, type_code, allow_null_type=False)
    assert is_valid_pair(category, type_code)
    assert type_label(category, type_code)


@pytest.mark.parametrize(
    ("category", "foreign_type"),
    [
        ("company", "medical_school"),
        ("university_academic", "venture_studio"),
        ("startup", "public_company"),
        ("investor", "trade_association"),
        ("hospital_clinical", "research_lab_center"),
        ("government", "private_foundation"),
        ("association_network", "incubator"),
    ],
)
def test_cross_category_pairs_are_refused_with_a_clear_message(category, foreign_type):
    assert not is_valid_pair(category, foreign_type)
    with pytest.raises(TaxonomyError) as error:
        validate_pair(category, foreign_type)
    # The message names both sides, so a 422 tells the caller what to fix.
    assert foreign_type in str(error.value)
    assert category in str(error.value)


def test_the_retired_catch_all_cannot_be_selected_but_still_displays():
    with pytest.raises(TaxonomyError, match="retired"):
        validate_pair("company", RETIRED_CATCH_ALL)
    # History stays readable: a record already holding it shows a real label.
    assert type_label("company", RETIRED_CATCH_ALL) == "Other (Retired)"


def test_a_legacy_null_type_passes_but_a_new_record_must_carry_one():
    # Decision D4: legacy NULL is allowed and displays as Pending Classification.
    validate_pair("company", None, allow_null_type=True)
    validate_pair("company", "", allow_null_type=True)
    with pytest.raises(TaxonomyError, match="needs a category type"):
        validate_pair("company", None, allow_null_type=False)
    with pytest.raises(TaxonomyError, match=NOT_APPLICABLE):
        validate_pair("company", "", allow_null_type=False)


def test_an_unknown_category_or_type_is_refused():
    with pytest.raises(TaxonomyError, match="not one of the 12"):
        validate_pair("aggregate", "university_system")
    with pytest.raises(TaxonomyError, match="required"):
        validate_pair("", "university_system")
    with pytest.raises(TaxonomyError, match="not in the Intern Guide catalog"):
        validate_pair("company", "a_type_that_never_existed")


def test_category_labels_resolve_and_unknown_codes_stay_empty():
    assert category_label("innovation_platform") == "Innovation & Entrepreneurship (E&I) Platform"
    assert category_label("nope") == ""
    assert type_label("company", "nope") == ""


# ------------------------------------------------------------------- regions

def test_region_mapping_matches_appendix_c_exactly():
    actual = {label: set(states) for _code, label, states in REGIONS}
    assert actual == APPENDIX_C
    assert sum(len(states) for states in actual.values()) == 51


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("DC", "Mid-Atlantic"),
        ("Washington DC", "Mid-Atlantic"),
        ("WA", "West Coast / Pacific"),
        ("Washington", "West Coast / Pacific"),
        ("CA", "West Coast / Pacific"),
        ("TX", "South Central / Texas Gulf"),
        ("ma", "Northeast"),
    ],
)
def test_region_is_derived_from_the_state(state, expected):
    assert region_for_state(state) == expected
    assert region_for_state(state, "United States") == expected


def test_a_missing_state_is_not_provided_and_a_non_us_record_is_not_applicable():
    # Decision D9: an absent location is unknown, never Not Applicable.
    assert region_for_state(None) == MISSING["not_provided"]
    assert region_for_state("") == MISSING["not_provided"]
    assert region_for_state("Nowhere", "US") == MISSING["not_provided"]
    # Decision D8: a non-US record says so explicitly.
    assert region_for_state("Casablanca", "Morocco") == NON_US_REGION
    assert region_for_state(None, "France") == NON_US_REGION


# ---------------------------------------------------------------- link types

def test_only_unit_of_and_operated_by_are_parenthood():
    # Decision D11. portfolio_of and member_of are relationships, not parents.
    assert PARENT_LINK_TYPES == ("unit_of", "operated_by")
    non_parent = {code for code, _label, is_parent in LINK_TYPES if not is_parent}
    assert {"member_of", "portfolio_of", "spinout_of", "funded_by", "collaborates_with"} <= non_parent
    assert "affiliated_with" in non_parent


def test_all_eleven_guide_link_types_are_present():
    assert len(LINK_TYPES) == 11
    # These codes are the ones the database stores: they match the
    # entity_edge_relationship_type_check constraint in the Architecture V2
    # target schema exactly. Appendix B of the Guide spells the last one with a
    # trailing `_entity`; the database does not, so the alias below carries the
    # Guide's spelling without letting the UI emit a code the DB would reject.
    assert {code for code, _label, _p in LINK_TYPES} == {
        "unit_of", "operated_by", "affiliated_with", "member_of", "portfolio_of",
        "spinout_of", "funded_by", "collaborates_with", "organizes", "participates_in",
        "connected_to_um6p_ocp",
    }
    assert LINK_TYPE_ALIASES == {"connected_to_um6p_ocp_entity": "connected_to_um6p_ocp"}
    assert LINK_TYPE_LABELS["connected_to_um6p_ocp"] == "Connected to UM6P/OCP Entity"


def test_the_six_missingness_words_are_distinct():
    values = list(MISSING.values())
    assert len(set(values)) == len(values) == 6
    assert values == [
        "Not Found", "Not Yet Collected", "Not Provided", "Pending Classification",
        "Not Available", "Not Applicable",
    ]
