// The Intern Guide taxonomy, as the Review screen uses it.
//
// Source of truth: "Actor Categories and Link Types — Intern Guide" (categories,
// category types, link types) and Architecture V2 §5.1–§5.4 (the Light Pull
// fields). Category codes are the stable Phase 5 codes; only labels changed.
// Every label here must match the backend catalog in
// GHUS-Platform/config/actor_categories.yaml byte for byte — tests/test_review_taxonomy.py
// compares the two and fails on any drift.
//
// Nothing in this file is a free-text string the UI invents. If a value is
// missing, the Review screen says which KIND of missing it is, using MISSING
// below; it never guesses and never shows a blank.

// ---------------------------------------------------------------- categories
// [categoryCode, categoryLabel, [[typeCode, typeLabel, meaning], …]]
// Not Applicable is always last and always present.
export const CATEGORIES = [
  ["university_academic", "University / Academic Institution", [
    ["university_system", "Main Institution", "The university record itself — the top of its own tree"],
    ["academic_department", "Department", "An academic subject-area unit (e.g. Dept. of Plant Sciences)"],
    ["college_school", "College / School", "A larger academic division containing multiple departments"],
    ["research_lab_center", "Research Lab / Center", "A research-focused unit inside the university, not its own degree program"],
    ["tech_transfer_office", "Tech Transfer Office", "Patenting and licensing of university research, not startup support"],
    ["professional_executive_education", "Professional / Executive Education", "Non-degree executive education, certificates and short courses"],
    ["accelerator_incubator", "Accelerator / Incubator", "A university-run startup-support program"],
    ["medical_school", "Medical School", "The degree-granting medical academic unit; the clinical hospital is a separate Category 5 record"],
    ["applied_facility_testbed_field_site", "Applied Facility / Testbed / Field Site", "A university-run physical test or demonstration site, such as a farm or pilot plant"],
    ["extension_outreach_program", "Extension / Outreach Program", "A public or community-facing applied program, such as agricultural extension"],
    ["not_applicable", "Not Applicable", "The university itself with no further sub-unit detail needed, or nothing listed fits"],
  ]],
  ["research_center", "Research Center / Institute / Laboratory", [
    ["independent_institute", "Independent", "Freestanding, with no parent organization of any kind"],
    ["nonprofit_operated", "Nonprofit-Operated", "Run by a nonprofit entity as its primary vehicle"],
    ["corporate_operated", "Corporate-Operated", "Run by or embedded in a company"],
    ["government_affiliated", "Government-Affiliated", "Government-funded, policy-focused or agency-housed, but not formally designated as a national laboratory"],
    ["not_applicable", "Not Applicable", "Nothing listed fits yet"],
  ]],
  ["national_laboratory", "National Laboratory", [
    ["university_operated_affiliated", "University-Operated / Affiliated", "Formally designated national lab whose operating contract is held by a university"],
    ["corporate_operated", "Corporate-Operated", "Operating contract held by a company"],
    ["consortium_operated", "Consortium-Operated", "Operating contract held by a multi-institution consortium"],
    ["government_direct", "Government-Direct", "Run directly by the federal agency with no outside operating contractor"],
    ["not_applicable", "Not Applicable", "Nothing listed fits yet"],
  ]],
  ["applied_facility", "Applied Research Facility / Testbed / Field Site", [
    ["independent", "Independent", "No parent organization"],
    ["government_operated", "Government-Operated", "Run by a federal, state or local agency"],
    ["corporate_operated", "Corporate-Operated", "Run by a company"],
    ["nonprofit_operated", "Nonprofit-Operated", "Run by a nonprofit"],
    ["not_applicable", "Not Applicable", "Nothing listed fits yet"],
  ]],
  ["hospital_clinical", "Hospital / Clinical System / Medical Center", [
    ["independent_standalone", "Independent-Standalone", "No parent system or institution"],
    ["nonprofit_health_system", "Nonprofit Health System", "Part of a larger nonprofit hospital network"],
    ["for_profit_health_system", "For-Profit Health System", "Part of a larger for-profit hospital network"],
    ["public_government_hospital", "Public or Government Hospital", "Operated by a government entity"],
    ["academic_medical_center", "University-Affiliated", "Operated by, or formally tied to, a university medical school; the medical school itself is a separate Category 1 record"],
    ["not_applicable", "Not Applicable", "Nothing listed fits yet"],
  ]],
  ["company", "Company / Corporate Actor", [
    ["public_company", "Public Company", "Publicly traded"],
    ["private_company", "Private Company", "Privately held, not SME-scale"],
    ["small_mid_size", "SME", "Small or medium enterprise, privately held"],
    ["business_unit_subsidiary", "Subsidiary / Business Unit", "A unit of a larger parent company"],
    ["joint_venture", "Joint Venture", "Jointly owned by two or more companies"],
    ["not_applicable", "Not Applicable", "Nothing listed fits yet"],
  ]],
  ["startup", "Startup / Emerging Technology Company", [
    ["independent_startup", "Independent", "Founded and operating with no institutional origin tie"],
    ["university_spinout", "University Spinout", "Founded on university-originated IP or research"],
    ["corporate_spinout", "Corporate Spinout", "Spun out of a company"],
    ["accelerator_portfolio_company", "Accelerator Portfolio Company", "Currently or recently in an accelerator or incubator program"],
    ["not_applicable", "Not Applicable", "Nothing listed fits yet"],
  ]],
  ["innovation_platform", "Innovation & Entrepreneurship (E&I) Platform", [
    ["incubator", "Incubator", "Provides space and resources for early-stage companies over an open-ended term"],
    ["accelerator", "Accelerator", "Runs fixed-term, cohort-based startup programs"],
    ["venture_studio", "Venture Studio", "Builds and launches new ventures itself rather than supporting external founders"],
    ["not_applicable", "Not Applicable", "Nothing listed fits yet"],
  ]],
  ["investor", "Investor / Funding Platform", [
    ["venture_capital", "Venture Capital Firm", "Institutional VC investing from managed funds"],
    ["corporate_venture", "Corporate Venture Arm", "A company's internal investment arm"],
    ["public_investment_fund", "Government Fund", "Public-sector investment vehicle"],
    ["angel_group", "Family Office / Angel Network", "Private individual or family capital, or an organized angel group"],
    ["not_applicable", "Not Applicable", "Nothing listed fits yet"],
  ]],
  ["government", "Government Agency / Public Authority", [
    ["federal_agency", "Federal", "National-level agency"],
    ["state_agency", "State", "State-level agency"],
    ["local_municipal", "Local / Municipal", "City or county-level agency"],
    ["public_utility", "Public Utility", "Government-affiliated utility provider"],
    ["not_applicable", "Not Applicable", "Nothing listed fits yet"],
  ]],
  ["foundation_nonprofit", "Foundation / Nonprofit", [
    ["private_foundation", "Private Foundation", "Privately endowed, typically grant-making"],
    ["operating_nonprofit", "Operating Nonprofit", "Runs its own programs rather than primarily granting funds"],
    ["corporate_foundation", "Corporate Foundation", "A company's affiliated philanthropic arm"],
    ["community_foundation", "Community Foundation", "Pools local or regional donor funds for local grantmaking"],
    ["not_applicable", "Not Applicable", "Nothing listed fits yet"],
  ]],
  ["association_network", "Association / Consortium / Network", [
    ["trade_association", "Trade Association", "Represents a commercial industry's shared interests"],
    ["research_consortium", "Research Consortium", "Multi-member group organized around shared research; each member links in as Member of, never as parent or child"],
    ["innovation_consortium", "Innovation Consortium", "Multi-member group organized around innovation or commercialization themes rather than research"],
    ["multi_location_network", "Statewide / Multi-Location Network", "One parent record, with each individual physical location mapped as its own linked child actor"],
    ["professional_network", "Professional Network", "Organized around a shared profession or role, not research or innovation"],
    ["diaspora_network", "Diaspora Network", "Organized around shared national or regional origin"],
    ["not_applicable", "Not Applicable", "Nothing listed fits yet"],
  ]],
];

