// The Intern Guide taxonomy, as the Review screen uses it.
//
// Source of truth: "Actor Categories and Link Types — Intern Guide" (categories,
// category types, link types) and Architecture V2 §5.1–§5.4 (the Light Pull
// fields). Category codes are the stable Phase 5 codes; only labels changed.
// Every label here must match the backend catalog in
// ghus-backend/config/actor_categories.yaml byte for byte — tests/test_review_taxonomy.py
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
  // The stored code is `connected_to_um6p_ocp`: that is what the entity_edge
  // CHECK constraint allows, so it is what arrives from the database. The Guide
  // writes the label with "Entity" on the end, which is what we display.
  ["connected_to_um6p_ocp", "Connected to UM6P/OCP Entity", false, "A documented connection to the master list. Never affects ranking or priority."],
];

// The Intern Guide's Appendix B spells this code with a trailing `_entity`.
// The database does not. Accepting both means a record written under either
// spelling still displays its real label instead of a raw code.
const LINK_TYPE_ALIASES = {connected_to_um6p_ocp_entity: "connected_to_um6p_ocp"};

function canonicalLinkType(code) {
  const value = String(code || "");
  return LINK_TYPE_ALIASES[value] || value;
}

export const PARENT_LINK_TYPES = LINK_TYPES.filter(([, , isParent]) => isParent)
  .map(([value, label, , rule]) => ({ value, label, rule }));

export function linkTypeLabel(code) {
  const canonical = canonicalLinkType(code);
  const found = LINK_TYPES.find(([value]) => value === canonical);
  return found ? found[1] : String(code || "").replaceAll("_", " ");
}

export function isParentLink(code) {
  const canonical = canonicalLinkType(code);
  return PARENT_LINK_TYPES.some(option => option.value === canonical);
}

