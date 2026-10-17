// The Review label dictionary (Appendix F).
//
// Every string the Review screen shows comes from here. No component hard-codes
// UI text. Two rules, both tested:
//
//   1. Title Case. Principal words are capitalised, including after a hyphen or
//      a slash ("Nonprofit-Operated", "Local / Municipal"). The short function
//      words (a, and, by, for, in, of, or, the, to, with) stay lower case unless
//      they come first ("Unit of", "Public or Government Hospital"). Acronyms
//      stay upper case: UM6P, OCP, TRL, SME, FFRDC, E&I, DC, US.
//   2. Data is never re-cased. Actor names, descriptions, source titles and
//      quotes display exactly as stored. That is why SENTENCES below is kept
//      separate: it holds prose the UI owns, not data it displays.

export const SECTIONS = {
  hubProposals: "Hub Proposals",
  identity: "Identity & Classification",
  location: "Location & Parent",
  sector: "Sector, Topic & Hub",
  facts: "Light Pull Facts",
  duplicates: "Possible Duplicates",
  audit: "Audit & Details",
};

export const BUTTONS = {
  verify: "Verify",
  park: "Park",
  reject: "Reject",
  saveEdits: "Save Edits",
  leaveUnassigned: "Leave Unassigned",
  chooseHub: "Choose Hub",
  continueUpdating: "Continue Updating This Map?",
  refresh: "Refresh Now",
  cancel: "Cancel",
  confirm: "Confirm",
  addSector: "+ Add a New Sector…",
  createSector: "Create Sector",
  addingSector: "Creating…",
};

export const FIELDS = {
  newSectorName: "New Sector Name",
  newSectorDescription: "What the Sector Covers, Optional",
  families: "Independent Families",
  categories: "Matched Categories",
  clusterRadius: "Core / Cluster Radius",
  hubCreated: "Hub Created",
  proposedMembers: "Proposed Members",
  name: "Name",
  otherNames: "Other Names",
  website: "Website",
  description: "Description",
  actorCategory: "Actor Category",
  categoryType: "Category Type",
  classificationNote: "Classification Note",
  country: "Country",
  state: "State",
  region: "Region",
  city: "City",
  coordinates: "Coordinates",
  multiLocation: "Multi-Location",
  parentOrganization: "Parent Organization",
  parentLinkType: "Link Type",
  parentSource: "Source",
  otherRelationships: "Other Relationships",
  sector: "Sector",
  primarySector: "Primary Sector",
  otherSectors: "Also Recorded",
  commonLightPull: "Common Light Pull Fields",
  categoryLightPull: "Category-Specific Fields",
  whyItMatched: "Why It Matched",
  strength: "Strength",
  topic: "Topic",
  hub: "Hub",
  currentHubs: "Current Hub Assignments",
  suggestedHubs: "Suggested Hubs",
  distance: "Distance",
  suggestion: "Suggestion",
  field: "Field",
  value: "Value",
  source: "Source",
  dateRead: "Date Read",
  confidence: "Confidence",
  origin: "Origin",
  um6pOcpConnection: "UM6P/OCP Connection",
  reviewer: "Reviewer",
  notes: "Notes",
  rejectionReason: "Rejection Reason",
  recordKind: "Record Kind",
  reviewState: "Review State",
  reviewReason: "Review Reason",
  sourceRun: "Source Run",
  search: "Search by Name or Domain",
  status: "Status",
  legacyActorType: "Legacy Actor Type",
  candidateId: "Candidate ID",
  runId: "Run ID",
  created: "Created",
  verificationHistory: "Verification History",
  editHistory: "Edit History",
  rawCandidate: "Raw Candidate Data",
  trl: "Stage or TRL",
  rankings: "Rankings",
  ghusNotes: "GHUS Notes",
  ghusEventNotes: "GHUS Event Notes",
  requestedBy: "Requested by",
  requestedVia: "Requested Via",
  lastRun: "Last Run",
  nextDue: "Next Due",
  runs: "Runs",
};