export const NOT_APPLICABLE = "not_applicable";
// The Phase 5 catch-all. Retired: it still DISPLAYS on records that hold it, so
// history stays readable, but it is never offered in a dropdown.
export const RETIRED_CATCH_ALL = "other";

const CATEGORY_INDEX = new Map(CATEGORIES.map(([code, label, types]) => [code, { label, types }]));

export function categoryOptions() {
  return CATEGORIES.map(([value, label]) => ({ value, label }));
}

/** Only the chosen category's types. An unknown category offers nothing. */
export function typeOptions(categoryCode) {
  const entry = CATEGORY_INDEX.get(String(categoryCode || ""));
  if (!entry) return [];
  return entry.types.map(([value, label, meaning]) => ({ value, label, meaning }));
}

export function categoryLabel(code) {
  return CATEGORY_INDEX.get(String(code || ""))?.label || "";
}

/** The stored label for a type, retired values included. */
export function typeLabel(categoryCode, typeCode) {
  const found = typeOptions(categoryCode).find(option => option.value === typeCode);
  if (found) return found.label;
  return typeCode === RETIRED_CATCH_ALL ? "Other (Retired)" : "";
}

export function isValidPair(categoryCode, typeCode) {
  return typeOptions(categoryCode).some(option => option.value === typeCode);
}

