"""The Intern Guide taxonomy, server side.

This mirrors ``frontend/taxonomy.js``. The two are authored separately and kept
honest by ``tests/test_review_taxonomy.py``, which loads the JavaScript module
through Node and compares it against this one pair by pair and label by label.
A drift in either direction fails the test rather than reaching a reviewer.

Category codes are the stable Phase 5 codes, so canonical rows and the hub
algorithm are unaffected; the Intern Guide changed the type codes, the display
labels and the catch-all.
"""

from __future__ import annotations

from typing import Any

NOT_APPLICABLE = "not_applicable"
# The Phase 5 catch-all. Retired: still displayed on the records that hold it,
# never offered for selection.
RETIRED_CATCH_ALL = "other"
CATCH_ALL_TYPE_CODES = (NOT_APPLICABLE, RETIRED_CATCH_ALL)

# (category_code, category_label, ((type_code, type_label, meaning), ...))
CATEGORIES: tuple[tuple[str, str, tuple[tuple[str, str, str], ...]], ...] = (
    ("university_academic", "University / Academic Institution", (
        ("university_system", "Main Institution",
         "The university record itself — the top of its own tree"),
        ("academic_department", "Department",
         "An academic subject-area unit (e.g. Dept. of Plant Sciences)"),
        ("college_school", "College / School",
         "A larger academic division containing multiple departments"),
        ("research_lab_center", "Research Lab / Center",
         "A research-focused unit inside the university, not its own degree program"),
        ("tech_transfer_office", "Tech Transfer Office",
         "Patenting and licensing of university research, not startup support"),
        ("professional_executive_education", "Professional / Executive Education",
         "Non-degree executive education, certificates and short courses"),
        ("accelerator_incubator", "Accelerator / Incubator",
         "A university-run startup-support program"),
        ("medical_school", "Medical School",
         "The degree-granting medical academic unit; the clinical hospital is a separate "
         "Category 5 record"),
        ("applied_facility_testbed_field_site", "Applied Facility / Testbed / Field Site",
         "A university-run physical test or demonstration site, such as a farm or pilot plant"),
        ("extension_outreach_program", "Extension / Outreach Program",
         "A public or community-facing applied program, such as agricultural extension"),
        ("not_applicable", "Not Applicable",
         "The university itself with no further sub-unit detail needed, or nothing listed fits"),
    )),
    ("research_center", "Research Center / Institute / Laboratory", (
        ("independent_institute", "Independent",
         "Freestanding, with no parent organization of any kind"),
        ("nonprofit_operated", "Nonprofit-Operated",
         "Run by a nonprofit entity as its primary vehicle"),
        ("corporate_operated", "Corporate-Operated", "Run by or embedded in a company"),
        ("government_affiliated", "Government-Affiliated",
         "Government-funded, policy-focused or agency-housed, but not formally designated "
         "as a national laboratory"),
        ("not_applicable", "Not Applicable", "Nothing listed fits yet"),
    )),
    ("national_laboratory", "National Laboratory", (
        ("university_operated_affiliated", "University-Operated / Affiliated",
         "Formally designated national lab whose operating contract is held by a university"),
        ("corporate_operated", "Corporate-Operated", "Operating contract held by a company"),
        ("consortium_operated", "Consortium-Operated",
         "Operating contract held by a multi-institution consortium"),
        ("government_direct", "Government-Direct",
         "Run directly by the federal agency with no outside operating contractor"),
        ("not_applicable", "Not Applicable", "Nothing listed fits yet"),
    )),
    ("applied_facility", "Applied Research Facility / Testbed / Field Site", (
        ("independent", "Independent", "No parent organization"),
        ("government_operated", "Government-Operated",
         "Run by a federal, state or local agency"),
        ("corporate_operated", "Corporate-Operated", "Run by a company"),
        ("nonprofit_operated", "Nonprofit-Operated", "Run by a nonprofit"),
        ("not_applicable", "Not Applicable", "Nothing listed fits yet"),
    )),
    ("hospital_clinical", "Hospital / Clinical System / Medical Center", (
        ("independent_standalone", "Independent-Standalone", "No parent system or institution"),
        ("nonprofit_health_system", "Nonprofit Health System",
         "Part of a larger nonprofit hospital network"),
        ("for_profit_health_system", "For-Profit Health System",
         "Part of a larger for-profit hospital network"),
        ("public_government_hospital", "Public or Government Hospital",
         "Operated by a government entity"),
        ("academic_medical_center", "University-Affiliated",
         "Operated by, or formally tied to, a university medical school; the medical school "
         "itself is a separate Category 1 record"),
        ("not_applicable", "Not Applicable", "Nothing listed fits yet"),
    )),
    ("company", "Company / Corporate Actor", (
        ("public_company", "Public Company", "Publicly traded"),
        ("private_company", "Private Company", "Privately held, not SME-scale"),
        ("small_mid_size", "SME", "Small or medium enterprise, privately held"),
        ("business_unit_subsidiary", "Subsidiary / Business Unit",
         "A unit of a larger parent company"),
        ("joint_venture", "Joint Venture", "Jointly owned by two or more companies"),
        ("not_applicable", "Not Applicable", "Nothing listed fits yet"),
    )),
    ("startup", "Startup / Emerging Technology Company", (
        ("independent_startup", "Independent",
         "Founded and operating with no institutional origin tie"),
        ("university_spinout", "University Spinout",
         "Founded on university-originated IP or research"),
        ("corporate_spinout", "Corporate Spinout", "Spun out of a company"),
        ("accelerator_portfolio_company", "Accelerator Portfolio Company",
         "Currently or recently in an accelerator or incubator program"),
        ("not_applicable", "Not Applicable", "Nothing listed fits yet"),
    )),
    ("innovation_platform", "Innovation & Entrepreneurship (E&I) Platform", (
        ("incubator", "Incubator",
         "Provides space and resources for early-stage companies over an open-ended term"),
        ("accelerator", "Accelerator", "Runs fixed-term, cohort-based startup programs"),
        ("venture_studio", "Venture Studio",
         "Builds and launches new ventures itself rather than supporting external founders"),
        ("not_applicable", "Not Applicable", "Nothing listed fits yet"),
    )),
    ("investor", "Investor / Funding Platform", (
        ("venture_capital", "Venture Capital Firm",
         "Institutional VC investing from managed funds"),
        ("corporate_venture", "Corporate Venture Arm", "A company's internal investment arm"),
        ("public_investment_fund", "Government Fund", "Public-sector investment vehicle"),
        ("angel_group", "Family Office / Angel Network",
         "Private individual or family capital, or an organized angel group"),
        ("not_applicable", "Not Applicable", "Nothing listed fits yet"),
    )),
    ("government", "Government Agency / Public Authority", (
        ("federal_agency", "Federal", "National-level agency"),
        ("state_agency", "State", "State-level agency"),
        ("local_municipal", "Local / Municipal", "City or county-level agency"),
        ("public_utility", "Public Utility", "Government-affiliated utility provider"),
        ("not_applicable", "Not Applicable", "Nothing listed fits yet"),
    )),
    ("foundation_nonprofit", "Foundation / Nonprofit", (
        ("private_foundation", "Private Foundation", "Privately endowed, typically grant-making"),
        ("operating_nonprofit", "Operating Nonprofit",
         "Runs its own programs rather than primarily granting funds"),
        ("corporate_foundation", "Corporate Foundation",
         "A company's affiliated philanthropic arm"),
        ("community_foundation", "Community Foundation",
         "Pools local or regional donor funds for local grantmaking"),
        ("not_applicable", "Not Applicable", "Nothing listed fits yet"),
    )),
    ("association_network", "Association / Consortium / Network", (
        ("trade_association", "Trade Association",
         "Represents a commercial industry's shared interests"),
        ("research_consortium", "Research Consortium",
         "Multi-member group organized around shared research; each member links in as "
         "Member of, never as parent or child"),
        ("innovation_consortium", "Innovation Consortium",
         "Multi-member group organized around innovation or commercialization themes "
         "rather than research"),
        ("multi_location_network", "Statewide / Multi-Location Network",
         "One parent record, with each individual physical location mapped as its own "
         "linked child actor"),
        ("professional_network", "Professional Network",
         "Organized around a shared profession or role, not research or innovation"),
        ("diaspora_network", "Diaspora Network",
         "Organized around shared national or regional origin"),
        ("not_applicable", "Not Applicable", "Nothing listed fits yet"),
    )),
)