export const BADGES = {
  actor: "Actor",
  event: "Event",
  person: "Person",
  imported: "Imported",
  parked: "Parked",
  verified: "Verified",
  rejected: "Rejected",
  migratedBaseline: "Verified · Migrated Baseline",
  possibleDuplicate: "Possible Duplicate",
  categoryDoubt: "Category Doubt",
  geocodeFailed: "Geocode Failed",
  awaitingVerification: "Awaiting Verification",
  awaitingPersonVerification: "Awaiting Person Verification",
  awaitingEventVerification: "Awaiting Event Verification",
  hubNeedsReview: "Hub Needs Review",
  hubAssignment: "Hub Assignment",
  sameTopicOverlap: "Same Topic Overlap",
  hubRadiusOverlap: "Hub Radius Overlap",
  hubMemberOutsideRadius: "Hub Member Outside Radius",
  hubCenterDrift: "Hub Center Drift",
  hubProposal: "Hub Proposal",
  factConflict: "Fact Conflict",
  pendingUpdate: "Pending Update",
  identityReview: "Identity Review",
  affiliationChange: "Affiliation Change",
  classificationReview: "Classification Review",
  geocodeReview: "Geocode Review",
  newHubProposal: "New Hub Proposal",
  pendingHumanUpdate: "Pending Human Update",
  alreadyExists: "Already Exists",
  newRecord: "New Record",
  notChecked: "Database Match Not Checked",
  testData: "Test Data",
  readOnly: "Read Only",
  active: "Active",
  paused: "Paused",
  expired: "Expired",
  cancelled: "Cancelled",
  dryRun: "Dry Run",
  live: "Live",
  currentlyAssigned: "Currently Assigned",
  suggested: "Suggested",
  hubDimension: "Decides Hub",
  secondary: "Secondary",
  high: "High",
  medium: "Medium",
  low: "Low",
  strong: "Strong",
  moderate: "Moderate",
};

export const QUEUE = {
  title: "Queue",
  preRedesignBacklog: "Pre-Redesign Backlog",
  shown: "Shown",
  allRuns: "All Runs",
  allTypes: "All Types",
  allCategories: "All Categories",
  allSectors: "All Sectors",
  allRegions: "All Regions",
  allReasons: "All Reasons",
  all: "All",
};

export const FACTS = {
  current: "Current",
  history: "History",
  found: "Found",
  notFoundInSources: "Not Found in Sources Read So Far",
  toggleHistory: "Show History",
  toggleCurrent: "Show Current",
};

export const TRIGGERS = {
  manual: "Manual",
  subscription: "Subscription",
  scheduled_event: "Scheduled Event",
  migration: "Migration",
};

// How a subscription was asked for. The database stores a code; a reviewer
// reads words. Raw codes never reach the screen.
export const REQUESTED_VIA = {
  map_verification: "Map Verification",
  review_updates: "Review Updates",
};

export const CADENCES = {
  once: "Once",
  weekly: "Weekly",
  monthly: "Monthly",
  quarterly: "Quarterly",
};

