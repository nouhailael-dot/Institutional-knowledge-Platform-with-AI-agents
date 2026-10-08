"""WS1: the Intern Guide catalog is the only selectable taxonomy.

These tests pin the catalog to the Guide document itself. APPENDIX_A below is
transcribed from "Actor Categories and Link Types - Intern Guide" via the
implementation brief's Appendix A, and the display labels are compared byte for
byte: a typo or a re-casing anywhere in the chain fails here rather than
reaching a reviewer's screen.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agents.common.actor_classification import (
    CATCH_ALL_TYPE_CODES,
    NOT_APPLICABLE,
    RETIRED_CATCH_ALL,
    ActorClassification,
    ActorClassificationError,
    ClassificationEvidence,
    load_category_catalog,
    validate_actor_classification,
)
from scripts.taxonomy_intern_guide_mapping import (
    EXACT,
    MAPPING,
    OUTPUT,
    REVIEW,
    build_rows,
    phase5_pairs,
    render,
)

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "agents" / "sql" / "510_v2_intern_guide_taxonomy.sql"
ROLLBACK = ROOT / "agents" / "sql" / "rollback" / "510_v2_intern_guide_taxonomy.sql"

# Appendix A, in order. (category code, category label, [(type code, type label)])
APPENDIX_A: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
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

TITLE_CASE_LOWER_WORDS = frozenset({"a", "and", "by", "for", "in", "of", "or", "the", "to", "with"})
ACRONYMS = frozenset({"UM6P", "OCP", "TRL", "SME", "FFRDC", "E&I", "DC", "US", "VC", "IP", "(E&I)"})


def test_runtime_catalog_is_appendix_a_byte_for_byte():
    catalog = load_category_catalog()
    assert len(catalog.categories) == len(APPENDIX_A)
    for category, (code, label, types) in zip(catalog.categories, APPENDIX_A, strict=True):
        assert category.code == code
        assert category.label == label, f"{code}: category label drifted from Appendix A"
        actual = tuple((item.code, item.label) for item in category.types)
        assert actual == types, f"{code}: type codes or labels drifted from Appendix A"


def test_migration_seeds_exactly_appendix_a():
    sql = MIGRATION.read_text(encoding="utf-8")
    body = sql.split("INSERT INTO actor_category_type_definition", 1)[1].split(
        "ON CONFLICT (category_code, type_code)", 1
    )[0]
    seeded = re.findall(r"\('([a-z_]+)','([a-z_0-9]+)','([^']*)',(\d+),true,", body)
    expected = [
        (code, type_code, label, str(position))
        for code, _label, types in APPENDIX_A
        for position, (type_code, label) in enumerate(types, start=1)
    ]
    assert seeded == expected


def test_every_category_has_exactly_one_selectable_not_applicable():
    catalog = load_category_catalog()
    for category in catalog.categories:
        codes = catalog.type_codes(category.code)
        assert codes.count(NOT_APPLICABLE) == 1
        assert codes[-1] == NOT_APPLICABLE


def test_retired_phase5_types_are_not_selectable_but_are_preserved():
    catalog = load_category_catalog()
    guide = {
        (category.code, item.code)
        for category in catalog.categories
        for item in category.types
    }
    retired = [pair for pair in phase5_pairs() if pair not in guide]
    assert retired, "the Guide retires Phase 5 types; the fixture cannot be empty"
    # Not selectable anywhere in the runtime catalog...
    for category_code, type_code in retired:
        assert not catalog.validates(category_code, type_code)
    # ...but never deleted: the migration retires rows and the rollback can
    # restore every one of them.
    migration = MIGRATION.read_text(encoding="utf-8")
    assert "DELETE FROM actor_category_type_definition" not in migration
    assert "SET active = false" in migration
    rollback = ROLLBACK.read_text(encoding="utf-8")
    for _category_code, type_code in retired:
        assert f"'{type_code}'" in rollback


def test_the_retired_catch_all_is_still_accepted_on_read_but_never_offered():
    catalog = load_category_catalog()
    assert RETIRED_CATCH_ALL in CATCH_ALL_TYPE_CODES
    assert NOT_APPLICABLE in CATCH_ALL_TYPE_CODES
    for category in catalog.categories:
        assert RETIRED_CATCH_ALL not in catalog.type_codes(category.code)


@pytest.mark.parametrize(
    ("category_code", "foreign_type"),
    [
        ("company", "medical_school"),
        ("university_academic", "venture_studio"),
        ("startup", "public_company"),
        ("investor", "trade_association"),
        ("hospital_clinical", "research_lab_center"),
        ("government", "private_foundation"),
    ],
)
def test_cross_category_pairs_are_rejected(category_code, foreign_type):
    evidence = ClassificationEvidence(main_job="Official self-description.")
    with pytest.raises(ActorClassificationError, match="does not belong"):
        validate_actor_classification(
            ActorClassification(category_code, foreign_type, None, False, evidence)
        )


@pytest.mark.parametrize("category_code", [code for code, _label, _types in APPENDIX_A])
def test_not_applicable_always_requires_a_note(category_code):
    evidence = ClassificationEvidence(main_job="Official self-description.")
    with pytest.raises(ActorClassificationError, match="requires category_note"):
        validate_actor_classification(
            ActorClassification(category_code, NOT_APPLICABLE, None, False, evidence)
        )
    accepted = validate_actor_classification(
        ActorClassification(
            category_code, NOT_APPLICABLE, "Nothing listed fits the self-description.",
            True, evidence,
        )
    )
    assert accepted.category_type == NOT_APPLICABLE


@pytest.mark.parametrize(
    "label",
    [label for _code, _cat, types in APPENDIX_A for _tcode, label in types]
    + [label for _code, label, _types in APPENDIX_A],
)
def test_every_catalog_label_is_title_case(label):
    for position, word in enumerate(re.split(r"[\s/]+", label)):
        for part in word.split("-"):
            bare = part.strip("()")
            if not bare or not bare[0].isalpha():
                continue
            if bare.upper() in ACRONYMS:
                assert part == part.upper() or part.startswith("("), f"{label}: {part}"
                continue
            if position > 0 and bare.lower() in TITLE_CASE_LOWER_WORDS:
                assert part == part.lower(), f"{label}: {part} should stay lower case"
                continue
            assert part[0].isupper(), f"{label}: {part} should start with a capital"


def test_mapping_covers_every_phase5_pair_and_is_deterministic():
    rows = build_rows(None)
    assert len(rows) == 65
    assert len(MAPPING) == 65
    assert render(rows) == render(build_rows(None))
    assert OUTPUT.read_text(encoding="utf-8") == render(rows)


def test_every_category_changing_mapping_is_review_only():
    changed = [
        (old, new) for old, new in MAPPING.items() if new[0] != old[0]
    ]
    assert changed, "the Guide moves at least the tech transfer office and the university lab"
    for (old_category, old_type), (new_category, _new_type, rule, reason) in changed:
        assert rule == REVIEW, f"{old_category}/{old_type} changes category and must be review"
        assert "CATEGORY CHANGE" in reason or "category change" in reason


def test_phase5_other_maps_to_not_applicable_everywhere():
    for (old_category, old_type), (new_category, new_type, rule, reason) in MAPPING.items():
        if old_type != RETIRED_CATCH_ALL:
            continue
        assert new_category == old_category
        assert new_type == NOT_APPLICABLE
        assert rule == EXACT
        assert "category_doubt" in reason