CATEGORY_LABELS: dict[str, str] = {code: label for code, label, _types in CATEGORIES}
TYPES_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    code: tuple(item[0] for item in types) for code, _label, types in CATEGORIES
}
TYPE_LABELS: dict[tuple[str, str], str] = {
    (code, type_code): type_label
    for code, _label, types in CATEGORIES
    for type_code, type_label, _meaning in types
}

# ----------------------------------------------------------------- regions
# Appendix C. Derived from the state, never entered by hand (decision D8).
REGIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("northeast", "Northeast", ("CT", "ME", "MA", "NH", "NY", "RI", "VT")),
    ("mid_atlantic", "Mid-Atlantic", ("DE", "MD", "NJ", "PA", "VA", "WV", "DC")),
    ("southeast", "Southeast", ("AL", "FL", "GA", "KY", "MS", "NC", "SC", "TN")),
    ("midwest_great_lakes", "Midwest / Great Lakes",
     ("IL", "IN", "IA", "KS", "MI", "MN", "MO", "NE", "ND", "OH", "SD", "WI")),
    ("south_central_texas_gulf", "South Central / Texas Gulf", ("AR", "LA", "OK", "TX")),
    ("mountain_west", "Mountain West / Rocky Mountain",
     ("AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY")),
    ("west_coast_pacific", "West Coast / Pacific", ("AK", "CA", "HI", "OR", "WA")),
)