// ------------------------------------------------------------------- regions
// Appendix C. Derived from the state, never entered by hand, and read-only in
// Review. DC is Mid-Atlantic and WA is West Coast / Pacific; both are checked
// by test, because both have been got wrong before.
export const REGIONS = [
  ["northeast", "Northeast", ["CT", "ME", "MA", "NH", "NY", "RI", "VT"]],
  ["mid_atlantic", "Mid-Atlantic", ["DE", "MD", "NJ", "PA", "VA", "WV", "DC"]],
  ["southeast", "Southeast", ["AL", "FL", "GA", "KY", "MS", "NC", "SC", "TN"]],
  ["midwest_great_lakes", "Midwest / Great Lakes", ["IL", "IN", "IA", "KS", "MI", "MN", "MO", "NE", "ND", "OH", "SD", "WI"]],
  ["south_central_texas_gulf", "South Central / Texas Gulf", ["AR", "LA", "OK", "TX"]],
  ["mountain_west", "Mountain West / Rocky Mountain", ["AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY"]],
  ["west_coast_pacific", "West Coast / Pacific", ["AK", "CA", "HI", "OR", "WA"]],
];

export const STATE_NAMES = {
  AK: "Alaska", AL: "Alabama", AR: "Arkansas", AZ: "Arizona", CA: "California",
  CO: "Colorado", CT: "Connecticut", DC: "Washington DC", DE: "Delaware",
  FL: "Florida", GA: "Georgia", HI: "Hawaii", IA: "Iowa", ID: "Idaho",
  IL: "Illinois", IN: "Indiana", KS: "Kansas", KY: "Kentucky", LA: "Louisiana",
  MA: "Massachusetts", MD: "Maryland", ME: "Maine", MI: "Michigan",
  MN: "Minnesota", MO: "Missouri", MS: "Mississippi", MT: "Montana",
  NC: "North Carolina", ND: "North Dakota", NE: "Nebraska", NH: "New Hampshire",
  NJ: "New Jersey", NM: "New Mexico", NV: "Nevada", NY: "New York", OH: "Ohio",
  OK: "Oklahoma", OR: "Oregon", PA: "Pennsylvania", RI: "Rhode Island",
  SC: "South Carolina", SD: "South Dakota", TN: "Tennessee", TX: "Texas",
  UT: "Utah", VA: "Virginia", VT: "Vermont", WA: "Washington", WI: "Wisconsin",
  WV: "West Virginia", WY: "Wyoming",
};

const STATE_TO_REGION = new Map();
for (const [code, label, states] of REGIONS) {
  for (const state of states) STATE_TO_REGION.set(state, { code, label });
}
const NAME_TO_STATE = new Map(
  Object.entries(STATE_NAMES).map(([code, name]) => [name.toLocaleLowerCase(), code]),
);

/** A two-letter code for a state given either a code or a full name. */
export function stateCode(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const upper = raw.toLocaleUpperCase();
  if (STATE_NAMES[upper]) return upper;
  return NAME_TO_STATE.get(raw.toLocaleLowerCase()) || "";
}

export const NON_US_REGION = "Not Applicable (Non-US)";

/**
 * Region, derived from the state. Decision D8: read-only, never typed in.
 * A non-US record is "Not Applicable (Non-US)"; a US record with no usable
 * state is "Not Provided", because an absent state is unknown, not N/A.
 */
export function regionForState(state, country) {
  const land = String(country || "").trim().toLocaleUpperCase();
  const isUS = !land || ["US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"].includes(land);
  if (!isUS) return NON_US_REGION;
  const code = stateCode(state);
  if (!code) return MISSING.notProvided;
  return STATE_TO_REGION.get(code)?.label || MISSING.notProvided;
}