// ------------------------------------------------------- missingness vocabulary
// Appendix D. These six are never interchangeable. Mixing them is the fastest
// way to turn "we have not looked yet" into "there is nothing there".
export const MISSING = {
  notFound: "Not Found",            // searched, and no evidence exists
  notYetChecked: "Not Yet Collected", // this layer has not run
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
// (ghus-backend/agents/collection/light_pull.py), so a row here resolves
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
  // Rendered by its own box, which reads this same fact. Listing it here too
  // produced two "Why It Matched" boxes, one of them empty.
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

// The sectors in the database, loaded from /api/review/sectors. Once loaded
// they ARE the list - including any sector GHUS added in Review. The constants
// above are only the fallback before (or without) a database.
let DATABASE_SECTORS = [];

export function setSectors(list) {
  DATABASE_SECTORS = (list || [])
    .filter(item => item && item.code)
    .map(item => [String(item.code).toUpperCase(), String(item.name || item.code)]);
}

function knownSectors() {
  return DATABASE_SECTORS.length ? DATABASE_SECTORS : [...THEMATIC_SECTORS, ...NON_THEMATIC_SECTORS];
}

export function sectorLabel(code) {
  const found = [...DATABASE_SECTORS, ...THEMATIC_SECTORS, ...NON_THEMATIC_SECTORS]
    .find(([value]) => value === code);
  return found ? found[1] : String(code || "");
}

// ------------------------------------------------------------------ countries
// ISO 3166-1: code and the short English name. The reviewer picks from this
// rather than typing, because the stored data already carries both "USA" and
// "United States" for the same country (680 and 202 rows in the restored copy),
// which makes every country filter wrong.
//
// COUNTRY_ALIASES maps the spellings already in the data onto the ISO name, so
// an existing record shows its country correctly without anything being
// rewritten underneath it.
const COUNTRY_PAIRS =
  "AF:Afghanistan;AL:Albania;DZ:Algeria;AD:Andorra;AO:Angola;AG:Antigua and Barbuda;" +
  "AR:Argentina;AM:Armenia;AU:Australia;AT:Austria;AZ:Azerbaijan;BS:Bahamas;BH:Bahrain;" +
  "BD:Bangladesh;BB:Barbados;BY:Belarus;BE:Belgium;BZ:Belize;BJ:Benin;BT:Bhutan;" +
  "BO:Bolivia;BA:Bosnia and Herzegovina;BW:Botswana;BR:Brazil;BN:Brunei;BG:Bulgaria;" +
  "BF:Burkina Faso;BI:Burundi;KH:Cambodia;CM:Cameroon;CA:Canada;CV:Cabo Verde;" +
  "CF:Central African Republic;TD:Chad;CL:Chile;CN:China;CO:Colombia;KM:Comoros;" +
  "CG:Congo;CD:Congo (Democratic Republic);CR:Costa Rica;CI:Côte d'Ivoire;HR:Croatia;" +
  "CU:Cuba;CY:Cyprus;CZ:Czechia;DK:Denmark;DJ:Djibouti;DM:Dominica;" +
  "DO:Dominican Republic;EC:Ecuador;EG:Egypt;SV:El Salvador;GQ:Equatorial Guinea;" +
  "ER:Eritrea;EE:Estonia;SZ:Eswatini;ET:Ethiopia;FJ:Fiji;FI:Finland;FR:France;" +
  "GA:Gabon;GM:Gambia;GE:Georgia;DE:Germany;GH:Ghana;GR:Greece;GD:Grenada;" +
  "GT:Guatemala;GN:Guinea;GW:Guinea-Bissau;GY:Guyana;HT:Haiti;HN:Honduras;HU:Hungary;" +
  "IS:Iceland;IN:India;ID:Indonesia;IR:Iran;IQ:Iraq;IE:Ireland;IL:Israel;IT:Italy;" +
  "JM:Jamaica;JP:Japan;JO:Jordan;KZ:Kazakhstan;KE:Kenya;KI:Kiribati;KW:Kuwait;" +
  "KG:Kyrgyzstan;LA:Laos;LV:Latvia;LB:Lebanon;LS:Lesotho;LR:Liberia;LY:Libya;" +
  "LI:Liechtenstein;LT:Lithuania;LU:Luxembourg;MG:Madagascar;MW:Malawi;MY:Malaysia;" +
  "MV:Maldives;ML:Mali;MT:Malta;MH:Marshall Islands;MR:Mauritania;MU:Mauritius;" +
  "MX:Mexico;FM:Micronesia;MD:Moldova;MC:Monaco;MN:Mongolia;ME:Montenegro;MA:Morocco;" +
  "MZ:Mozambique;MM:Myanmar;NA:Namibia;NR:Nauru;NP:Nepal;NL:Netherlands;" +
  "NZ:New Zealand;NI:Nicaragua;NE:Niger;NG:Nigeria;KP:North Korea;" +
  "MK:North Macedonia;NO:Norway;OM:Oman;PK:Pakistan;PW:Palau;PS:Palestine;PA:Panama;" +
  "PG:Papua New Guinea;PY:Paraguay;PE:Peru;PH:Philippines;PL:Poland;PT:Portugal;" +
  "QA:Qatar;RO:Romania;RU:Russia;RW:Rwanda;KN:Saint Kitts and Nevis;LC:Saint Lucia;" +
  "VC:Saint Vincent and the Grenadines;WS:Samoa;SM:San Marino;" +
  "ST:Sao Tome and Principe;SA:Saudi Arabia;SN:Senegal;RS:Serbia;SC:Seychelles;" +
  "SL:Sierra Leone;SG:Singapore;SK:Slovakia;SI:Slovenia;SB:Solomon Islands;" +
  "SO:Somalia;ZA:South Africa;KR:South Korea;SS:South Sudan;ES:Spain;LK:Sri Lanka;" +
  "SD:Sudan;SR:Suriname;SE:Sweden;CH:Switzerland;SY:Syria;TW:Taiwan;TJ:Tajikistan;" +
  "TZ:Tanzania;TH:Thailand;TL:Timor-Leste;TG:Togo;TO:Tonga;TT:Trinidad and Tobago;" +
  "TN:Tunisia;TR:Türkiye;TM:Turkmenistan;TV:Tuvalu;UG:Uganda;UA:Ukraine;" +
  "AE:United Arab Emirates;GB:United Kingdom;US:United States;UY:Uruguay;" +
  "UZ:Uzbekistan;VU:Vanuatu;VA:Vatican City;VE:Venezuela;VN:Vietnam;YE:Yemen;" +
  "ZM:Zambia;ZW:Zimbabwe";

export const COUNTRIES = COUNTRY_PAIRS.split(";").map(pair => {
  const [code, name] = pair.split(":");
  return [code, name];
});

const COUNTRY_BY_NAME = new Map(COUNTRIES.map(([code, name]) => [name.toLocaleLowerCase(), name]));
const COUNTRY_ALIASES = new Map(Object.entries({
  usa: "United States", "u.s.a.": "United States", "u.s.": "United States",
  us: "United States", "united states of america": "United States",
  uk: "United Kingdom", "u.k.": "United Kingdom",
  "great britain": "United Kingdom", england: "United Kingdom",
  korea: "South Korea", "republic of korea": "South Korea",
  "russian federation": "Russia", turkey: "Türkiye",
  "ivory coast": "Côte d'Ivoire", "cape verde": "Cabo Verde",
  "czech republic": "Czechia", swaziland: "Eswatini",
}));

/** The ISO name for a stored country value. Unknown values are kept as stored. */
export function normalizeCountry(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const key = raw.toLocaleLowerCase();
  return COUNTRY_ALIASES.get(key) || COUNTRY_BY_NAME.get(key) || raw;
}

/** Every country, the United States first (most actors are there), then A–Z. */
export function countryOptions() {
  const options = COUNTRIES.map(([, name]) => ({value: name, label: name}));
  return [...options.filter(o => o.value === "United States"),
    ...options.filter(o => o.value !== "United States")];
}

/**
 * Sector options for the Review dropdown.
 *
 * Built from the catalog, so adding a sector to the reference data adds it here
 * with no code change. Any sector already recorded on a record is included even
 * when it is not one of the eight thematic ones, so an existing value is never
 * silently dropped from its own dropdown.
 */
export function sectorOptions(recorded = []) {
  const base = DATABASE_SECTORS.length ? knownSectors() : THEMATIC_SECTORS;
  const options = base.map(([value, label]) => ({value, label}));
  const known = new Set(options.map(option => option.value));
  for (const code of recorded) {
    if (code && !known.has(code)) {
      known.add(code);
      options.push({value: code, label: sectorLabel(code)});
    }
  }
  return options;
}