STATE_NAMES: dict[str, str] = {
    "AK": "Alaska", "AL": "Alabama", "AR": "Arkansas", "AZ": "Arizona",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "DC": "Washington DC", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "IA": "Iowa", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "MA": "Massachusetts", "MD": "Maryland", "ME": "Maine", "MI": "Michigan",
    "MN": "Minnesota", "MO": "Missouri", "MS": "Mississippi", "MT": "Montana",
    "NC": "North Carolina", "ND": "North Dakota", "NE": "Nebraska",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NV": "Nevada", "NY": "New York", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VA": "Virginia", "VT": "Vermont",
    "WA": "Washington", "WI": "Wisconsin", "WV": "West Virginia", "WY": "Wyoming",
}

_STATE_TO_REGION: dict[str, str] = {
    state: label for _code, label, states in REGIONS for state in states
}
_NAME_TO_STATE: dict[str, str] = {name.casefold(): code for code, name in STATE_NAMES.items()}

NON_US_REGION = "Not Applicable (Non-US)"
US_COUNTRY_NAMES = frozenset({"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"})

# ------------------------------------------------- missingness vocabulary
# Appendix D. Never interchangeable.
MISSING = {
    "not_found": "Not Found",
    "not_yet_checked": "Not Yet Checked",
    "not_provided": "Not Provided",
    "pending": "Pending Classification",
    "not_available": "Not Available",
    "not_applicable": "Not Applicable",
}

# --------------------------------------------------------------- link types
# Appendix B. is_parent marks the only two link types the parent picker offers
# (decision D11).
LINK_TYPES: tuple[tuple[str, str, bool], ...] = (
    ("unit_of", "Unit of", True),
    ("operated_by", "Operated by", True),
    ("affiliated_with", "Affiliated with", False),
    ("member_of", "Member of", False),
    ("portfolio_of", "Portfolio of", False),
    ("spinout_of", "Spinout of", False),
    ("funded_by", "Funded by", False),
    ("collaborates_with", "Collaborates with", False),
    ("organizes", "Organizes", False),
    ("participates_in", "Participates in", False),
    ("connected_to_um6p_ocp_entity", "Connected to UM6P/OCP Entity", False),
)
PARENT_LINK_TYPES: tuple[str, ...] = tuple(
    code for code, _label, is_parent in LINK_TYPES if is_parent
)
LINK_TYPE_LABELS: dict[str, str] = {code: label for code, label, _ in LINK_TYPES}

# ----------------------------------------------------------------- sectors
# Decision D13: the eight thematic sectors are selectable.
THEMATIC_SECTORS: tuple[tuple[str, str], ...] = (
    ("AGRI", "Agriculture"), ("WATER", "Water"), ("AI", "Artificial Intelligence"),
    ("ENERGY", "Energy"), ("MINING", "Mining"), ("CHEM", "Chemistry"),
    ("HEALTH", "Health"), ("SUSTAIN", "Sustainability"),
)
NON_THEMATIC_SECTORS: tuple[tuple[str, str], ...] = (
    ("CROSS", "Cross-Cutting"), ("DIASPORA", "Diaspora"),
)

# Decision D14.
TRL_CATEGORY = "startup"
RANKING_CATEGORY = "university_academic"


class TaxonomyError(ValueError):
    """A category, type or pair is not in the Intern Guide catalog."""


def category_codes() -> tuple[str, ...]:
    return tuple(CATEGORY_LABELS)


def type_codes(category_code: str) -> tuple[str, ...]:
    """The selectable types of one category. Retired codes are not included."""

    try:
        return TYPES_BY_CATEGORY[category_code]
    except KeyError as exc:
        raise TaxonomyError(f"unknown actor category {category_code!r}") from exc