export function stateOptions() {
  return Object.entries(STATE_NAMES)
    .map(([value, label]) => ({ value, label: `${label} (${value})` }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

// --------------------------------------------------------------- link types
// Appendix B. Only Unit of and Operated by are parenthood (decision D11);
// everything else is shown read-only under Other Relationships.
export const LINK_TYPES = [
  ["unit_of", "Unit of", true, "The child is an organizational part of the parent, under the parent's governance."],
  ["operated_by", "Operated by", true, "A facility or program run by an organization but with its own identity."],
  ["affiliated_with", "Affiliated with", false, "People only: a person to the organization they are associated with."],
  ["member_of", "Member of", false, "An independent organization to an Association / Consortium / Network it belongs to. Not parenthood."],
  ["portfolio_of", "Portfolio of", false, "A startup in an accelerator, incubator or venture studio program. Not ownership."],
  ["spinout_of", "Spinout of", false, "A startup founded on IP that originated at a university or company."],
  ["funded_by", "Funded by", false, "A grant, investment or award from a funder to the actor."],
  ["collaborates_with", "Collaborates with", false, "A documented partnership that is not parenthood, membership or funding."],
  ["organizes", "Organizes", false, "An actor to an event it runs."],
  ["participates_in", "Participates in", false, "An actor to an event it takes part in without organizing."],
  ["connected_to_um6p_ocp_entity", "Connected to UM6P/OCP Entity", false, "A documented connection to the master list. Never affects ranking or priority."],
];

export const PARENT_LINK_TYPES = LINK_TYPES.filter(([, , isParent]) => isParent)
  .map(([value, label, , rule]) => ({ value, label, rule }));

export function linkTypeLabel(code) {
  const found = LINK_TYPES.find(([value]) => value === code);
  return found ? found[1] : String(code || "").replaceAll("_", " ");
}

export function isParentLink(code) {
  return PARENT_LINK_TYPES.some(option => option.value === code);
}

// ------------------------------------------------------- missingness vocabulary
// Appendix D. These six are never interchangeable. Mixing them is the fastest
// way to turn "we have not looked yet" into "there is nothing there".
export const MISSING = {
  notFound: "Not Found",            // searched, and no evidence exists
  notYetChecked: "Not Yet Checked", // this layer has not run
  notProvided: "Not Provided",      // an optional input is absent (location)
  pending: "Pending Classification", // a legacy NULL category type
  notAvailable: "Not Available",    // there is no parent, and that is complete
  notApplicable: "Not Applicable",  // a deliberate reviewer selection
};

export const NO_PARENT_TOOLTIP =
  "No parent organization recorded. Standalone actors are complete records.";

// --------------------------------------------------- Light Pull fact rows
// Architecture V2 §5.1 common rows, then §5.2 per-category rows (Appendix D).
// The keys are the backend's stable fact-ledger keys
// (GHUS-Platform/agents/collection/light_pull.py), so a row here resolves
// against a real fact or honestly reports which kind of missing it is.
export const COMMON_LIGHT_ROWS = [
  ["official_identity", "Official Identity"],
  ["actor_category_type", "Category and Type"],
  ["parent_connection", "Parent or Connection"],
  ["website", "Website"],
  ["description", "Description"],
  ["location", "Location"],
  ["hub_assignment", "Hub"],
  ["sector_topic", "Sector and Topic"],
  ["why_matched", "Why It Matched"],
  ["recent_activity", "Recent Activity"],
  ["funding_signal", "Funding Signal"],
  ["international_connection", "International / Africa / Morocco Connection"],
  ["um6p_ocp_connection", "UM6P/OCP Connection"],
];

// categoryCode -> [[factKey, rowLabel], …]
export const CATEGORY_LIGHT_ROWS = {
  university_academic: [
    ["topic_unit_and_work", "Relevant School, Department or Lab on the Topic"],
    ["institution_control", "Public or Private"],
    ["land_grant_designation", "Land-Grant or Other Designation"],
    ["rankings", "Rankings"],
    ["relevant_centers_programs", "Main Relevant Centers and Programs"],
  ],
  research_center: [
    ["parent_and_center_type", "Parent and Center Type"],
    ["topic_research_focus", "Research Focus on the Topic"],
    ["active_recent_projects", "Active or Recent Projects"],
    ["main_funders", "Main Funders"],
  ],
  national_laboratory: [
    ["sponsoring_agency", "Sponsoring Agency"],
    ["formal_national_designation", "Formal Designation Confirmed"],
    ["topic_program_area", "Relevant Program Area"],
  ],
  applied_facility: [
    ["facility_type_operator", "Facility Type and Operator"],
    ["testing_demonstration_scope", "What It Tests or Demonstrates"],
    ["current_project", "A Current Project"],
  ],
  hospital_clinical: [
    ["clinical_research_focus", "Clinical or Research Focus on the Topic"],
    ["parent_academic_link", "Parent or Academic Link"],
    ["hospital_type_scale", "Type and Scale"],
    ["current_initiative", "A Current Initiative"],
  ],
  company: [
    ["ownership_and_size", "Public or Private, and Size"],
    ["topic_business_segment_product", "Relevant Business Segment or Product"],
    ["mapped_geography_operations", "Where It Operates in the Mapped Geography"],
  ],
  startup: [
    ["technology_and_problem", "Technology and Problem Addressed"],
    ["founding_year_location", "Founding Year and Location"],
    ["published_stage_or_trl", "Stage or TRL"],
    ["funding_stage", "Funding Stage"],
    ["pilot_customer_evidence", "Pilot or Customer Evidence"],
  ],
  innovation_platform: [
    ["platform_type_operator", "Type and Operator"],
    ["sector_focus", "Sector Focus"],
    ["platform_offerings", "What It Offers"],
    ["scale_indicator", "Scale Indicator"],
  ],
  investor: [
    ["investor_type_headquarters", "Type and Headquarters"],
    ["sector_stage_focus", "Sector and Stage Focus"],
    ["geographic_focus", "Geographic Focus"],
    ["published_fund_size", "Fund Size"],
    ["topic_investment_thesis", "Investment Thesis on the Topic"],
  ],
  government: [
    ["jurisdiction_parent_agency", "Jurisdiction and Parent Agency"],
    ["topic_mandate_program", "Relevant Mandate or Program"],
    ["visible_funding_programs", "Funding Programs"],
  ],
  foundation_nonprofit: [
    ["mission_sector_focus", "Mission and Sector Focus"],
    ["geographic_focus", "Geographic Focus"],
    ["relevant_program", "A Relevant Program"],
    ["programs_grant_themes", "Programs and Grant Themes"],
  ],
  association_network: [
    ["association_type", "Type"],
    ["sector_geographic_scope", "Sector Focus and Geographic Scope"],
    ["member_types", "Member Types"],
    ["current_initiative_working_group", "Current Initiative or Working Group"],
    ["linked_members", "Members"],
    ["network_scope_locations", "Network Scope and Locations"],
  ],
};

// Decision D14. TRL is a Startup row and only when published; rankings are a
// University row. Neither is ever inferred, and a nonprofit never shows a TRL.
export const TRL_CATEGORY = "startup";
export const RANKING_CATEGORY = "university_academic";

export function showsTrl(categoryCode) {
  return categoryCode === TRL_CATEGORY;
}

export function showsRankings(categoryCode) {
  return categoryCode === RANKING_CATEGORY;
}

/** The Light Pull rows for a category, common rows first. */
export function lightRowsFor(categoryCode) {
  const specific = CATEGORY_LIGHT_ROWS[String(categoryCode || "")] || [];
  return [...COMMON_LIGHT_ROWS, ...specific];
}

// ------------------------------------------------------------- sectors
// Decision D13: the eight thematic sectors are selectable. CROSS and DIASPORA
// are read from configuration; until GHUS decides, an existing value on a
// record still displays, read-only.
export const THEMATIC_SECTORS = [
  ["AGRI", "Agriculture"],
  ["WATER", "Water"],
  ["AI", "Artificial Intelligence"],
  ["ENERGY", "Energy"],
  ["MINING", "Mining"],
  ["CHEM", "Chemistry"],
  ["HEALTH", "Health"],
  ["SUSTAIN", "Sustainability"],
];

export const NON_THEMATIC_SECTORS = [
  ["CROSS", "Cross-Cutting"],
  ["DIASPORA", "Diaspora"],
];

export function sectorLabel(code) {
  const found = [...THEMATIC_SECTORS, ...NON_THEMATIC_SECTORS].find(([value]) => value === code);
  return found ? found[1] : String(code || "");
}