// Prose the UI owns. Full sentences, so normal sentence capitalisation applies
// and the Title Case test skips this block by design.
export const SENTENCES = {
  noSectorMatched: (described) => `No GHUS sector matched this organisation. Its page describes its work as: ${described}. If none of the sectors fits, add a new one.`,
  sectorNeedsReviewer: "Enter your name in the decision section first: a new sector is recorded as your decision.",
  sectorCreated: (name) => `Sector “${name}” added. It is now in every sector list.`,
  sectorExisted: (name) => `Sector “${name}” already exists and has been selected.`,
  noHubCreated: "No — a proposal only.",
  hubProposalsExplain: "Detection proposes; GHUS decides. A proposal never creates a hub — it records a cluster that met every threshold, for a person to accept or refuse.",
  hubProposalsNone: "No open hub proposals. Detection runs produce a proposal only when a cluster meets every threshold.",
  hubProposalsUnavailable: "Hub proposals are unavailable: no PostgreSQL review source is configured.",
  demoLabel: "Example / test data — not GHUS-verified production data.",
  queueEmpty: "No candidates match these filters.",
  queueLoading: "Loading candidates…",
  queueSelectOne: "Select a candidate from the queue.",
  noFacts: "No Light Pull facts have been recorded for this record yet.",
  pageEyebrow: "Human admission control",
  pageTitle: "Review agent discoveries.",
  pageLead:
    "Every record below was found by an agent and parked. Claude proposes; GHUS decides. " +
    "Verify authorises the topic-scoped Deep Pull, Park leaves the record for later, and " +
    "Reject keeps the record with its reason. Nothing here is ever deleted.",
  failClosed:
    "Canonical admission is fail-closed. Apply the emitted migration and configure " +
    "dedicated review-writer credentials to enable decisions.",
  writerUnavailable:
    "The canonical writer is unavailable, so Verify, Park and Reject are disabled. " +
    "No decision can be recorded until it is reachable again.",
  schemaMismatch:
    "The review source does not match the expected schema, so decisions are disabled.",
  noParent: "No parent organization recorded. Standalone actors are complete records.",
  parentPickerRule:
    "Only Unit of and Operated by record parenthood, and each one needs a source. " +
    "Member of, Portfolio of, Spinout of, Funded by and Collaborates with are " +
    "relationships, not parenthood, and are shown read-only below.",
  regionDerived: "Derived from the state. Not editable.",
  membershipsKept:
    "Existing memberships are never replaced or removed here. A member that now sits " +
    "outside the radius is flagged, not dropped.",
  suggestionIsNotADecision:
    "A suggestion is the deterministic rule's proposal, not an assignment. Choose one, " +
    "choose a different hub, or leave the actor unassigned.",
  noHubOption: "Not Applicable — No Hub",
  subscriptionsExplain:
    "Actor updates are opt-in. Each subscription keeps a stated scope current for a " +
    "stated period; nothing outside one is swept. The event update schedule is separate " +
    "and unchanged.",
  subscriptionsNone:
    "No subscriptions yet. One is created when a map is verified, or from here once the " +
    "scheduler contract is built.",
  subscriptionsUnavailable:
    "No PostgreSQL review source is configured, so subscriptions cannot be read.",
  subscriptionNoScope:
    "No scope recorded — this subscription would sweep everything and must not run.",
  hubDropdownRule:
    "Only existing hubs are listed. A new hub is never created here: detection proposes " +
    "one and GHUS decides.",
  lightPullBoxes:
    "These are the Light Pull fields from Architecture V2 Sept, Sections 5.1 and 5.2. " +
    "Every box for this actor category stays visible, including the ones with nothing " +
    "in them, because an empty field is itself an answer.",
  chooseCategoryForBoxes:
    "Choose an Actor Category to see the fields collected for it.",
  deepIsSeparate:
    "Deep Pull evidence, collected only after a GHUS verification. It is not Light Pull.",
  sectorDecidesHub:
    "Hub membership is decided on sector. An actor joins a hub because it works in that " +
    "hub's sector and sits inside its radius.",
  topicIsSecondary:
    "Topic is the specific thing this actor was found for. It is recorded on the record and " +
    "on any hub proposal, but it no longer decides hub membership.",
  categoryChangeWarning:
    "Changing the Actor Category clears the Category Type, because a type belongs to " +
    "exactly one category. Choose a new type before saving.",
  notApplicableNeedsNote:
    "Not Applicable is a deliberate choice, never a stand-in for missing data. " +
    "Give a one-line note saying what the doubt is; this record goes to GHUS for review.",
  pendingClassification:
    "This legacy record has no category type. It is not being treated as Not Applicable.",
  noDeletion: "Record will be kept, not deleted.",
  verifyConsequences:
    "Verifying authorises the topic-scoped Deep Pull, makes this actor eligible for hub " +
    "assignment, and counts it towards hub detection. The decision is kept in history " +
    "permanently.",
  reviewerRequired:
    "There is no authenticated identity yet, so the reviewer name is recorded as typed. " +
    "It is never defaulted or guessed.",
  migratedBaseline:
    "Migrated from the existing canonical map as Verified. No reviewer and no review date " +
    "were recorded, because none exist.",
  duplicatesNoMerge:
    "Compare the records side by side. Nothing is merged automatically.",
  trlStartupOnly: "TRL is recorded for startups only, and only when a source publishes it.",
  rankingsUniversityOnly:
    "Rankings are recorded for universities only. A department never inherits its " +
    "university's ranking.",
  legacyTrl: "A legacy Imported estimate. Not a current TRL.",
  ghusNotesOnly: "GHUS writes this field. Agents never do.",
  eventNotesEmpty: "Empty. GHUS writes this field; agents never do.",
  personDiscoveryDisabled:
    "Person discovery is disabled. Existing person candidates are shown for review only.",
  auditIntro:
    "Identifiers, raw candidate data and legacy fields. Nothing here is part of the " +
    "decision; it is here so the decision can be audited.",
  backlogGroup:
    "Everything found before the redesign cutoff, shown together. The original run is " +
    "unchanged and still visible under Audit & Details.",
  noRunRecorded: "Not Recorded",
};

/** Every label the Title Case rule applies to, for the test to walk. */
export const TITLE_CASE_GROUPS = {
  SECTIONS, BUTTONS, FIELDS, BADGES, QUEUE, FACTS, TRIGGERS, CADENCES, REQUESTED_VIA,
};

export const TITLE_CASE_LOWER_WORDS = new Set([
  "a", "and", "by", "for", "in", "of", "or", "the", "to", "with",
]);

export const ACRONYMS = new Set([
  "UM6P", "OCP", "TRL", "SME", "FFRDC", "E&I", "DC", "US", "ID", "VC", "IP",
  "UM6P/OCP",
]);