def is_valid_pair(category_code: Any, type_code: Any) -> bool:
    return type_code in TYPES_BY_CATEGORY.get(str(category_code or ""), ())


def validate_pair(category_code: Any, type_code: Any, *, allow_null_type: bool = True) -> None:
    """Raise unless the pair is one the Intern Guide allows.

    ``allow_null_type`` covers decision D4: a LEGACY record may carry
    ``category_type = NULL`` and displays as "Pending Classification". A record
    created after the redesign must always carry a type, so the writer path
    calls this with ``allow_null_type=False``.
    """

    category = str(category_code or "").strip()
    if not category:
        raise TaxonomyError("actor category is required")
    if category not in CATEGORY_LABELS:
        raise TaxonomyError(f"{category!r} is not one of the 12 actor categories")
    stored = type_code if type_code is None else str(type_code).strip()
    if not stored:
        if allow_null_type:
            return
        raise TaxonomyError(
            f"a new {category!r} record needs a category type; if none fits, "
            f"choose {NOT_APPLICABLE} and give a one-line note"
        )
    if stored in TYPES_BY_CATEGORY[category]:
        return
    if stored == RETIRED_CATCH_ALL:
        raise TaxonomyError(
            f"{RETIRED_CATCH_ALL!r} is retired; use {NOT_APPLICABLE} with a one-line note"
        )
    owner = next(
        (code for code, types in TYPES_BY_CATEGORY.items() if stored in types), None
    )
    if owner:
        raise TaxonomyError(
            f"category type {stored!r} belongs to {owner!r}, not {category!r}"
        )
    raise TaxonomyError(f"category type {stored!r} is not in the Intern Guide catalog")


def category_label(code: Any) -> str:
    return CATEGORY_LABELS.get(str(code or ""), "")


def type_label(category_code: Any, type_code: Any) -> str:
    """The display label for a stored type, retired values included."""

    key = (str(category_code or ""), str(type_code or ""))
    if key in TYPE_LABELS:
        return TYPE_LABELS[key]
    return "Other (Retired)" if key[1] == RETIRED_CATCH_ALL else ""


def state_code(value: Any) -> str:
    """A two-letter code from either a code or a full state name."""

    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.upper() in STATE_NAMES:
        return raw.upper()
    return _NAME_TO_STATE.get(raw.casefold(), "")


def region_for_state(state: Any, country: Any = None) -> str:
    """Region, derived (decision D8). Never stored from user input.

    A non-US record is "Not Applicable (Non-US)". A US record with no usable
    state is "Not Provided", because an absent state is unknown, not N/A
    (decision D9).
    """

    land = str(country or "").strip().upper()
    if land and land not in US_COUNTRY_NAMES:
        return NON_US_REGION
    code = state_code(state)
    if not code:
        return MISSING["not_provided"]
    return _STATE_TO_REGION.get(code, MISSING["not_provided"])


def shows_trl(category_code: Any) -> bool:
    return str(category_code or "") == TRL_CATEGORY


def shows_rankings(category_code: Any) -> bool:
    return str(category_code or "") == RANKING_CATEGORY


def catalog_payload() -> dict[str, Any]:
    """What ``GET /api/review/catalog`` serves, so the UI never invents a value."""

    return {
        "categories": [
            {
                "code": code,
                "label": label,
                "types": [
                    {"code": type_code, "label": type_label_, "meaning": meaning}
                    for type_code, type_label_, meaning in types
                ],
            }
            for code, label, types in CATEGORIES
        ],
        "regions": [
            {"code": code, "label": label, "states": list(states)}
            for code, label, states in REGIONS
        ],
        "states": [
            {"code": code, "name": name} for code, name in sorted(STATE_NAMES.items())
        ],
        "link_types": [
            {"code": code, "label": label, "is_parent": is_parent}
            for code, label, is_parent in LINK_TYPES
        ],
        "sectors": {
            "thematic": [{"code": code, "label": label} for code, label in THEMATIC_SECTORS],
            "other": [{"code": code, "label": label} for code, label in NON_THEMATIC_SECTORS],
        },
        "missing": dict(MISSING),
        "not_applicable": NOT_APPLICABLE,
        "retired_catch_all": RETIRED_CATCH_ALL,
        "non_us_region": NON_US_REGION,
        "trl_category": TRL_CATEGORY,
        "ranking_category": RANKING_CATEGORY,
    }
