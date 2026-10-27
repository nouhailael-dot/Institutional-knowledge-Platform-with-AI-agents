// The GHUS Review screen.
//
// Claude proposes; GHUS decides. Every control here records a human decision as
// a new fact; nothing is overwritten and nothing is deleted. The screen is
// organised as the Architecture V2 Light Pull defines it: Identity &
// Classification, Location & Parent, Sector/Topic & Hub, Light Pull Facts,
// Possible Duplicates, and a collapsed Audit & Details that holds the IDs and
// raw data. Raw UUIDs and debug strings never appear in the main view.
//
// Vocabularies come from taxonomy.js; UI text comes from labels.js. Nothing in
// this file invents a label or a value, and a missing value always says WHICH
// kind of missing it is — Not Found, Not Yet Collected, Not Provided, Pending
// Classification, Not Available, Not Applicable — because those six are not
// interchangeable.

import {
  CATEGORY_LIGHT_ROWS, COMMON_LIGHT_ROWS, MISSING, NON_US_REGION, NOT_APPLICABLE,
  NO_PARENT_TOOLTIP, RETIRED_CATCH_ALL, THEMATIC_SECTORS,
  categoryLabel, categoryOptions, countryOptions, isParentLink, isValidPair,
  linkTypeLabel, normalizeCountry, regionForState, sectorLabel, sectorOptions, setSectors,
  showsRankings, showsTrl, stateOptions, typeLabel, typeOptions,
} from "./taxonomy.js?v=20261019";
import {
  BADGES, BUTTONS, CADENCES, FACTS, FIELDS, QUEUE, SECTIONS, SENTENCES,
  TRIGGERS,
} from "./labels.js?v=20261015";
import {usDate, usDateTime} from "./dates.js?v=20261027a";

export const REVIEW_STATUS_LABELS = {
  pending_review: BADGES.parked,
  approved: BADGES.verified,
  rejected_by_reviewer: BADGES.rejected,
};
export const RECORD_STATUS_LABELS = {
  imported: BADGES.imported,
  parked: BADGES.parked,
  verified: BADGES.verified,
  rejected: BADGES.rejected,
};
export const DUPLICATE_LABELS = {
  new: BADGES.newRecord,
  already_exists: BADGES.alreadyExists,
  possible_duplicate: BADGES.possibleDuplicate,
  not_checked: BADGES.notChecked,
};
// Every review_kind the sources emit, with a distinct label each. Two kinds
// never share a label: a reviewer filtering the queue has to be able to tell
// them apart, and "Verified" would read as a decision that has already been
// made rather than one that is waiting.
export const REVIEW_REASON_LABELS = {
  verify_actor: BADGES.awaitingVerification,
  verify_person: BADGES.awaitingPersonVerification,
  verify_event: BADGES.awaitingEventVerification,
  category_doubt: "Category Unsure",
  geocode_failed: BADGES.geocodeFailed,
  hub_needs_review: BADGES.hubNeedsReview,
  hub_assignment: "Hub to Confirm",
  hub_radius_overlap: BADGES.hubRadiusOverlap,
  hub_member_outside_radius: BADGES.hubMemberOutsideRadius,
  hub_center_drift: BADGES.hubCenterDrift,
  hub_proposal: BADGES.hubProposal,
  same_topic_overlap: "Overlaps Another Hub",
  possible_duplicate: BADGES.possibleDuplicate,
  fact_conflict: "Different Value Found",
  actor_update: "Update to Check",
  pending_update: "Change to a GHUS Value",
  // The remaining kinds the review_item CHECK constraint allows. Without these
  // a real queue row would show a raw lower-case code.
  identity: BADGES.identityReview,
  affiliation_change: BADGES.affiliationChange,
  classification: "Category to Confirm",
  geocode: "Location to Confirm",
  new_hub: BADGES.newHubProposal,
  pending_human_update: BADGES.pendingHumanUpdate,
  // Why an item waits for a person, as the review store derives it from what
  // its source recorded (src/review/store.py derive_review_reason). These
  // replace the sources' internal codes - rubric_band, fuzzy_match,
  // relationship_review - which read as nothing to a reviewer.
  borderline_score: "Borderline Score",
  data_feed: "Supplied by GHUS (Data Feed)",
  third_party_page: "Read From Another Site",
  website_unverified: "Website Not Confirmed",
  page_not_organisation: "A Page, Not an Organisation",
  focus_unconfirmed: "Sub-topic Not Confirmed",
  thin_evidence: "Too Little Evidence",
  weak_description: "Description Too Thin",
  low_priority: "Low Engagement Priority",
  new_person: "New Person to Confirm",
  new_record: "New Record to Confirm",
  location_unplaced: "Location Not on the Map",
  relationship_check: "Link to Confirm",
  map_agent: "Proposed by Build the Map",
};

/** One sentence per reason: what the agent could not settle, and so asks you. */
export const REVIEW_REASON_HINTS = {
  borderline_score: "The agent scored it between reject and accept, so a person decides.",
  data_feed: "GHUS supplied it through the Data Feed; a person decides whether it is added.",
  third_party_page: "It was read from a page about the organisation on someone else's site, not its own.",
  website_unverified: "The page states no website of its own, so who published it is unconfirmed.",
  page_not_organisation: "The description reads like a web page or portal, not an organisation.",
  focus_unconfirmed: "Its own pages do not use the sub-topic words the request asked for.",
  thin_evidence: "Too few of the scoring criteria are evidenced on its page to accept it unseen.",
  weak_description: "The description is missing, too short, or a slogan.",
  low_priority: "Relevant, but its engagement priority is below what accepting it unseen needs.",
  new_person: "People are never added without a person's decision.",
  new_record: "A new record found by discovery, waiting for a decision.",
  possible_duplicate: "It may already be on the map; confirm it is new, or the same one.",
  location_unplaced: "Its address could not be placed on the map; give the city and state.",
  relationship_check: "A link between two organisations needs confirming before it is shown.",
  map_agent: "Proposed by a Build the Map run, waiting for a decision.",
  verify_actor: "On the map but not yet verified for this topic; Deep Pull needs this.",
  category_doubt: "The agent was unsure which category fits; choose one.",
  hub_assignment: "The hub this actor was placed in needs confirming.",
  same_topic_overlap: "It sits in two hubs on the same topic; keep the right one.",
  classification: "Its category or type needs a person to confirm.",
  geocode: "Its location was placed, but needs confirming.",
  fact_conflict: "An update found a different value from weaker or older evidence; the map keeps its value until you choose.",
  actor_update: "What an actor update wrote, with its sources. Already on the map; say it looks right or flag it.",
  pending_update: "An update found a different value for one GHUS set; GHUS values change only by your decision.",
};

export function reviewReasonHint(value) {
  return REVIEW_REASON_HINTS[value] || "";
}

/**
 * A run in the run filter: what it was, and how many of its items still wait.
 * The trigger is added only when one was recorded - "Manual" is the fallback
 * for an unrecorded trigger, and printed on every run it told a reader nothing
 * (and was wrong for the map's own checks).
 */
export function runOptionLabel(group = {}) {
  const trigger = group.trigger && group.trigger !== "manual" ? group.trigger_label : null;
  const waiting = Number(group.pending_count || 0);
  return [group.label, trigger].filter(Boolean).join(" · ") + (waiting ? ` (${waiting})` : "");
}

/**
 * The reason filter's options: only reasons actually waiting, most first.
 * It used to list every reason that could ever exist (34, from "Hub Center
 * Drift" to "Same Topic Overlap"), most of them never present. A chosen
 * reason stays listed even if nothing matches it any more.
 */
export function reasonOptions(counts = {}, chosen = "all") {
  const rows = Object.entries(counts || {}).filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1] || reviewReasonLabel(a[0]).localeCompare(reviewReasonLabel(b[0])));
  if (chosen && chosen !== "all" && !rows.some(([kind]) => kind === chosen)) rows.push([chosen, 0]);
  return rows;
}
export const RECORD_KIND_LABELS = {actor: BADGES.actor, event: BADGES.event, person: BADGES.person};

export const REJECTION_REASONS = [
  "Not relevant to GHUS sectors",
  "Not an organisation / event / person page",
  "Duplicate of an existing record",
  "Outside target geography",
  "Past event with no useful participants",
  "Insufficient evidence on the page",
  "Other",
];

export function reviewStatusLabel(value) {
  return REVIEW_STATUS_LABELS[value] || String(value || "").replaceAll("_", " ");
}

export function reviewReasonLabel(value) {
  if (!value) return "";
  return REVIEW_REASON_LABELS[value] || String(value).replaceAll("_", " ");
}

// actor_topic.match_strength and actor_fact.confidence are controlled values
// stored lower case. They are vocabulary, not source data, so they display as
// labels; an unrecognised value is shown as stored rather than guessed at.
export const MATCH_STRENGTH_LABELS = {strong: BADGES.strong, moderate: BADGES.moderate};
export const CONFIDENCE_LABELS = {high: BADGES.high, medium: BADGES.medium, low: BADGES.low};

export function matchStrengthLabel(value) {
  const key = String(value || "").toLocaleLowerCase();
  return MATCH_STRENGTH_LABELS[key] || value || MISSING.notFound;
}

export function confidenceLabel(value) {
  const key = String(value || "").toLocaleLowerCase();
  return CONFIDENCE_LABELS[key] || value || null;
}

// Candidate IDs and run UUIDs belong in Audit & Details, never in a queue row
// or a header. This strips them from a run description without touching the
// stored value.
const DISCOVERY_UUID =
  /(?:discovery:|v2-review:)?[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/gi;

export function reviewRunLabel(source = {}) {
  const raw = String(source.run_label || source.description || source.source_description || "").trim();
  const cleaned = raw
    .replace(DISCOVERY_UUID, "")
    .replace(/\s*·\s*(?=·|$)/g, "")
    .replace(/[\s·:—-]+$/g, "")
    .trim();
  if (cleaned && !/^discovery$/i.test(cleaned)) return cleaned;
  const entity = String(source.entity_type || "").trim().toLocaleLowerCase();
  return entity
    ? `${entity.charAt(0).toLocaleUpperCase() + entity.slice(1)} discovery`
    : "Discovery Run";
}

export function runChip(candidate = {}) {
  const parts = [reviewRunLabel(candidate)];
  const trigger = TRIGGERS[candidate.run_trigger];
  if (trigger) parts.push(trigger);
  if (candidate.run_group_key === "pre_redesign_backlog") parts.push(QUEUE.preRedesignBacklog);
  return parts.join(" · ");
}

export function filterReviewCandidates(candidates, filters = {}) {
  const needle = String(filters.search || "").trim().toLocaleLowerCase();
  return (candidates || []).filter(candidate => {
    if (filters.status && filters.status !== "all" && candidate.status !== filters.status) return false;
    if (filters.entity_type && filters.entity_type !== "all" && candidate.entity_type !== filters.entity_type) return false;
    if (filters.source_run_id && candidate.source_run_id !== filters.source_run_id) return false;
    if (filters.run_group && filters.run_group !== "all" && candidate.run_group_key !== filters.run_group) return false;
    if (filters.review_reason && filters.review_reason !== "all" && candidate.review_reason !== filters.review_reason) return false;
    if (filters.actor_category && filters.actor_category !== "all"
        && String(candidate.reviewed_payload?.actor_category || "") !== filters.actor_category) return false;
    return !needle || JSON.stringify([
      candidate.display_name,
      candidate.reviewed_payload?.website,
      candidate.reviewed_payload,
    ]).toLocaleLowerCase().includes(needle);
  });
}

/** Queue groups in render order: the backlog first, then one group per run. */
// ------------------------------------------------------------- runs (left panel)
// Review is organised Run Type -> named run -> records -> one record's review.

/** The Run Type dropdown: exactly these six, in this order. */
export const RUN_TYPE_OPTIONS = [
  {value: "all", label: "All Runs"},
  {value: "discovery_actors", label: "Discovery Actors"},
  {value: "discovery_events", label: "Discovery Events"},
  {value: "discovery_people", label: "Discovery People"},
  {value: "actor_updates", label: "Actor Updates"},
  {value: "data_feed", label: "Data Feed Imports"},
];

const RUN_TYPE_NAMES = {
  discovery_actors: "Discovery Actors", discovery_events: "Discovery Events",
  discovery_people: "Discovery People", actor_updates: "Actor Updates", map_checks: "Map Checks",
  data_feed: "Data Feed Imports",
};

export function runTypeName(type) {
  return RUN_TYPE_NAMES[type] || "Run";
}

/**
 * The named runs for the left panel: of the chosen type, with at least one
 * record in the current queue (status, category and search already applied),
 * newest first. Each carries how many of its records are shown.
 */
export function runsForType(groups = [], candidates = [], runType = "all") {
  const shown = new Map();
  for (const candidate of candidates) {
    shown.set(candidate.run_group_key, (shown.get(candidate.run_group_key) || 0) + 1);
  }
  return groups
    .filter(group => runType === "all" || group.run_type === runType)
    .filter(group => shown.get(group.key))
    .map(group => ({...group, shown_count: shown.get(group.key)}));
}

/** "Oct 19, 2026 · 6 pending" - the run's real date and what waits in it. */
export function runMeta(group, status = "pending_review") {
  const word = {pending_review: "pending", approved: "verified", rejected_by_reviewer: "rejected"}[status]
    || "shown";
  return [group.run_date, `${group.shown_count ?? group.pending_count ?? 0} ${word}`]
    .filter(Boolean).join(" · ");
}

/** Records of one run, in queue order. */
export function recordsOfRun(candidates = [], runKey) {
  return runKey ? candidates.filter(candidate => candidate.run_group_key === runKey) : [];
}

/**
 * Who made the record: "Imported" (GHUS supplied it - a Data Feed spreadsheet
 * or form) or "AI-Mapped" (the discovery agent found it). Null for checks the
 * map raised about records already on it.
 */
export function originLabel(candidate) {
  const meta = candidate?.agent_metadata || {};
  if (meta.data_feed) return "Imported";
  if (["search_candidate", "event_review_queue", "person_review_queue"].includes(meta.source_table)) {
    return "AI-Mapped";
  }
  return null;
}

/**
 * The Deep Pull a reviewer may start once they verified an actor for a sector:
 * that actor and exactly that sector, or null. The backend checks the same
 * gate again before it reads and before it writes.
 */
export function deepPullTarget(candidate) {
  const meta = candidate?.agent_metadata || {};
  if (candidate?.status !== "approved" || meta.source_table !== "review_item"
    || meta.review_kind !== "verify_actor" || !meta.entity_id || !meta.topic_code) return null;
  return {key: `${meta.entity_id}:${meta.topic_code}`, actor_id: meta.entity_id,
    topic: meta.topic_code, name: candidate.display_name || candidate.payload?.name || "This actor"};
}

/** "About $0.04; never more than $0.15." Only from real past reads. */
export function deepCostLine(cost) {
  if (!cost) return "";
  const cap = Number(cost.cap_usd);
  const ceiling = Number.isFinite(cap) && cost.cap_usd != null ? `never more than $${cap.toFixed(2)}` : "";
  if (cost.typical_usd == null) {
    return ceiling ? `No past reads to estimate from; ${ceiling}.` : "";
  }
  return `About $${Number(cost.typical_usd).toFixed(2)}${ceiling ? `; ${ceiling}` : ""}.`;
}

/** What a finished Deep Pull did, in one sentence. */
export function deepResultLine(checked = {}, applied = null) {
  const results = applied?.results || [];
  const written = results.filter(r => r.written);
  const found = written.filter(r => r.actual !== "not_found").length;
  const missing = written.filter(r => r.actual === "not_found").length;
  const failed = results.length - written.length;
  const parts = [`Deep Pull done: ${found} ${found === 1 ? "item" : "items"} found on its pages`];
  if (missing) parts.push(`${missing} not stated (recorded as Not Found)`);
  if (applied?.review_items) parts.push(`${applied.review_items} waiting in Review`);
  if (failed) parts.push(`${failed} could not be written`);
  if (!applied) parts.splice(0, 1, "Deep Pull done: its pages state none of the selected items, so nothing was written");
  return `${parts.join(", ")}. Cost $${Number(checked.cost_usd || 0).toFixed(2)}.`;
}

/** A record row's second line: what it is and why it waits. */
export function recordRowNote(candidate) {
  const meta = candidate?.agent_metadata || {};
  if (meta.review_kind === "actor_profile") {
    const runs = (meta.update_runs || []).length;
    const changes = (meta.changes || []).length;
    return [`${runs} update${runs === 1 ? "" : "s"}`,
      changes ? `${changes} change${changes === 1 ? "" : "s"} to review` : "nothing to decide"].join(" · ");
  }
  if (meta.source_table === "actor_update") return "Update result · check what it wrote";
  const kind = RECORD_KIND_LABELS[candidate?.entity_type] || candidate?.entity_type || "";
  const origin = originLabel(candidate);
  const quality = qualityOf(candidate);
  if (quality?.completeness) return [kind, origin, quality.label].filter(Boolean).join(" · ");
  const reason = candidate?.review_reason ? reviewReasonLabel(candidate.review_reason) : "";
  return [kind, origin, reason].filter(Boolean).join(" · ");
}

export function groupQueue(candidates, groups = []) {
  const byKey = new Map();
  for (const group of groups) byKey.set(group.key, {...group, candidates: []});
  const loose = [];
  for (const candidate of candidates || []) {
    const bucket = byKey.get(candidate.run_group_key);
    if (bucket) bucket.candidates.push(candidate);
    else loose.push(candidate);
  }
  const ordered = [...byKey.values()].filter(group => group.candidates.length);
  if (loose.length) {
    ordered.push({
      key: "unrecorded", label: SENTENCES.noRunRecorded, is_backlog: false,
      trigger_label: null, candidates: loose,
    });
  }
  return ordered;
}

export function editableReviewPayload(candidate, draft) {
  return Object.fromEntries((candidate?.editable_fields || [])
    .filter(field => Object.prototype.hasOwnProperty.call(draft || {}, field))
    .map(field => [field, draft[field]]));
}

// Review items about one box's value: the decision is between two values.
export const FACT_REVIEW_KINDS = ["fact_conflict", "pending_update"];

export function isFactReview(candidate) {
  return twoWayKind(candidate) === "fact";
}

/**
 * Review items decided by one of two answers - no rejection reason, no record
 * created: a fact conflict, a proposed link between two actors, or a hub an
 * unassigned actor now fits. null for everything else.
 */
export function twoWayKind(candidate) {
  const meta = candidate?.agent_metadata || {};
  if (meta.source_table === "actor_update") return "update";
  if (meta.source_table !== "review_item") return null;
  if (FACT_REVIEW_KINDS.includes(meta.review_kind)) return "fact";
  if (meta.review_kind === "relationship_review") return "relationship";
  if (meta.review_kind === "hub_assignment" && meta.pipeline?.proposal === "membership") return "hub";
  return null;
}

const TWO_WAY_ANSWERS = {
  fact: ["Use the new value", "Keep the current value"],
  relationship: ["Confirm the link", "Not a link"],
  hub: ["Add to the hub", "Keep it out"],
  update: ["Looks right", "Flag it (the map is not changed)"],
};

const LINK_WORDS = {
  collaborates_with: "works with", funded_by: "is funded by", unit_of: "is a unit of",
  member_of: "is a member of", operated_by: "is operated by", portfolio_of: "is backed by",
  spinout_of: "is a spin-out of",
};

/** What a link or hub proposal asks, in one sentence, with its evidence. */
export function twoWaySummary(candidate) {
  const meta = candidate?.agent_metadata || {};
  const pipeline = meta.pipeline || {};
  const name = candidate?.display_name || candidate?.reviewed_payload?.name || "This actor";
  if (twoWayKind(candidate) === "relationship") {
    const other = meta.candidate_name || "another actor on the map";
    const words = LINK_WORDS[pipeline.proposed_relationship_type] || "is linked to";
    // The stored direction: subject -> object. The item's actor is the subject
    // unless the proposal says otherwise.
    const subjectIsThis = !pipeline.subject_actor_id || pipeline.subject_actor_id === meta.entity_id;
    return {
      question: subjectIsThis ? `${name} ${words} ${other}?` : `${other} ${words} ${name}?`,
      source_url: pipeline.source_url || null,
      detail: pipeline.source_url ? "Read on this page by an actor update."
        : "No source page is recorded for this link, so it can only be refused or left.",
    };
  }
  if (twoWayKind(candidate) === "hub") {
    const evidence = pipeline.deterministic_evidence || {};
    const hub = meta.proposed_hub_name || "a hub";
    return {
      question: `Add ${name} to ${hub}?`,
      source_url: null,
      detail: [evidence.sector_code && `Same sector (${evidence.sector_code})`,
        evidence.distance_miles != null && `${evidence.distance_miles} miles from the centre, `
          + `inside its ${evidence.radius_miles}-mile radius`,
        "it is in no hub of that sector yet"].filter(Boolean).join("; ") + ".",
    };
  }
  return null;
}

// ------------------------------------------------------------ actor updates
// One profile per actor: what its updates found is shown in its own boxes, and
// only the changes that need a person are listed below them.

// ------------------------------------------------- discovered people and events
// The agent's quality checks and the facts it read from the page, each with
// its quote (backend agents/discovery/quality_gates.py and page_facts.py).

const COMPLETENESS_WORDS = {
  complete: "Complete", incomplete: "Incomplete", insufficient: "Not enough to keep",
};
const OUTCOME_WORDS = {
  qualified: "Qualified for Review", needs_research: "Needs More Research", excluded: "Excluded",
};
const TIMING_WORDS = {
  upcoming: "Upcoming", past: "Past", date_unconfirmed: "Date unconfirmed", cancelled: "Cancelled",
};
const CHECK_WORDS = {
  identity: "Identity", source: "Official source", affiliation: "Current affiliation",
  relevance: "GHUS relevance", completeness: "Completeness", freshness: "Date",
  location: "Place or format",
};

/**
 * A list, whatever arrived: staged records stored before 2026-10-24 carried
 * Python's text of a tuple ("('a', 'b')"), and joining that crashed the page.
 */
export function asList(value) {
  if (Array.isArray(value)) return value;
  if (typeof value !== "string" || !value.trim()) return [];
  const text = value.trim();
  if (/^[([]/.test(text)) {
    const items = [...text.matchAll(/'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"/g)]
      .map(m => (m[1] ?? m[2]).replace(/\\(.)/g, "$1"));
    if (items.length) return items;
    if (/^[([]\s*,?\s*[)\]]$/.test(text)) return [];   // an empty tuple or list
  }
  return [text];
}

/** The quality checks of a discovered person or event, or null for anything else. */
export function qualityOf(candidate) {
  const quality = candidate?.agent_metadata?.quality;
  if (!quality || typeof quality !== "object") return null;
  return {
    completeness: quality.completeness || null,
    label: COMPLETENESS_WORDS[quality.completeness] || "Not checked",
    decision: quality.decision || null,
    outcome: OUTCOME_WORDS[quality.outcome] || null,
    whyMatched: quality.why_matched || null,
    timing: TIMING_WORDS[quality.freshness] || null,
    reasons: asList(quality.reasons),
    checks: asList(quality.checks).filter(check => check && typeof check === "object").map(check => ({
      name: CHECK_WORDS[check.name] || check.name,
      state: check.passed === true ? "ok" : check.passed === false ? "missing" : "unknown",
      detail: check.detail || "",
    })),
    missing: asList(quality.missing_mandatory),
    priorityMissing: asList(quality.missing_priority),
    conflicts: asList(quality.conflicts),
  };
}

const PERSON_FACT_BOXES = [
  ["bio", "Biography"], ["linkedin_url", "LinkedIn profile"],
  ["department", "Department or unit"], ["expertise", "Expertise"],
  ["relevant_work", "Relevant projects or work"],
  ["work_location", "Work location"], ["other_affiliations", "Other affiliations"],
  ["um6p_ocp_connection", "UM6P / OCP connection"],
];
const EVENT_FACT_BOXES = [
  ["organizer", "Organizer"], ["format", "Format"], ["event_status", "Status"],
  ["registration_url", "Registration"], ["registration_deadline", "Registration deadline"],
  ["themes", "Themes or agenda"], ["speakers", "Confirmed speakers"],
  ["participating_organizations", "Participating organizations"],
  ["standing_claims", "Stated scale or standing"],
  ["um6p_ocp_involvement", "UM6P / OCP involvement"],
];
const FACT_VALUE_WORDS = {in_person: "In person", online: "Online", hybrid: "Hybrid",
  scheduled: "Scheduled", postponed: "Postponed", cancelled: "Cancelled"};

/** One box per fact the agent reads for this kind of record: value, quote and source. */
export function pageFactBoxes(candidate) {
  const facts = candidate?.agent_metadata?.page_facts || {};
  const evidence = facts.evidence || {};
  const read = candidate?.agent_metadata?.quality || facts.evidence;
  const boxes = candidate?.entity_type === "event" ? EVENT_FACT_BOXES : PERSON_FACT_BOXES;
  return boxes.map(([key, label]) => {
    const value = facts[key];
    const has = value !== null && value !== undefined && value !== "" && !(Array.isArray(value) && !value.length);
    const proof = evidence[key] || {};
    return {
      key, label,
      value: has ? (Array.isArray(value) ? value.join(", ") : FACT_VALUE_WORDS[value] || String(value)) : null,
      link: has && /^https?:\/\//.test(String(value)) ? String(value) : null,
      // A bio is its own quote; it is not shown twice.
      quote: proof.quote && proof.quote !== value ? proof.quote : null,
      source: proof.source_url || null,
      dateRead: proof.date_read ? shortDate(proof.date_read) : null,
      // The agent read the page for it: absent means Not Found; never read, Not Yet Collected.
      state: has ? null : read ? MISSING.notFound : MISSING.notYetChecked,
      dropped: (facts.dropped || []).includes(key),
    };
  });
}

/** The event Discovery sends to open an actor's update profile here. */
export const OPEN_IN_REVIEW = "ghus:open-review";

export function isUpdateProfile(candidate) {
  return candidate?.agent_metadata?.review_kind === "actor_profile";
}

function shortDate(value) {
  if (value === null || value === undefined || value === "") return "";
  return usDate(value);
}

function clip(text, length = 90) {
  const value = String(text ?? "");
  return value.length > length ? `${value.slice(0, length - 1)}…` : value;
}

/**
 * Two readings of one box, fact by fact: "Employees: 500 → 600", "Customers:
 * added (2000)". Only for values in parts; plain text has no parts to compare.
 */
export function partChanges(previous, current) {
  const isParts = value => value && typeof value === "object" && !Array.isArray(value);
  if (!isParts(previous) || !isParts(current)) return [];
  const show = value => (Array.isArray(value) ? value.join(", ") : String(value));
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const out = [];
  for (const key of new Set([...Object.keys(current), ...Object.keys(previous)])) {
    if (key === CARRIED_OVER || FACT_DATE_KEYS.has(key)) continue;
    const before = previous[key], after = current[key];
    const had = before !== null && before !== undefined && before !== "";
    const has = after !== null && after !== undefined && after !== "";
    if (had && has && !same(before, after)) {
      out.push({part: key, kind: "changed", text: `${fieldLabel(key)}: ${show(before)} → ${show(after)}`});
    } else if (!had && has) {
      out.push({part: key, kind: "added", text: `${fieldLabel(key)}: added (${show(after)})`});
    }
  }
  return out;
}

const UPDATE_WORDS = {
  new: "New", changed: "Updated", additional: "More detail", confirmed: "Confirmed",
  no_change: "No change",
  not_found: "Not found on its pages", conflict: "Change to review",
  protected: "GHUS value kept", not_yet_collected: "Not read",
};

/**
 * What the latest update found for one box: "Updated · Oct 19, 2026 ·
 * Employees: 500 → 600", or "was: …" for a value written as plain text.
 */
export function updateNote(update, value) {
  if (!update) return "";
  const changes = ["changed", "additional"].includes(update.outcome)
    ? partChanges(update.previous_value, value) : [];
  const outcome = update.outcome === "changed" && changes.length
    && changes.every(change => change.kind === "added") ? "additional" : update.outcome;
  const parts = [UPDATE_WORDS[outcome] || outcome, shortDate(update.date)];
  if (changes.length) {
    parts.push(...changes.map(change => change.text));
  } else if (update.outcome === "changed" && update.previous_value !== null
      && update.previous_value !== undefined) {
    parts.push(`was: ${clip(formatFactValue(update.previous_value), 70)}`);
  }
  return parts.filter(Boolean).join(" · ");
}

const CHANGE_CHOICES = {
  fact: [
    {value: "keep_current", label: "Keep Current Value", done: "the current value stays.",
      consequence: "The value on the map stays current. The new reading is kept in the history, marked not used."},
    {value: "use_new", label: "Use New Value", primary: true, done: "the new value is now current.",
      consequence: "The new value becomes current through the GHUS fact writer. The previous value stays in the history."},
  ],
  keepBoth: {value: "keep_both", label: "Keep Both", done: "both locations are kept.",
    consequence: "The current location stays primary; the new one is added as an additional location, with its source."},
  relationship: [
    {value: "refuse", label: "Not a link", done: "no link is recorded.", consequence: "No link is recorded."},
    {value: "confirm", label: "Confirm the link", primary: true, done: "the link is recorded.",
      consequence: "The link is recorded with its source page."},
  ],
  hub: [
    {value: "refuse", label: "Keep it out", done: "it stays out of the hub.", consequence: "No membership is added."},
    {value: "confirm", label: "Add to the hub", primary: true, done: "it is added to the hub.",
      consequence: "The hub membership is added. Nothing is ever removed from a hub here."},
  ],
};

const CHOICE_WORDS = {
  keep_current: "Kept the current value", use_new: "Used the new value", keep_both: "Kept both",
  confirm: "Confirmed", refuse: "Refused",
};

function side(fact) {
  if (!fact) return null;
  return {
    value: formatFactValue(fact.value),
    source: present(fact.source_url),
    date: shortDate(fact.date_read),
    confidence: confidenceLabel(present(fact.confidence)),
    setBy: fact.set_by === "ghus_human" ? "GHUS" : "Agent",
  };
}

/** The changes waiting on a profile, each with its two values and its choices. */
export function changeRows(candidate) {
  const meta = candidate?.agent_metadata || {};
  const name = candidate?.display_name || candidate?.reviewed_payload?.name || "This actor";
  return (meta.changes || []).map(change => {
    const base = {id: change.review_item_id, kind: change.kind, topic: change.topic_name || null,
      reason: change.reason || ""};
    if (change.kind === "fact") {
      const difference = partChanges(change.current?.value, change.proposed?.value)
        .map(item => item.text).join(" · ");
      return {...base, field: change.field_key, label: factRowLabel(candidate, String(change.field_key || "")),
        previous: side(change.current), proposed: side(change.proposed), difference,
        choices: [...CHANGE_CHOICES.fact, ...(change.can_keep_both ? [CHANGE_CHOICES.keepBoth] : [])]};
    }
    if (change.kind === "relationship") {
      const other = change.candidate_name || "another actor on the map";
      const words = LINK_WORDS[change.relationship_type] || "is linked to";
      const subjectIsThis = !change.subject_actor_id || change.subject_actor_id === meta.entity_id;
      return {...base, label: "Proposed link",
        question: subjectIsThis ? `${name} ${words} ${other}?` : `${other} ${words} ${name}?`,
        source: present(change.source_url),
        reason: change.source_url ? "Named on its own pages by an actor update."
          : "No source page is recorded for this link, so it can only be refused or left.",
        choices: CHANGE_CHOICES.relationship};
    }
    const evidence = change.evidence || {};
    return {...base, label: "Proposed hub", question: `Add ${name} to ${change.hub_name || "a hub"}?`,
      source: null,
      reason: [evidence.sector_code && `Same sector (${evidence.sector_code})`,
        evidence.distance_miles != null && `${evidence.distance_miles} miles from the centre`]
        .filter(Boolean).join("; "),
      choices: CHANGE_CHOICES.hub};
  });
}

/**
 * Other items waiting in Review for the same actor on the map - a location
 * check, a hub, its verification - each with its own decision. Listed on the
 * actor's card so one actor reads as one profile, without merging decisions
 * that need their own form.
 */
export function relatedItems(candidates = [], selected) {
  const actorId = selected?.agent_metadata?.entity_id;
  if (!actorId) return [];
  return candidates
    .filter(item => item.candidate_id !== selected.candidate_id
      && item.agent_metadata?.entity_id === actorId)
    .map(item => ({
      id: item.candidate_id,
      label: isUpdateProfile(item) ? "Actor updates"
        : item.review_reason ? reviewReasonLabel(item.review_reason) : recordRowNote(item),
      run: item.run_label || "",
    }));
}

/** The changes already decided on this actor, newest first. */
export function decidedChangeRows(candidate) {
  return (candidate?.agent_metadata?.decided_changes || []).map(row => ({
    id: row.review_item_id,
    label: row.field_key ? factRowLabel(candidate, row.field_key) : "Proposal",
    choice: CHOICE_WORDS[row.choice] || row.choice,
    by: row.reviewer, date: shortDate(row.decided_at),
  }));
}

const RUN_STATUS_WORDS = {succeeded: "Completed", attention: "Completed with limits", failed: "Failed"};

function countsLine(counts = {}) {
  const words = [["new", "new"], ["changed", "updated"], ["additional", "more detail"],
    ["confirmed", "confirmed"],
    ["conflict", "to review"], ["protected", "GHUS kept"], ["not_found", "not found"]];
  return words.filter(([key]) => counts[key]).map(([key, word]) => `${counts[key]} ${word}`).join(" · ")
    || "nothing new";
}

/** The actor's update runs, newest first: date, name, status and what each found. */
export function updateRunRows(candidate) {
  const meta = candidate?.agent_metadata || {};
  const runs = meta.update_runs || (meta.run_id ? [{
    run_id: meta.run_id, date: candidate.created_at, title: String(candidate.source_description || "")
      .replace(/^Actor update:\s*/, ""), status: meta.run_status, pages_read: meta.pages_read || [],
    counts: Object.fromEntries(Object.entries((meta.written || []).reduce((acc, fact) => {
      const key = fact.lifecycle_state === "conflict_flagged" ? "conflict"
        : fact.lifecycle_state === "pending_update" ? "protected"
        : fact.collection_state !== "found" ? "not_found"
        : fact.previous_value != null ? "changed" : "new";
      acc[key] = (acc[key] || 0) + 1;
      return acc;
    }, meta.corroborated ? {confirmed: meta.corroborated} : {}))),
  }] : []);
  return runs.map(run => ({
    id: run.run_id, date: shortDate(run.date), title: run.title || "Actor update",
    status: RUN_STATUS_WORDS[run.status] || run.status || "",
    summary: countsLine(run.counts), sector: run.topic_name || null,
    pages: (run.pages_read || []).filter(Boolean),
  }));
}

function updateHistoryBlock(html, candidate) {
  const runs = updateRunRows(candidate);
  if (!runs.length) return null;
  return html`<section class="review-section">
    <h3>Update history</h3>
    <p class="review-hint">Every update of this organization, newest first. What they found is
      in its boxes above; earlier values stay in Fact History.</p>
    <ul class="review-update-runs">
      ${runs.map(run => html`<li key=${run.id}>
        <div><strong>${run.title}</strong><span>${[run.date, run.status, run.sector].filter(Boolean).join(" · ")}</span></div>
        <small>${run.summary}${run.pages.length > 0 && html` · pages read:
          ${run.pages.map((url, index) => html`${index ? ", " : " "}<a href=${url} target="_blank"
            rel="noreferrer">${pageLabel(url)}</a>`)}`}</small>
      </li>`)}
    </ul>
  </section>`;
}

function collectedBlock(html, candidate) {
  const quality = qualityOf(candidate);
  const boxes = pageFactBoxes(candidate);
  if (!quality && boxes.every(box => box.state === MISSING.notYetChecked)) return null;
  return html`<section class="review-section">
    <h3>Collected information</h3>
    ${quality && html`<div class=${"review-quality " + (quality.completeness || "")}>
      <div class="review-quality-head"><strong>${quality.outcome
        ? `${quality.outcome} · ${quality.label}` : quality.label}</strong>
        ${quality.timing && html`<span class="review-chip">${quality.timing}</span>`}
        <span>${quality.reasons.join(" ")}</span></div>
      ${quality.whyMatched && html`<p class="review-hint"><strong>Why it matched:</strong> ${quality.whyMatched}</p>`}
      <ul class="review-checks">${quality.checks.map(check => html`<li key=${check.name}
        class=${check.state}><strong>${check.name}</strong> ${check.detail}</li>`)}</ul>
      ${quality.missing.length > 0 && html`<p class="review-hint">Not confirmed: ${quality.missing.join(", ")}.</p>`}
      ${quality.priorityMissing.length > 0 && html`<p class="review-hint">Not found on the page:
        ${quality.priorityMissing.join(", ")}.</p>`}
      ${quality.conflicts.map((conflict, index) => html`<p class="review-message error" key=${index}>${conflict}</p>`)}
    </div>`}
    <div class="review-boxes">${boxes.map(box => html`<div class="review-box light-box" key=${box.key}>
      <dt>${box.label}</dt>
      <dd>${box.state ? html`<span class="review-missing">${box.state}</span>`
        : box.link ? html`<a href=${box.link} target="_blank" rel="noreferrer">${box.value}</a>` : box.value}</dd>
      ${box.quote && html`<small>“${box.quote}”</small>`}
      ${(box.source || box.dateRead) && html`<small>${box.source
        ? html`<a href=${box.source} target="_blank" rel="noreferrer">Source</a>` : ""}${box.dateRead
        ? ` · read ${box.dateRead}` : ""}</small>`}
    </div>`)}</div>
  </section>`;
}

function changesBlock(html, candidate, {onDecide, disabled, reviewer, setReviewer}) {
  const rows = changeRows(candidate);
  const decided = decidedChangeRows(candidate);
  if (!rows.length && !decided.length) return null;
  const pending = candidate?.status === "pending_review";
  return html`<section class="review-section review-changes">
    <h3>Changes to Review ${rows.length > 0 && html`<span class="review-chip">${rows.length}</span>`}</h3>
    ${!rows.length && html`<p class="review-hint">Every change has been decided.</p>`}
    ${rows.length > 0 && pending && html`<label class="review-field review-changes-reviewer">
      <span>Reviewer</span>
      <input value=${reviewer} onInput=${e => setReviewer(e.target.value)} placeholder="Your name"/></label>`}
    ${rows.map(row => html`<div class="review-change" key=${row.id}>
      <div class="review-change-head"><strong>${row.label}</strong>
        ${row.topic && html`<span class="review-chip">${row.topic}</span>`}</div>
      ${row.kind === "fact" ? html`<div class="review-change-values">
          ${[["Current value", row.previous], ["Newly collected", row.proposed]].map(([title, value]) => html`
            <div key=${title}><span class="review-change-label">${title}</span>
              <p>${value ? value.value : MISSING.notFound}</p>
              ${value && html`<small>${value.source
                ? html`<a href=${value.source} target="_blank" rel="noreferrer">Source</a>` : MISSING.notFound}
                ${value.date && ` · read ${value.date}`}${value.confidence && ` · ${value.confidence}`}
                · set by ${value.setBy}</small>`}
            </div>`)}
        </div>`
        : html`<p>${row.question}${row.source && html` <a href=${row.source} target="_blank"
            rel="noreferrer">Open the page</a>`}</p>`}
      ${row.difference && html`<p class="review-change-difference">${row.difference}</p>`}
      ${row.reason && html`<p class="review-hint">${row.reason}</p>`}
      ${pending && html`<div class="review-change-actions">
        ${row.choices.map(choice => html`<button key=${choice.value}
          class=${"btn " + (choice.primary ? "" : "ghost")} disabled=${disabled || !reviewer.trim()}
          onClick=${() => onDecide(row, choice)}>${choice.label}</button>`)}
      </div>`}
    </div>`)}
    ${decided.length > 0 && html`<details class="review-subsection"><summary>${decided.length} decided</summary>
      <ul class="review-evidence">${decided.map(row => html`<li key=${row.id}>
        <strong>${row.label}</strong> <span>${row.choice}</span> <span>${row.by} · ${row.date}</span>
      </li>`)}</ul></details>`}
  </section>`;
}

function twoWayBlock(html, candidate) {
  const summary = twoWaySummary(candidate);
  if (!summary) return null;
  return html`<section class="review-section">
    <h3>${summary.question}</h3>
    <p>${summary.detail}${summary.source_url && html` <a href=${summary.source_url}
      target="_blank" rel="noreferrer">Open the page</a>`}</p>
    <p class="review-hint">${reviewReasonHint(candidate?.agent_metadata?.review_kind)}</p>
  </section>`;
}

/** The two values a fact review decides between, as rows for a table. */
export function factChangeRows(candidate) {
  const change = candidate?.agent_metadata?.fact_change || {};
  const side = (fact, label) => fact ? {
    label,
    value: formatFactValue(fact.value),
    source_url: fact.source_url || null,
    date_read: fact.date_read ? shortDate(fact.date_read) : "—",
    confidence: fact.confidence || "—",
    set_by: fact.set_by === "ghus_human" ? "GHUS" : "Agent",
  } : null;
  return {
    field: change.field_key || "",
    rows: [side(change.current, "On the map now"), side(change.proposed, "Found by the update")]
      .filter(Boolean),
  };
}

function factChangeBlock(html, candidate) {
  const {field, rows} = factChangeRows(candidate);
  return html`<section class="review-section">
    <h3>${reviewFieldLabel(field) || "Value"}: which one is right?</h3>
    <table><thead><tr><th></th><th>Value</th><th>Source</th><th>Read</th>
      <th>Confidence</th><th>Set by</th></tr></thead>
    <tbody>${rows.map(row => html`<tr key=${row.label}>
      <th scope="row">${row.label}</th><td>${row.value}</td>
      <td>${row.source_url ? html`<a href=${row.source_url} target="_blank" rel="noreferrer">open</a>` : "—"}</td>
      <td>${row.date_read}</td><td>${row.confidence}</td><td>${row.set_by}</td>
    </tr>`)}</tbody></table>
    <p class="review-hint">${reviewReasonHint(candidate?.agent_metadata?.review_kind)}</p>
  </section>`;
}

export function decisionOptions(entityType, candidate = null) {
  const twoWay = twoWayKind(candidate);
  if (twoWay) {
    const [yes, no] = TWO_WAY_ANSWERS[twoWay];
    return [
      {value: "new", label: yes},
      {value: "reject", label: no},
      {value: "defer", label: BUTTONS.park},
    ];
  }
  const noun = {actor: "actor", event: "event", person: "person"}[entityType] || "record";
  return [
    {value: "same_existing", label: `Same as existing ${noun}`},
    {value: "new", label: `New ${noun}`},
    {value: "reject", label: BUTTONS.reject},
    {value: "defer", label: BUTTONS.park},
  ];
}

export function validateReviewDraft(candidate, draft) {
  const errors = {};
  const payload = editableReviewPayload(candidate, draft);
  ["name", ...(candidate?.entity_type === "person" ? ["affiliation", "role"] : [])]
    .forEach(field => {
      if (!String(payload[field] ?? "").trim()) errors[field] = "Required.";
    });
  Object.entries(candidate?.field_constraints || {}).forEach(([field, rules]) => {
    if (rules?.max_length && String(payload[field] ?? "").length > rules.max_length) {
      errors[field] = `Maximum ${rules.max_length} characters.`;
    }
  });
  if (candidate?.entity_type === "actor") {
    const category = String(payload.actor_category ?? "").trim();
    const type = String(payload.category_type ?? "").trim();
    // A type always belongs to exactly one category. An incompatible pair can
    // never be saved, in the browser or on the server.
    if (type && !category) errors.actor_category = "Choose the Actor Category first.";
    if (type && category && !isValidPair(category, type)) {
      errors.category_type = "This type belongs to a different Actor Category.";
    }
    // Not Applicable is a decision, so it carries a reason.
    if (type === NOT_APPLICABLE && !String(payload.category_note ?? "").trim()) {
      errors.category_note = "Required when the type is Not Applicable.";
    }
  }
  return errors;
}

export function canSubmitReview({
  candidate, reviewer, rejectionReason, rejectionOther, decision, decisionKind, targetId,
  busy, admissionConfigured, draftErrors = {},
}) {
  const kind = decisionKind || decision;
  if (!candidate || candidate.status !== "pending_review" || busy || !admissionConfigured
      || !String(reviewer || "").trim() || Object.keys(draftErrors).length) return false;
  // A profile is marked reviewed once its changes are decided.
  if (isUpdateProfile(candidate) && kind === "new" && (candidate.agent_metadata?.changes || []).length) {
    return false;
  }
  if (twoWayKind(candidate)) return ["new", "reject", "defer"].includes(kind);
  if (kind === "same_existing" && !String(targetId || "").trim()) return false;
  if (kind === "reject") {
    return REJECTION_REASONS.includes(rejectionReason)
      && (rejectionReason !== "Other" || Boolean(String(rejectionOther || "").trim()));
  }
  return ["same_existing", "new", "defer"].includes(kind);
}

export function diffFields(candidatePayload, match) {
  const held = match?.payload || match || {};
  const keys = [...new Set([...Object.keys(candidatePayload || {}), ...Object.keys(held)])].sort();
  return keys
    .filter(key => JSON.stringify(candidatePayload?.[key] ?? null) !== JSON.stringify(held[key] ?? null))
    .map(key => ({field: key, candidate: candidatePayload?.[key] ?? null, existing: held[key] ?? null}));
}

/** Every edit the reviewer has made, before and after, for the confirm dialog. */
export function pendingEdits(candidate, draft) {
  const original = candidate?.reviewed_payload || {};
  return (candidate?.editable_fields || [])
    .filter(field => Object.prototype.hasOwnProperty.call(draft || {}, field))
    .map(field => ({field, before: original[field] ?? null, after: draft[field] ?? null}))
    .filter(edit => JSON.stringify(edit.before ?? "") !== JSON.stringify(edit.after ?? ""));
}

const REVIEW_FIELD_LABELS = {
  name: FIELDS.name, actor_category: FIELDS.actorCategory, category_type: FIELDS.categoryType,
  category_note: FIELDS.classificationNote, actor_type: FIELDS.legacyActorType,
  actor_type_raw: "Original Type Evidence", location_city: FIELDS.city, state: FIELDS.state,
  region: FIELDS.region, country: FIELDS.country, website: FIELDS.website,
  description: FIELDS.description, estimated_trl: FIELDS.trl,
  affiliation: "Organization", role: "Title", public_profile_url: "Public Profile",
  research_area: "Relevant Expertise", event_type: "Event Type", next_date: "Date",
  recurring_pattern: "Frequency", sponsoring_orgs: "Organizer",
  thematic_focus: "Sector and Topic", expected_attendance: "Scale Claim",
  access_type: "Access Type", location: "Location",
};

export function reviewFieldLabel(field) {
  return REVIEW_FIELD_LABELS[field]
    || field.replaceAll("_", " ").replace(/\b\w/g, letter => letter.toUpperCase());
}

// Fields the reviewer never edits by hand in the main view: the region is
// derived from the state (D8), and the legacy actor_type lives in Audit only.
export const DERIVED_FIELDS = new Set(["region"]);
export const AUDIT_ONLY_FIELDS = new Set(["actor_type", "actor_type_raw"]);

export function lightPullFacts(candidate) {
  const meta = candidate?.agent_metadata || {};
  if (meta.source_table === "actor_update" && !meta.facts && Array.isArray(meta.written)) {
    // An update result recorded before profiles: what it wrote fills its boxes,
    // each marked with what the update did. Nothing else is inferred.
    return meta.written.map(fact => {
      // A conflict or a change to a GHUS value was not applied: the map kept
      // its value, and this reading is a proposal, never shown as saved.
      const proposal = ["conflict_flagged", "pending_update"].includes(fact.lifecycle_state);
      return {
      fact_key: fact.fact_key, fact_type: "light_pull", layer: 1,
      collection_state: fact.collection_state, value: proposal ? null : fact.value ?? null,
      pending_value: proposal ? fact.value ?? null : null,
      confidence: fact.confidence, source_url: fact.source_url, date_read: fact.date_read
        ? new Date(fact.date_read * 1000).toISOString() : null,
      update: {
        outcome: fact.lifecycle_state === "conflict_flagged" ? "conflict"
          : fact.lifecycle_state === "pending_update" ? "protected"
          : fact.collection_state !== "found" ? "not_found"
          : fact.previous_value != null ? "changed" : "new",
        date: candidate.created_at, previous_value: fact.previous_value ?? null,
      },
    };
    });
  }
  return (meta.facts || [])
    .filter(fact => fact?.fact_type === "light_pull" && Number(fact?.layer) === 1);
}

export function deepPullFacts(candidate) {
  return (candidate?.agent_metadata?.facts || [])
    .filter(fact => fact?.fact_type === "deep_pull" && Number(fact?.layer) === 2);
}

// A fact whose whole meaning is one sentence. Showing the sentence is the point;
// showing {"reason": "..."} around it is noise a reviewer has to read past.
const FACT_PRIMARY_KEYS = [
  "reason", "description", "summary", "text", "value", "name", "statement",
];

// Dates a fact carries about ITSELF - when it was read, when it was recorded -
// are provenance, and a reviewer reads a box for what it says, not when it was
// fetched. They stay on the stored fact and in Audit & Details; they are not
// printed in front of the value.
const FACT_DATE_KEYS = new Set([
  "date", "date_read", "dateRead", "retrieved_at", "recorded_at", "collected_at",
  "as_of", "timestamp", "fetched_at", "observed_at", "updated_at", "created_at",
]);

// Which parts of a value an earlier reading supplied (backend fact_parts).
const CARRIED_OVER = "carried_over";

/** Turn one key of a fact object into "Label: value", or null if it says nothing. */
function factEntry(key, value) {
  if (value === null || value === undefined) return null;
  if (FACT_DATE_KEYS.has(key) || key === CARRIED_OVER) return null;
  if (Array.isArray(value)) {
    const items = value.map(item => (typeof item === "string" ? item : null)).filter(Boolean);
    if (!items.length) return null;
    return `${fieldLabel(key)}: ${items.join(", ")}`;
  }
  if (typeof value === "object") return null;          // nested objects stay out of a one-liner
  const text = String(value).trim();
  if (!text) return null;
  return `${fieldLabel(key)}: ${text}`;
}

/** A fact key as a readable label, reusing the screen's own label rules. */
function fieldLabel(key) {
  return reviewFieldLabel(String(key || ""));
}

/**
 * A recorded fact, readable.
 *
 * Light Pull stores structured values, and dumping them as raw JSON made the
 * boxes unreadable: a reviewer saw `{ "reason": "Found by open-web discovery
 * ..." }` instead of the sentence. So: a single meaningful sentence is shown as
 * itself, a small object becomes "Label: value" lines, and JSON remains only as
 * the last resort for something genuinely structured.
 */
export function formatFactValue(value) {
  if (value === null || value === undefined) return "No value recorded";
  if (typeof value === "string") return value;
  if (typeof value !== "object") return String(value);
  if (Array.isArray(value)) {
    const items = value.map(item => (typeof item === "string" ? item.trim() : "")).filter(Boolean);
    return items.length ? items.join(", ") : "No value recorded";
  }
  for (const key of FACT_PRIMARY_KEYS) {
    const primary = value[key];
    if (typeof primary === "string" && primary.trim()) return primary.trim();
  }
  const entries = Object.entries(value);
  const lines = entries.map(([key, item]) => factEntry(key, item)).filter(Boolean);
  if (lines.length) return lines.join("\n");
  // Everything there was to say was a date. Dumping the JSON would put the
  // timestamp back on screen by the back door.
  if (entries.length && entries.every(([key]) => FACT_DATE_KEYS.has(key))) {
    return "No value recorded";
  }
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}

function hostOf(url) {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return ""; }
}

function otherHost(source, website) {
  const host = hostOf(source);
  return host && hostOf(website) && host !== hostOf(website) ? host : null;
}

function present(value) {
  return value === null || value === undefined || String(value).trim() === ""
    ? null : String(value).trim();
}

/**
 * The Light Pull rows for this record's category (Appendix D), resolved against
 * the recorded facts.
 *
 * A row with no fact says which kind of missing it is. "Not Found" means the
 * layer ran and found nothing; "Not Yet Collected" means it has not run. The two
 * are never merged, because merging them turns "we have not looked" into
 * "there is nothing there".
 */
export function lightFactRows(candidate) {
  const category = String(candidate?.reviewed_payload?.actor_category || "");
  const facts = new Map();
  for (const fact of lightPullFacts(candidate)) {
    if (fact?.fact_key) facts.set(String(fact.fact_key), fact);
  }
  // An actor's boxes are its recorded facts: a box with no fact was never
  // read (a read that found nothing records Not Found), so it is Not Yet
  // Collected - not Not Found because some other box was read.
  const recordFacts = candidate?.agent_metadata?.source_table === "actor_update";
  // A Data Feed record's boxes are what GHUS supplied: until a Light Pull
  // reads its pages, an empty box was never looked for.
  const supplied = Boolean(candidate?.agent_metadata?.data_feed)
    && !candidate?.agent_metadata?.light_pull_read?.read_at;
  const layerRan = facts.size > 0 && !recordFacts && !supplied;
  const pendingByField = new Map((candidate?.agent_metadata?.changes || [])
    .filter(change => change.kind === "fact" && change.field_key)
    .map(change => [String(change.field_key), change]));
  const specific = CATEGORY_LIGHT_ROWS[category] || [];
  return [...COMMON_LIGHT_ROWS, ...specific]
    // D14: TRL is a Startup row only, rankings a University row only. Neither
    // is ever shown — let alone inferred — for any other category.
    .filter(([key]) => key !== "published_stage_or_trl" || showsTrl(category))
    .filter(([key]) => key !== "rankings" || showsRankings(category))
    .map(([key, label]) => {
      const fact = facts.get(key);
      if (!fact) {
        const state = layerRan ? MISSING.notFound : MISSING.notYetChecked;
        // The source, date, confidence and origin columns carry the SAME kind
        // of missing as the row. Saying "Not Found" for a source the layer
        // never went looking for would claim a search that did not happen.
        return {
          key, label, value: null, state, metaState: state,
          source: null, dateRead: null, confidence: null, origin: null,
          update: null, pending: pendingByField.get(key) || null, recordValue: null,
        };
      }
      // The ledger's own vocabulary, from the actor_fact CHECK constraint:
      // 'found', 'not_found', 'not_yet_collected'. A state other than 'found'
      // carries a NULL value by that same constraint, so the row must report
      // which kind of missing it is rather than printing an empty value.
      const missing = String(fact.collection_state || "").toLocaleLowerCase();
      const state = missing === "not_found" ? MISSING.notFound
        : ["not_yet_collected", "not_checked", "not_yet_checked"].includes(missing)
          ? MISSING.notYetChecked
        : null;
      return {
        key, label,
        value: state ? null : fact.value ?? null,
        state,
        // A fact that exists was read from somewhere, so an absent column here
        // genuinely means the layer looked and found nothing to record.
        metaState: state === MISSING.notYetChecked ? MISSING.notYetChecked : MISSING.notFound,
        source: present(fact.source_url),
        // A source that is not its own website (its parent's site, a government
        // or another credible site, read when its own refused): named.
        sourceHost: otherHost(fact.source_url, candidate?.reviewed_payload?.website),
        dateRead: present(fact.date_read),
        confidence: confidenceLabel(present(fact.confidence)),
        origin: present(fact.source_origin),
        // The organisation's own pages the Light Pull read for this box. A
        // "Not Found" with pages listed means those pages were read and none
        // of them states it - never that nobody looked.
        pagesRead: Array.isArray(fact.pages_read) ? fact.pages_read.filter(Boolean) : [],
        // What the latest actor update found for this box, and a change to it
        // still waiting for a decision (shown as proposed, never as saved).
        update: fact.update || null,
        pending: pendingByField.get(key)
          || (fact.pending_value != null ? {proposed: {value: fact.pending_value}} : null),
        kept: fact.pending_value != null,
        recordValue: fact.record_value ?? null,
        fromSector: present(fact.from_sector),
        // From the earlier GHUS profile: a value no read has replaced, or the
        // record beside a box its own pages did not state.
        fromRecord: present(fact.from_record),
        carriedOver: Array.isArray(fact.value?.[CARRIED_OVER]) ? fact.value[CARRIED_OVER] : [],
      };
    });
}

/** The missing state, said plainly ("Not Found"); the pages checked are listed under it. */
export function missingWithPages(row) {
  return row?.state || null;
}

// Common Light Pull keys that are already shown as an editable control in the
// Identity, Location or Sector boxes. Repeating them as a read-only box would
// say the same thing twice, with one copy stale.
const LIGHT_ROWS_SHOWN_AS_CONTROLS = new Set([
  "official_identity", "actor_category_type", "website", "description",
  "location", "parent_connection", "sector_topic", "hub_assignment",
]);

/**
 * The Light Pull information boxes for a record, in two groups.
 *
 * `common` are the Section 5.1 fields every actor has; `specific` are the
 * Section 5.2 fields for this actor's category. Changing the category changes
 * only the second group, and nothing the reviewer has typed is touched.
 */
export function lightPullBoxes(candidate, category) {
  const resolved = String(
    category ?? candidate?.reviewed_payload?.actor_category ?? "",
  );
  const rows = lightFactRows({
    ...candidate,
    reviewed_payload: {...(candidate?.reviewed_payload || {}), actor_category: resolved},
  });
  const specificKeys = new Set((CATEGORY_LIGHT_ROWS[resolved] || []).map(([key]) => key));
  return {
    common: rows.filter(row => !specificKeys.has(row.key)
      && !LIGHT_ROWS_SHOWN_AS_CONTROLS.has(row.key)),
    specific: rows.filter(row => specificKeys.has(row.key)),
  };
}

export function factHistoryRows(candidate) {
  return (candidate?.agent_metadata?.fact_history || [])
    .filter(fact => fact && fact.fact_key)
    .map(fact => ({
      key: String(fact.fact_key),
      label: factRowLabel(candidate, String(fact.fact_key)),
      value: fact.value ?? null,
      confidence: confidenceLabel(present(fact.confidence)),
      dateRead: present(fact.date_read),
      isCurrent: Boolean(fact.is_current),
      lifecycle: present(fact.lifecycle_state),
    }));
}

function factRowLabel(candidate, key) {
  const category = String(candidate?.reviewed_payload?.actor_category || "");
  const found = [...COMMON_LIGHT_ROWS, ...(CATEGORY_LIGHT_ROWS[category] || [])]
    .find(([rowKey]) => rowKey === key);
  return found ? found[1] : reviewFieldLabel(key);
}

/**
 * Parent organization (decisions D10 and D11).
 *
 * Only Unit of and Operated by are parenthood. Having no parent is a complete,
 * normal state, so an absent parent reads "Not Available" with an explanation —
 * never as a warning or a gap to fill.
 */
export function parentDisplay(candidate) {
  const edges = candidate?.agent_metadata?.relationships || [];
  const parent = edges.find(edge =>
    edge?.direction === "outgoing" && isParentLink(edge.relationship_type));
  if (!parent) {
    return {hasParent: false, missing: MISSING.notAvailable, tooltip: NO_PARENT_TOOLTIP};
  }
  return {
    hasParent: true,
    name: present(parent.counterpart_name) || present(parent.counterpart_id) || MISSING.notProvided,
    linkType: linkTypeLabel(parent.relationship_type),
    source: present(parent.source_url),
  };
}

/** Everything that is not parenthood, read-only in this release (D11). */
export function otherRelationships(candidate) {
  return (candidate?.agent_metadata?.relationships || [])
    .filter(edge => edge && !isParentLink(edge.relationship_type))
    .map(edge => ({
      label: linkTypeLabel(edge.relationship_type),
      direction: edge.direction === "outgoing" ? "to" : "from",
      counterpart: present(edge.counterpart_name) || present(edge.counterpart_id) || MISSING.notProvided,
      counterpartType: present(edge.counterpart_type),
      source: present(edge.source_url),
    }));
}

/**
 * The header's classification and location, with the right missingness for each
 * absent value.
 *
 * The region is always derived from the state (D8). A missing location is "Not
 * Provided" and never "Not Applicable", because an absent city is unknown, not
 * deliberately inapplicable (D9). A legacy NULL type is "Pending
 * Classification" and is never treated as Not Applicable (D4).
 */
export function actorReviewSummary(payload = {}, originalPayload = payload) {
  const category = present(payload.actor_category);
  const type = present(payload.category_type);
  const legacyType = present(originalPayload?.actor_type);
  return {
    actor_category: category,
    actor_category_label: category ? categoryLabel(category) || category : null,
    category_type: type,
    category_type_label: type ? typeLabel(category, type) || type : MISSING.pending,
    category_type_retired: type === RETIRED_CATCH_ALL,
    category_note: present(payload.category_note),
    city: present(payload.location_city) || present(payload.city) || MISSING.notProvided,
    state: present(payload.state) || MISSING.notProvided,
    region: regionForState(payload.state, payload.country),
    country: present(payload.country) || MISSING.notProvided,
    pending_classification: !type,
    legacy_actor_type: legacyType,
  };
}

/** Header badges: record kind, review state and every review reason. */
export function headerBadges(candidate) {
  if (!candidate) return [];
  const badges = [{tone: "kind", label: RECORD_KIND_LABELS[candidate.entity_type] || candidate.entity_type}];
  const recordStatus = RECORD_STATUS_LABELS[String(candidate.record_status || "").toLocaleLowerCase()];
  badges.push({tone: candidate.status, label: recordStatus || reviewStatusLabel(candidate.status)});
  if (candidate.review_reason) {
    badges.push({tone: "reason", label: reviewReasonLabel(candidate.review_reason),
      hint: reviewReasonHint(candidate.review_reason)});
  }
  if (candidate.duplicate_state === "possible_duplicate") {
    badges.push({tone: "duplicate", label: BADGES.possibleDuplicate});
  }
  return badges;
}

/**
 * The 965 migrated actors (decision D7). They are Verified, through an honest
 * bootstrap event, with no reviewer and no review date — because none exist.
 * The screen says so rather than inventing either.
 */
export function isMigratedBaseline(candidate) {
  const run = `${candidate?.source_run_id || ""} ${candidate?.source_description || ""}`;
  return /existing_canonical_migration/i.test(run) || candidate?.run_trigger === "migration";
}

/**
 * The options the hub dropdown offers, in the order a reviewer wants them:
 * what the actor already belongs to, then what the rule suggests, then the rest
 * of the live hubs. Each is labelled with which it is, so choosing a suggestion
 * is a deliberate act rather than an accident of ordering.
 *
 * This only ever lists hubs that already exist. A new hub is never created from
 * here; detection proposes one and GHUS decides.
 */
export function hubDropdownOptions(candidate) {
  const metadata = candidate?.agent_metadata || {};
  const seen = new Set();
  const options = [];
  const add = (hub, suffix) => {
    const id = String(hub?.hub_id || "");
    if (!id || seen.has(id)) return;
    seen.add(id);
    const miles = hub.distance_miles != null ? ` · ${hub.distance_miles} mi` : "";
    options.push({hub_id: id, label: `${hub.name || id}${miles}${suffix}`});
  };
  for (const hub of metadata.hub_memberships || []) add(hub, ` · ${BADGES.currentlyAssigned}`);
  for (const hub of metadata.hub_suggestions || []) add(hub, ` · ${BADGES.suggested}`);
  for (const hub of metadata.hubs || []) add(hub, "");
  return options;
}

function decisionKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `review-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function errorMessage(body, status) {
  const detail = body?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map(item => item.msg).join(" ");
  if (detail?.message) return detail.message;
  return `The request failed (${status}).`;
}

const NEW_SECTOR = "__new_sector__";

async function request(url, options = {}) {
  const response = await fetch(url, options);
  let body = {};
  try { body = await response.json(); } catch {}
  if (!response.ok) throw new Error(errorMessage(body, response.status));
  return body;
}

/**
 * One Light Pull information box.
 *
 * A box is always rendered, even with nothing in it, because the absence of a
 * field is itself the answer and hiding it would make the record look complete.
 * Which KIND of absence it is -- Not Found, Not Yet Collected, Not Applicable --
 * is shown as stated, never substituted.
 */
function pageLabel(url) {
  try {
    const path = new URL(url).pathname.replace(/\/+$/, "");
    return path ? path.split("/").pop().replace(/[-_]+/g, " ") : "Home";
  } catch {
    return "Page";
  }
}

function lightBox(html, row) {
  // The date a page was read is provenance, not something a reviewer reads a
  // box for, and a full ISO timestamp in every box crowded out the value. The
  // source link and the confidence stay; the timestamp is still recorded on the
  // fact and still shown in Audit & Details.
  const provenance = [row.source, row.confidence].some(Boolean);
  return html`<div class="review-box light-box" key=${row.key}>
    <dt>${row.label}</dt>
    <dd>${row.state
      ? html`<span class="review-missing">${missingWithPages(row)}</span>`
      : row.kept ? html`<span class="review-missing">The value on the map was kept (see Fact History)</span>`
      : formatFactValue(row.value)}</dd>
    ${row.state && row.pagesRead?.length > 0 && html`<small>Checked:
      ${row.pagesRead.map((url, index) => html`${index ? " · " : " "}<a href=${url}
        target="_blank" rel="noreferrer">${pageLabel(url)}</a>`)}
    </small>`}
    ${provenance && html`<small>
      ${row.source
        ? html`<a href=${row.source} target="_blank" rel="noreferrer">${row.sourceHost
          ? `Source: ${row.sourceHost}` : "Source"}</a>`
        : ""}
      ${row.confidence ? (row.source ? ` · ${row.confidence}` : row.confidence) : ""}
    </small>`}
    ${row.fromSector && html`<small>From its ${row.fromSector} facts.</small>`}
    ${row.fromRecord && html`<small>From the ${row.fromRecord} (not re-read from its pages).</small>`}
    ${row.recordValue != null && html`<div class="review-record-value">
      <span>On the earlier GHUS profile</span><p>${formatFactValue(row.recordValue)}</p></div>`}
    ${row.carriedOver?.length > 0 && html`<small>Kept from an earlier reading:
      ${row.carriedOver.map(fieldLabel).join(", ")}.</small>`}
    ${row.update && !row.pending && html`<div class=${"review-update-note " + row.update.outcome}>
      <span>This update</span>${updateNote(row.update, row.value)}</div>`}
    ${row.pending && html`<div class="review-proposed">
      <span>Proposed — Not Yet Approved</span>
      <p>${formatFactValue(row.pending.proposed?.value)}</p>
      <small>Decide under Changes to Review.</small>
    </div>`}
  </div>`;
}

function formatSync(lastSync) {
  const row = (lastSync || []).find(item => item.source === "postgresql");
  return row?.last_success_at
    ? usDateTime(row.last_success_at)
    : "Not yet synchronized";
}

function formatDate(seconds) {
  return seconds ? usDate(seconds) : SENTENCES.noRunRecorded;
}

/**
 * A calendar date, in the reader's locale.
 *
 * Distinct from formatDate, which takes epoch seconds. A subscription's period
 * is a date with no time of day, and parsing "2026-08-30" through the Date
 * constructor would read it as UTC midnight and can show the previous day west
 * of Greenwich. Splitting the parts avoids inventing a time that was never
 * recorded.
 */
function formatDay(value) {
  return usDate(String(value || ""));
}

/** Where a proposed hub sits, in words. */
export function hubProposalPlace(proposal = {}) {
  const place = [proposal.primary_city, proposal.state, proposal.country]
    .map(value => String(value || "").trim()).filter(Boolean).join(", ");
  const key = proposal.dimension_key
    ? `${proposal.dimension || "sector"} ${proposal.dimension_key}` : "";
  return [place || MISSING.notProvided, key].filter(Boolean).join(" · ");
}

/**
 * A threshold as "12 of 10 required", so a reader sees the margin.
 *
 * The count alone does not say whether it passed, and the requirement alone
 * does not say by how much.
 */
export function thresholdLabel(count, required) {
  if (count === null || count === undefined) return MISSING.notYetChecked;
  if (required === null || required === undefined) return String(count);
  return `${count} of ${required} required`;
}

/**
 * The recorded explanation of why this record was found.
 *
 * Discovery stores it as a Light Pull fact; only some paths also put it on
 * agent_metadata. Nothing here reconstructs an explanation - if neither holds
 * one, the box says Not Yet Collected rather than inventing search intent.
 */
export function whyMatchedFact(candidate) {
  const fact = (candidate?.agent_metadata?.facts || [])
    .find(item => item?.fact_key === "why_matched" && item?.collection_state === "found");
  const value = fact?.value;
  if (!value || typeof value !== "object") return null;
  return {
    reason: value.reason || null,
    strength: value.strength ?? fact.confidence ?? null,
    date_read: value.date_read || fact.date_read || null,
    source_url: value.source_url || fact.source_url || null,
  };
}

const LONG_FIELDS = /description|activities|approach|summary|constraints|focus|research|category_note|thematic/;

function textField(html, candidate, field, value, onChange, disabled, error) {
  const long = LONG_FIELDS.test(field);
  const type = field === "estimated_trl" ? "number" : /url|website|profile/.test(field) ? "url" : "text";
  const limit = candidate?.field_constraints?.[field]?.max_length;
  return html`<label class=${"review-field " + (error ? "invalid" : "")}>
    <span>${reviewFieldLabel(field)}</span>
    ${long
      ? html`<textarea rows="3" value=${value ?? ""} maxlength=${limit} disabled=${disabled}
          onInput=${event => onChange(field, event.target.value)}></textarea>`
      : html`<input type=${type} min=${type === "number" ? 1 : undefined}
          max=${type === "number" ? 9 : undefined} maxlength=${limit} value=${value ?? ""}
          disabled=${disabled} onInput=${event => onChange(field, event.target.value)}/>`}
    ${error && html`<small class="field-error">${error}</small>`}
  </label>`;
}

export function createReviewPage({html, useEffect, useRef, useState}) {
  return function Review() {
    const [filters, setFilters] = useState({
      status: "pending_review", run_type: "all", entity_type: "all",
      actor_category: "all", search: "",
    });
    // The named run open in the centre panel, and where the list was scrolled.
    const [runKey, setRunKey] = useState(null);
    const listScroll = useRef(0);
    const [data, setData] = useState({
      candidates: [], counts: {}, source_maps: [], run_groups: [], sync_warnings: [],
      last_sync: [], admission_configured: false,
    });
    const [selectedId, setSelectedId] = useState(null);
    const [selected, setSelected] = useState(null);
    const [draft, setDraft] = useState({});
    const [reviewer, setReviewer] = useState("");
    const [notes, setNotes] = useState("");
    const [decisionKind, setDecisionKind] = useState("same_existing");
    const [targetId, setTargetId] = useState("");
    const [rejectionReason, setRejectionReason] = useState("");
    const [rejectionOther, setRejectionOther] = useState("");
    const [hubIds, setHubIds] = useState([]);
    const [proposeHub, setProposeHub] = useState(false);
    const [proposedHub, setProposedHub] = useState({name: "", rationale: ""});
    const [factView, setFactView] = useState("current");
    const [view, setView] = useState("queue");
    const [hubDemo, setHubDemo] = useState({proposals: [], configured: false, loaded: false});
    // Sectors come from the database, so one added here appears at once.
    const [sectorState, setSectorState] = useState({canCreate: false, version: 0});
    const [newSector, setNewSector] = useState(null);
    const [busy, setBusy] = useState(false);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [feedback, setFeedback] = useState("");
    // The Deep Pull offered after a verification: its plan (free), then its run.
    const [deep, setDeep] = useState(null);
    const keys = useRef(new Map());

    const loaded = useRef(null);
    async function load(signal, force = false) {
      setLoading(true);
      setError("");
      const params = new URLSearchParams();
      Object.entries(filters).forEach(([key, value]) => {
        // The run type narrows the runs panel; it is not a server filter.
        if (key !== "run_type" && value && value !== "all") params.set(key, value);
      });
      if (force) params.set("refresh", "true");
      try {
        const body = await request(`/api/review/candidates?${params}`, {signal});
        setData(body);
        loaded.current = body;
        // A record stays open after a decision; nothing opens by itself.
        setSelectedId(current =>
          body.candidates.some(item => item.candidate_id === current) ? current : null);
      } catch (exception) {
        if (exception.name !== "AbortError") setError(exception.message);
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    }

    useEffect(() => {
      const controller = new AbortController();
      load(controller.signal);
      return () => controller.abort();
    }, [filters.status, filters.entity_type, filters.actor_category, filters.search]);

    // Discovery -> Run now: show that actor's update profile, freshly read from the map.
    useEffect(() => {
      async function onOpen(event) {
        // Discovery / Dashboard -> Show Results: that run, every record shown.
        const wanted = event.detail?.run_key;
        if (wanted) {
          setView("queue");
          setFilters(current => ({...current, run_type: event.detail.run_type || "all",
            status: "all"}));
          setSelectedId(null);
          loaded.current = null;
          await load(undefined, true);
          setRunKey(wanted);
          return;
        }
        const actorId = event.detail?.actor_id;
        setView("queue");
        setFilters(current => ({...current, run_type: "actor_updates"}));
        setSelectedId(null);
        setRunKey(null);
        loaded.current = null;
        await load(undefined, true);
        const profile = (loaded.current?.candidates || []).find(item => isUpdateProfile(item)
          && item.agent_metadata?.entity_id === actorId);
        if (profile) { setRunKey(profile.run_group_key); openRecord(profile.candidate_id); }
      }
      window.addEventListener(OPEN_IN_REVIEW, onOpen);
      return () => window.removeEventListener(OPEN_IN_REVIEW, onOpen);
    }, []);

    useEffect(() => {
      if (!selectedId) { setSelected(null); setDraft({}); return; }
      let active = true;
      request(`/api/review/candidates/${selectedId}`).then(candidate => {
        if (!active) return;
        setSelected(candidate);
        setDraft({...candidate.reviewed_payload});
        // Two values for one box: keeping the map's value is the safe default.
        // Keeping the map as it is is the safe default; a proposal waits.
        setDecisionKind(isFactReview(candidate) ? "reject"
          : twoWayKind(candidate) === "update" ? "new" : twoWayKind(candidate) ? "defer"
          : candidate.duplicate_state === "already_exists" ? "same_existing" : "new");
        setTargetId("");
        setRejectionReason("");
        setRejectionOther("");
        setHubIds([]);
        setProposeHub(false);
        setFactView("current");
      }).catch(exception => { if (active) setError(exception.message); });
      return () => { active = false; };
    }, [selectedId]);


    useEffect(() => {
      if (view !== "hubs" || hubDemo.loaded) return;
      let active = true;
      request("/api/review/hub-proposals")
        .then(body => { if (active) setHubDemo({...body, loaded: true}); })
        .catch(exception => { if (active) setError(exception.message); });
      return () => { active = false; };
    }, [view, hubDemo.loaded]);

    async function loadSectors() {
      try {
        const body = await request("/api/review/sectors");
        setSectors(body.sectors || []);
        setSectorState(current => ({canCreate: !!body.can_create, version: current.version + 1}));
      } catch (exception) { setError(exception.message); }
    }
    useEffect(() => { loadSectors(); }, []);

    function startNewSector(suggestion) {
      setNewSector({name: suggestion || "", description: "", busy: false, error: ""});
    }

    async function createSector() {
      if (!newSector) return;
      if (!reviewer.trim()) {
        setNewSector({...newSector, error: SENTENCES.sectorNeedsReviewer});
        return;
      }
      setNewSector({...newSector, busy: true, error: ""});
      try {
        const created = await request("/api/review/sectors", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({name: newSector.name.trim(),
                                description: newSector.description.trim() || null,
                                reviewer: reviewer.trim()}),
        });
        await loadSectors();
        edit("primary_sector", created.code);
        setNewSector(null);
        setFeedback(created.created ? SENTENCES.sectorCreated(created.name)
                                    : SENTENCES.sectorExisted(created.name));
      } catch (exception) {
        setNewSector(current => current && {...current, busy: false, error: exception.message});
      }
    }

    function setFilter(key, value) {
      setFilters(current => ({...current, [key]: value}));
      if (key === "run_type") { setSelectedId(null); setRunKey(null); }
    }

    function openRecord(candidateId) {
      const list = document.querySelector(".review-main");
      listScroll.current = list ? window.scrollY : 0;
      setSelectedId(candidateId);
      window.scrollTo({top: 0});
    }

    function backToRecords() {
      setSelectedId(null);
      // Restore where the list was, once it has rendered again.
      requestAnimationFrame(() => window.scrollTo({top: listScroll.current}));
    }

    function edit(field, value) {
      setDraft(current => ({...current, [field]: value}));
    }

    /**
     * Changing the Actor Category clears an incompatible Category Type, and
     * asks first. A type belongs to exactly one category, so carrying it over
     * would record something untrue.
     */
    function editCategory(value) {
      const currentType = String(draft.category_type ?? "").trim();
      if (currentType && !isValidPair(value, currentType)) {
        if (!window.confirm(SENTENCES.categoryChangeWarning)) return;
        setDraft(current => ({...current, actor_category: value, category_type: ""}));
        return;
      }
      setDraft(current => ({...current, actor_category: value}));
    }

    /** The state drives the region, so they move together and stay consistent. */
    function editState(value) {
      setDraft(current => ({
        ...current, state: value, region: regionForState(value, current.country),
      }));
    }

    /** Country moves the region too: a non-US record has no US region. */
    function editCountry(value) {
      setDraft(current => ({
        ...current, country: value, region: regionForState(current.state, value),
      }));
    }

    async function save() {
      if (!selected || busy) return;
      setBusy(true); setError(""); setFeedback("");
      try {
        const saved = await request(`/api/review/candidates/${selected.candidate_id}`, {
          method: "PATCH",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({fields: editableReviewPayload(selected, draft)}),
        });
        setSelected(saved);
        setDraft({...saved.reviewed_payload});
        setFeedback("Edits saved as a new reviewer-sourced fact. The previous value is kept in History.");
      } catch (exception) {
        setError(exception.message);
      } finally {
        setBusy(false);
      }
    }

    function confirmText(kind) {
      const edits = pendingEdits(selected, draft);
      const lines = [`${selected.display_name} — ${decisionOptions(selected.entity_type, selected)
        .find(option => option.value === kind)?.label}`];
      if (edits.length) {
        lines.push("", "Pending edits:");
        for (const item of edits) {
          lines.push(`  ${reviewFieldLabel(item.field)}: ${item.before ?? "—"} → ${item.after ?? "—"}`);
        }
      }
      if (isFactReview(selected)) {
        if (kind !== "defer") lines.push("", "Both values stay in the history; nothing is deleted.");
      } else if (twoWayKind(selected) === "update") {
        if (kind !== "defer") lines.push("", "Recorded in Review only; the map is not changed.");
      } else if (twoWayKind(selected)) {
        if (kind !== "defer") lines.push("", twoWaySummary(selected).question);
      } else if (kind === "new" || kind === "same_existing") {
        lines.push("", SENTENCES.verifyConsequences);
      }
      if (kind === "reject" && !twoWayKind(selected)) {
        lines.push("", `${FIELDS.rejectionReason}: ${rejectionReason}`
          + (rejectionReason === "Other" ? ` — ${rejectionOther}` : ""), SENTENCES.noDeletion);
      }
      if (kind === "defer") lines.push("", `${FIELDS.notes}: ${notes || "—"}`);
      return lines.join("\n");
    }

    async function decide() {
      const draftErrors = validateReviewDraft(selected, draft);
      if (!canSubmitReview({
        candidate: selected, reviewer, rejectionReason, rejectionOther, decisionKind, targetId,
        busy, admissionConfigured: data.admission_configured, draftErrors,
      })) return;
      if (!window.confirm(confirmText(decisionKind))) return;
      const mapKey = `${selected.candidate_id}:${decisionKind}`;
      if (!keys.current.has(mapKey)) keys.current.set(mapKey, decisionKey());
      setBusy(true); setError(""); setFeedback("");
      try {
        const body = {
          decision_kind: decisionKind,
          reviewer: reviewer.trim(),
          idempotency_key: keys.current.get(mapKey),
          confirmed: true,
          notes: notes.trim() || null,
          edited_payload: editableReviewPayload(selected, draft),
          target_id: targetId.trim() || null,
          hub_ids: hubIds,
          proposed_hub: proposeHub && proposedHub.name.trim()
            ? {name: proposedHub.name.trim(), rationale: proposedHub.rationale.trim() || null}
            : null,
          rejection_reason: decisionKind === "reject" ? rejectionReason : null,
          rejection_reason_other: decisionKind === "reject" && rejectionReason === "Other"
            ? rejectionOther.trim() : null,
        };
        const updated = await request(
          `/api/review/candidates/${selected.candidate_id}/decision`,
          {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)},
        );
        setSelected(updated);
        setFeedback("Decision recorded. It is kept in history permanently.");
        keys.current.delete(mapKey);
        await load(undefined, true);
      } catch (exception) {
        setError(exception.message);
      } finally {
        setBusy(false);
      }
    }

    const deepTarget = deepPullTarget(selected);
    // Free: asks the backend what a Deep Pull would read and cost. Nothing runs.
    useEffect(() => {
      if (!deepTarget) { setDeep(null); return undefined; }
      let live = true;
      setDeep({key: deepTarget.key, state: "planning"});
      request(`/api/discovery/actors/${deepTarget.actor_id}/plan`, {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({scope: "general", depth: "deep", topic: deepTarget.topic}),
      }).then(plan => { if (live) setDeep({key: deepTarget.key, state: "ready", plan}); })
        .catch(err => { if (live) setDeep({key: deepTarget.key, state: "error", error: err.message}); });
      return () => { live = false; };
    }, [deepTarget?.key]);

    async function runDeepPull() {
      const plan = deep?.plan;
      if (!deepTarget || !plan?.can_check || deep.state === "running") return;
      const items = plan.fields.map(fieldLabel).join(", ");
      if (!window.confirm([`Run Deep Pull for ${deepTarget.name} in ${plan.topic?.name || deepTarget.topic}?`,
        "", `It reads up to three of its own pages for ${plan.fields.length} selected items: ${items}.`,
        deepCostLine(plan.cost), "",
        "What the pages state is written to the map with its source. Values set by GHUS and "
          + "conflicting readings are not written over; they wait in Review."].join("\n"))) return;
      setDeep({...deep, state: "running"});
      try {
        const body = JSON.stringify({scope: "general", depth: "deep", topic: deepTarget.topic});
        const checked = await request(`/api/discovery/actors/${deepTarget.actor_id}/check`, {
          method: "POST", headers: {"Content-Type": "application/json"}, body});
        if (checked.ok === false) throw new Error(checked.error || "The Deep Pull could not read its pages.");
        const applied = checked.check_id && checked.writes
          ? await request(`/api/discovery/actor-checks/${checked.check_id}/apply`, {method: "POST"})
          : null;
        if (applied && applied.ok === false && !(applied.results || []).length) {
          throw new Error(applied.error || "The Deep Pull was not written.");
        }
        setDeep(d => ({...d, state: "done", line: deepResultLine(checked, applied)}));
      } catch (exception) {
        setDeep(d => ({...d, state: "failed", error: exception.message}));
      }
    }

    async function decideChange(row, choice) {
      if (!selected || busy || !reviewer.trim()) return;
      const text = [`${selected.display_name} — ${row.label}: ${choice.label}`, "", choice.consequence,
        "", "Nothing is deleted; every value stays in the history."].join("\n");
      if (!window.confirm(text)) return;
      const mapKey = `${selected.candidate_id}:${row.id}:${choice.value}`;
      if (!keys.current.has(mapKey)) keys.current.set(mapKey, decisionKey());
      setBusy(true); setError(""); setFeedback("");
      try {
        const updated = await request(
          `/api/review/candidates/${selected.candidate_id}/changes/${row.id}`,
          {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({
            choice: choice.value, reviewer: reviewer.trim(), confirmed: true,
            idempotency_key: keys.current.get(mapKey), notes: notes.trim() || null,
          })},
        );
        setSelected(updated);
        keys.current.delete(mapKey);
        setFeedback(`${row.label}: ${choice.done}`);
        await load(undefined, true);
      } catch (exception) {
        setError(exception.message);
      } finally {
        setBusy(false);
      }
    }

    const counts = data.counts || {};
    const pending = selected?.status === "pending_review";
    const draftErrors = selected ? validateReviewDraft(selected, draft) : {};
    const matches = selected?.top_matches || [];
    const hubs = selected?.agent_metadata?.hubs || [];
    // Three different things, kept apart: what the actor already belongs to,
    // what the deterministic rule would propose, and every hub a reviewer could
    // choose by hand. A suggestion is never shown as a membership.
    const memberships = selected?.agent_metadata?.hub_memberships || [];
    const suggestions = selected?.agent_metadata?.hub_suggestions || [];
    const hubOptions = selected ? hubDropdownOptions(selected) : [];
    const runs = runsForType(data.run_groups, data.candidates, filters.run_type);
    // The open run: the one chosen, or the newest of this type.
    const activeRun = runs.find(run => run.key === runKey) || runs[0] || null;
    const records = recordsOfRun(data.candidates, activeRun?.key);
    const isActor = selected?.entity_type === "actor";
    // Light Pull populates the information boxes. The category-specific group
    // follows the category currently chosen in the dropdown, so it updates as
    // soon as the reviewer changes it -- without touching anything they typed.
    const lightBoxes = selected && isActor
      ? lightPullBoxes(selected, draft.actor_category)
      : {common: [], specific: []};
    const summary = isActor
      ? actorReviewSummary(draft, selected?.original_payload || selected?.reviewed_payload)
      : null;
    const parent = isActor ? parentDisplay(selected) : null;
    const relationships = isActor ? otherRelationships(selected) : [];
    const factRows = isActor ? lightFactRows(selected) : [];
    const historyRows = isActor ? factHistoryRows(selected) : [];
    const deepFacts = deepPullFacts(selected);
    const writerDown = !data.admission_configured;
    const editableHere = (selected?.editable_fields || []).filter(field =>
      !DERIVED_FIELDS.has(field) && !AUDIT_ONLY_FIELDS.has(field)
      && !["actor_category", "category_type", "category_note", "name", "website", "description",
           "location_city", "state", "country"].includes(field));

    return html`<section class="review-page" aria-labelledby="review-title">
      <div class="eyebrow">${SENTENCES.pageEyebrow}</div>
      <h1 class="hero-h" id="review-title">${SENTENCES.pageTitle}</h1>

      <div class="review-counts" aria-label="Review queue counts">
        ${["pending_review", "approved", "rejected_by_reviewer"].map(status => html`
          <button key=${status} class=${"review-count " + (filters.status === status ? "active" : "")}
            onClick=${() => setFilter("status", status)}>
            <strong>${counts[status] || 0}</strong><span>${reviewStatusLabel(status)}</span>
          </button>`)}
      </div>
      <div class="review-sync">
        <span>Last PostgreSQL sync: ${formatSync(data.last_sync)}</span>
        <button class="btn ghost" disabled=${loading} onClick=${() => load(undefined, true)}>
          ${BUTTONS.refresh}
        </button>
      </div>
      ${writerDown && html`<div class="review-notice" role="alert">
        <strong>${SENTENCES.failClosed}</strong> ${SENTENCES.writerUnavailable}
      </div>`}
      ${(data.sync_warnings || []).map((warning, index) => html`
        <div key=${index} class="review-message error" role="alert">
          <strong>Source sync warning:</strong> ${warning}
        </div>`)}
      <div class="review-tabs" role="tablist" aria-label="Review views">
        <button role="tab" aria-selected=${view === "queue"}
          class=${"btn ghost " + (view === "queue" ? "active" : "")}
          onClick=${() => setView("queue")}>${QUEUE.title}</button>
        <button role="tab" aria-selected=${view === "hubs"}
          class=${"btn ghost " + (view === "hubs" ? "active" : "")}
          onClick=${() => setView("hubs")}>${SECTIONS.hubProposals}</button>
      </div>

      ${view === "hubs" && html`<section class="review-updates" aria-label=${SECTIONS.hubProposals}>
        ${!hubDemo.loaded && html`<p class="muted">${SENTENCES.queueLoading}</p>`}
        ${hubDemo.loaded && !hubDemo.configured && html`
          <p class="muted">${SENTENCES.hubProposalsUnavailable}</p>`}
        ${hubDemo.loaded && hubDemo.configured && !hubDemo.proposals.length && html`
          <p class="muted">${SENTENCES.hubProposalsNone}</p>`}
        ${hubDemo.proposals.map(proposal => html`
          <div class="review-match" key=${proposal.proposed_hub_id}>
            <div class="review-detail-head">
              <div><strong>${proposal.name}</strong>
                <p class="review-subhead">${hubProposalPlace(proposal)}</p></div>
              <span class=${"review-status " + (proposal.created_hub ? "verified" : "parked")}>
                ${proposal.created_hub ? BADGES.verified : BADGES.parked}</span>
            </div>
            <p>${proposal.rationale}</p>
            <dl class="review-facts">
              <div><dt>${FIELDS.families}</dt>
                <dd>${thresholdLabel(proposal.family_count, proposal.families_required)}</dd></div>
              <div><dt>${FIELDS.categories}</dt>
                <dd>${thresholdLabel(proposal.category_count, proposal.categories_required)}</dd></div>
              <div><dt>${FIELDS.clusterRadius}</dt>
                <dd>${proposal.core_radius_miles ?? "?"} / ${proposal.radius_miles ?? "?"} mi</dd></div>
              <div><dt>${FIELDS.hubCreated}</dt>
                <dd>${proposal.created_hub ? BADGES.verified : SENTENCES.noHubCreated}</dd></div>
            </dl>
            <h4>${FIELDS.proposedMembers} (${proposal.members.length})</h4>
            <ul class="review-evidence">
              ${proposal.members.map((member, index) => html`<li key=${index}>
                <strong>${member.name}</strong>
                <span>${categoryLabel(member.actor_category)}${member.category_type
                  ? " · " + typeLabel(member.actor_category, member.category_type) : ""}</span>
              </li>`)}
            </ul>
          </div>`)}
      </section>`}



      ${view === "queue" && html`<div class="review-filters" aria-label="Review filters">
        <label><span>Run Type</span>
          <select value=${filters.run_type} onChange=${e => setFilter("run_type", e.target.value)}>
            ${RUN_TYPE_OPTIONS.map(option => html`
              <option key=${option.value} value=${option.value}>${option.label}</option>`)}
          </select></label>
        ${filters.run_type === "all" && html`<label><span>${FIELDS.recordKind}</span>
          <select value=${filters.entity_type} onChange=${e => setFilter("entity_type", e.target.value)}>
            <option value="all">${QUEUE.allTypes}</option>
            <option value="actor">${BADGES.actor}</option>
            <option value="person">${BADGES.person}</option>
            <option value="event">${BADGES.event}</option>
          </select></label>`}
        <label><span>${FIELDS.actorCategory}</span>
          <select value=${filters.actor_category} onChange=${e => setFilter("actor_category", e.target.value)}>
            <option value="all">${QUEUE.allCategories}</option>
            ${categoryOptions().map(option => html`
              <option key=${option.value} value=${option.value}>${option.label}</option>`)}
          </select></label>
        <label><span>${FIELDS.search}</span>
          <input type="search" value=${filters.search}
            onInput=${e => setFilter("search", e.target.value)} placeholder="Name or domain"/></label>
      </div>`}
      ${error && html`<div class="review-message error" role="alert">${error}</div>`}
      ${feedback && html`<div class="review-message success" role="status">${feedback}</div>`}
      ${deepTarget && deep?.key === deepTarget.key && html`<section class="review-deep" aria-label="Deep Pull">
        <div>
          <strong>Deep Pull for ${deepTarget.name}</strong>
          ${deep.state === "planning" && html`<p>Checking what a Deep Pull would read…</p>`}
          ${deep.state === "error" && html`<p>${deep.error}</p>`}
          ${deep.plan && !deep.plan.can_check && deep.state !== "done" && html`<p>${deep.plan.refusal
            || deep.plan.error || "Nothing is selected for a Deep Pull."}</p>`}
          ${deep.plan?.can_check && ["ready", "running", "failed"].includes(deep.state) && html`
            <p>${`Verified for ${deep.plan.topic?.name}: it may now read selected detail on this sector — `
              + `${deep.plan.fields.length} of ${deep.plan.schema_size} Deep items: `
              + `${deep.plan.fields.map(fieldLabel).join(", ")}.`}</p>
            <p class="review-deep-cost">Expected cost: ${deepCostLine(deep.plan.cost) || "—"}</p>`}
          ${deep.state === "running" && html`<p role="status">Reading up to three of its own pages — about a minute.</p>`}
          ${deep.state === "failed" && html`<p class="review-deep-error" role="alert">${deep.error}</p>`}
          ${deep.state === "done" && html`<p role="status">${deep.line}</p>`}
        </div>
        ${deep.plan?.can_check && deep.state !== "done" && html`<button type="button" class="btn"
          disabled=${deep.state === "running"} onClick=${runDeepPull}>
          ${deep.state === "running" ? "Running Deep Pull…" : "Run Deep Pull"}</button>`}
      </section>`}

      ${view === "queue" && html`<div class="review-workspace">
        <!-- NAMED RUNS (left panel) -->
        <nav class="review-runs" aria-label="Runs">
          <div class="review-queue-head">
            <strong>${RUN_TYPE_OPTIONS.find(o => o.value === filters.run_type)?.label || "Runs"}</strong>
            <span>${runs.length} ${runs.length === 1 ? "run" : "runs"}</span>
          </div>
          ${loading && html`<div class="review-empty" role="status">${SENTENCES.queueLoading}</div>`}
          ${!loading && !runs.length && html`<div class="review-empty">No runs with records here.</div>`}
          ${runs.map(run => html`
            <button key=${run.key} class=${"review-run " + (activeRun?.key === run.key ? "active" : "")}
              aria-pressed=${activeRun?.key === run.key}
              onClick=${() => { setRunKey(run.key); setSelectedId(null); }}>
              <strong>${run.run_name || run.label}</strong>
              ${filters.run_type === "all" && html`<span class="review-run-type">${runTypeName(run.run_type)}</span>`}
              <small>${runMeta(run, filters.status)}</small>
            </button>`)}
        </nav>

        <div class="review-main">
        ${!selectedId && html`<section class="review-records" aria-label="Records">
          ${!activeRun && !loading && html`<div class="review-empty">${SENTENCES.queueEmpty}</div>`}
          ${activeRun && html`
            <header class="review-records-head">
              <div>
                <span class="review-run-type">${runTypeName(activeRun.run_type)}</span>
                <h2>${activeRun.run_name || activeRun.label}</h2>
                <p class="review-subhead">${runMeta(activeRun, filters.status)}</p>
              </div>
            </header>
            <ul class="review-record-list">
              ${records.map(candidate => html`<li key=${candidate.candidate_id}>
                <button class="review-record" onClick=${() => openRecord(candidate.candidate_id)}>
                  <span class="review-row-main">
                    <strong>${candidate.display_name}</strong>
                    <small>${recordRowNote(candidate)}</small>
                  </span>
                  <span class=${"review-status " + candidate.status}>${
                    candidate.status !== "pending_review" ? reviewStatusLabel(candidate.status)
                      : (candidate.agent_metadata?.changes || []).length ? "To decide"
                      : candidate.agent_metadata?.source_table === "actor_update" ? "To check"
                      : reviewStatusLabel(candidate.status)}</span>
                </button></li>`)}
            </ul>`}
        </section>`}

        ${selectedId && html`<button class="btn ghost review-back" onClick=${backToRecords}>
          ← Back to Records</button>`}
        ${selectedId && html`<article class="review-detail" aria-live="polite">
          ${!selected && html`<div class="review-empty" role="status">${SENTENCES.queueLoading}</div>`}
          ${selected && html`
          <!-- HEADER -->
          <header class="review-detail-head">
            <div>
              <h2>${selected.display_name}</h2>
              <p class="review-subhead">
                ${present(draft.website) || MISSING.notProvided} · ${runChip(selected)}
              </p>
            </div>
            <div class="review-badges">
              ${headerBadges(selected).map((badge, index) => html`
                <span key=${index} class=${"review-status " + badge.tone}
                  title=${badge.hint || ""}>${badge.label}</span>`)}
            </div>
          </header>
          ${isMigratedBaseline(selected) && html`<div class="review-notice" role="status">
            <strong>${BADGES.migratedBaseline}.</strong> ${SENTENCES.migratedBaseline}
          </div>`}
          ${selected.admission_error && html`<div class="review-message error">
            <strong>Last admission failed:</strong> ${selected.admission_error}
          </div>`}

          <!-- 1 IDENTITY & CLASSIFICATION -->
          <section class="review-section">
            <h3><span class="review-step">1</span>${SECTIONS.identity}</h3>
            <div class="review-field-grid">
              ${textField(html, selected, "name", draft.name, edit, !pending || busy, draftErrors.name)}
              ${textField(html, selected, "website", draft.website, edit, !pending || busy, draftErrors.website)}
            </div>
            ${textField(html, selected, "description", draft.description, edit, !pending || busy, draftErrors.description)}
            ${isActor && html`<div class="review-field-grid">
              <label class=${"review-field " + (draftErrors.actor_category ? "invalid" : "")}>
                <span>${FIELDS.actorCategory}</span>
                <select value=${draft.actor_category ?? ""} disabled=${!pending || busy}
                  onChange=${e => editCategory(e.target.value)}>
                  <option value="">Choose a category</option>
                  ${categoryOptions().map(option => html`
                    <option key=${option.value} value=${option.value}>${option.label}</option>`)}
                </select>
                ${draftErrors.actor_category && html`<small class="field-error">${draftErrors.actor_category}</small>`}
              </label>
              <label class=${"review-field " + (draftErrors.category_type ? "invalid" : "")}>
                <span>${FIELDS.categoryType}</span>
                <select value=${draft.category_type ?? ""} disabled=${!pending || busy || !draft.actor_category}
                  onChange=${e => edit("category_type", e.target.value)}>
                  <option value="">${summary?.pending_classification ? MISSING.pending : "Choose a type"}</option>
                  ${typeOptions(draft.actor_category).map(option => html`
                    <option key=${option.value} value=${option.value} title=${option.meaning}>
                      ${option.label}
                    </option>`)}
                </select>
                ${draftErrors.category_type && html`<small class="field-error">${draftErrors.category_type}</small>`}
                ${summary?.pending_classification && html`
                  <small class="review-hint">${SENTENCES.pendingClassification}</small>`}
                ${summary?.category_type_retired && html`
                  <small class="review-hint">${typeLabel(draft.actor_category, RETIRED_CATCH_ALL)}</small>`}
              </label>
            </div>
            ${textField(html, selected, "category_note", draft.category_note, edit, !pending || busy, draftErrors.category_note)}
            ${String(draft.category_type ?? "") === NOT_APPLICABLE && html`
              <p class="review-hint">${SENTENCES.notApplicableNeedsNote}</p>`}`}
          </section>

          <!-- 2 LOCATION & PARENT -->
          ${isActor && html`<section class="review-section">
            <h3><span class="review-step">2</span>${SECTIONS.location}</h3>
            <div class="review-field-grid">
              <label class="review-field"><span>${FIELDS.country}</span>
                <select value=${normalizeCountry(draft.country) || ""} disabled=${!pending || busy}
                  onChange=${e => editCountry(e.target.value)}>
                  <option value="">${MISSING.notProvided}</option>
                  ${countryOptions().map(option => html`
                    <option key=${option.value} value=${option.value}>${option.label}</option>`)}
                  ${draft.country && !countryOptions().some(o => o.value === normalizeCountry(draft.country))
                    && html`<option value=${draft.country}>${draft.country}</option>`}
                </select></label>
              <label class="review-field"><span>${FIELDS.state}</span>
                <select value=${draft.state ?? ""} disabled=${!pending || busy}
                  onChange=${e => editState(e.target.value)}>
                  <option value="">${MISSING.notProvided}</option>
                  ${stateOptions().map(option => html`
                    <option key=${option.value} value=${option.value}>${option.label}</option>`)}
                </select></label>
              <label class="review-field"><span>${FIELDS.region}</span>
                <input value=${summary.region} readonly disabled aria-readonly="true"/>
</label>
              ${textField(html, selected, "location_city", draft.location_city, edit, !pending || busy, draftErrors.location_city)}
            </div>
            ${twoWayKind(selected) === "update" && (() => {
              const row = factRows.find(item => item.key === "location");
              return row && (row.value || row.update || row.pending) && html`<div class="review-boxes">
                ${lightBox(html, {...row, label: "Location read from its pages"})}</div>`;
            })()}
            <dl class="review-facts">
              <div><dt>${FIELDS.coordinates}</dt><dd>
                ${selected.agent_metadata?.coordinates ? "Geocoded" : MISSING.notFound}
              </dd></div>
              <div><dt>${FIELDS.multiLocation}</dt><dd>
                ${selected.agent_metadata?.multi_location ? "Yes" : "No"}
              </dd></div>
            </dl>
            <h4>${FIELDS.parentOrganization}</h4>
            ${parent.hasParent
              ? html`<dl class="review-facts">
                  <div><dt>${FIELDS.parentOrganization}</dt><dd>${parent.name}</dd></div>
                  <div><dt>${FIELDS.parentLinkType}</dt><dd>${parent.linkType}</dd></div>
                  <div><dt>${FIELDS.parentSource}</dt><dd>${parent.source
                    ? html`<a href=${parent.source} target="_blank" rel="noreferrer">${parent.source}</a>`
                    : MISSING.notFound}</dd></div>
                </dl>`
              : html`<p class="review-complete" title=${parent.tooltip}>
                  <strong>${parent.missing}</strong> — ${parent.tooltip}
                </p>`}
            <h4>${FIELDS.otherRelationships} <span class="review-chip">${BADGES.readOnly}</span></h4>
            ${!relationships.length && html`<p class="muted">${MISSING.notFound}</p>`}
            <ul class="review-evidence">
              ${relationships.map((edge, index) => html`<li key=${index}>
                <strong>${edge.label}</strong> ${edge.direction} ${edge.counterpart}
                ${edge.counterpartType && html`<span>${edge.counterpartType}</span>`}
                ${edge.source
                  ? html`<a href=${edge.source} target="_blank" rel="noreferrer">${edge.source}</a>`
                  : html`<span>${MISSING.notFound}</span>`}
              </li>`)}
            </ul>
          </section>`}

          <!-- 3 SECTOR, TOPIC & HUB -->
          ${isActor && html`<section class="review-section">
            <h3><span class="review-step">3</span>${SECTIONS.sector}</h3>
            <div class="review-two-up">
              <div class="review-box">
                <h4>${FIELDS.sector} <span class="review-chip">${BADGES.hubDimension}</span></h4>
                <label class="review-field">
                  <span>${FIELDS.primarySector}</span>
                  <select value=${draft.primary_sector ?? ""} disabled=${!pending || busy}
                    data-sectors=${sectorState.version}
                    onChange=${e => e.target.value === NEW_SECTOR
                      ? startNewSector(selected.agent_metadata?.unmatched_sector_suggestion)
                      : edit("primary_sector", e.target.value)}>
                    <option value="">${MISSING.notApplicable}</option>
                    ${sectorOptions(selected.agent_metadata?.sector_codes || []).map(option => html`
                      <option key=${option.value} value=${option.value}>${option.label}</option>`)}
                    ${sectorState.canCreate && pending && html`
                      <option value=${NEW_SECTOR}>${BUTTONS.addSector}</option>`}
                  </select></label>
                ${!(selected.agent_metadata?.sector_codes || []).length
                  && selected.agent_metadata?.unmatched_sector_suggestion && html`
                  <p class="review-notice">${SENTENCES.noSectorMatched(
                    selected.agent_metadata.unmatched_sector_suggestion)}</p>`}
                ${newSector && html`<div class="review-new-sector">
                  <label class="review-field"><span>${FIELDS.newSectorName}</span>
                    <input value=${newSector.name} maxLength="80"
                      onInput=${e => setNewSector({...newSector, name: e.target.value})}/></label>
                  <label class="review-field"><span>${FIELDS.newSectorDescription}</span>
                    <textarea rows="2" maxLength="500" value=${newSector.description}
                      onInput=${e => setNewSector({...newSector, description: e.target.value})}></textarea></label>
                  ${newSector.error && html`<p class="field-error">${newSector.error}</p>`}
                  <div class="review-new-sector-actions">
                    <button class="btn" disabled=${newSector.busy || newSector.name.trim().length < 2}
                      onClick=${createSector}>${newSector.busy ? BUTTONS.addingSector : BUTTONS.createSector}</button>
                    <button class="btn ghost" disabled=${newSector.busy}
                      onClick=${() => setNewSector(null)}>${BUTTONS.cancel}</button>
                  </div>
                </div>`}
                ${(selected.agent_metadata?.sector_codes || []).length > 0 && html`
                  <p class="review-hint">${FIELDS.otherSectors}:
                    ${(selected.agent_metadata.sector_codes || []).map(sectorLabel).join(" · ")}
                    <span class="review-chip">${BADGES.readOnly}</span></p>`}
              </div>
              <div class="review-box">
                <h4>${FIELDS.whyItMatched}</h4>
                ${(() => {
                  // Two sources say this, and the dedicated one is often empty:
                  // discovery records the explanation as a Light Pull fact, while
                  // agent_metadata.why_matched is only set on some paths. Reading
                  // both means one box instead of a populated box beside an empty
                  // one claiming Not Yet Collected.
                  const why = selected.agent_metadata?.why_matched || whyMatchedFact(selected);
                  if (!why) return html`<p class="muted">${MISSING.notYetChecked}</p>`;
                  return html`<dl class="review-facts">
                    <div><dt>${FIELDS.strength}</dt><dd>${matchStrengthLabel(why.strength)}</dd></div>
                  </dl>
                  <p>${why.reason || MISSING.notFound}</p>
                  ${why.source_url && html`
                    <a href=${why.source_url} target="_blank" rel="noreferrer">${why.source_url}</a>`}`;
                })()}
              </div>
            </div>
            <h4>${FIELDS.currentHubs}</h4>
            ${!memberships.length && html`<p class="muted">${MISSING.notFound}</p>`}
            <ul class="review-evidence">
              ${memberships.map((hub, index) => html`<li key=${"m" + index}>
                <strong>${hub.name || hub.hub_id}</strong>
                <span>${FIELDS.distance}: ${hub.distance_miles != null
                  ? `${hub.distance_miles} mi` : MISSING.notFound}</span>
                ${hub.outside_radius && html`<span class="review-status reason">
                  ${BADGES.hubMemberOutsideRadius}</span>`}
              </li>`)}
            </ul>
            <h4>${FIELDS.suggestedHubs}</h4>
            ${!suggestions.length && html`<p class="muted">${MISSING.notYetChecked}</p>`}
            <ul class="review-evidence">
              ${suggestions.map((hub, index) => html`<li key=${"s" + index}>
                <strong>${hub.name || hub.hub_id}</strong>
                <span>${FIELDS.distance}: ${hub.distance_miles != null
                  ? `${hub.distance_miles} mi` : MISSING.notFound}</span>
                <span>${FIELDS.suggestion}: ${hub.reason || MISSING.notFound}</span>
              </li>`)}
            </ul>
            <label class="review-field"><span>${BUTTONS.chooseHub}</span>
              <select value=${hubIds[0] ?? ""} disabled=${!pending || busy}
                onChange=${e => setHubIds(e.target.value ? [e.target.value] : [])}>
                <option value="">${SENTENCES.noHubOption}</option>
                ${hubOptions.map(option => html`
                  <option key=${option.hub_id} value=${option.hub_id}>${option.label}</option>`)}
              </select></label>
          </section>`}

          <!-- 4 LIGHT PULL INFORMATION -->
          ${isActor && html`<section class="review-section">
            <h3><span class="review-step">4</span>${SECTIONS.facts}</h3>
            ${twoWayKind(selected) === "update" && html`<p class="review-hint">${[
              selected.agent_metadata?.topic_name && `Sector: ${selected.agent_metadata.topic_name}.`,
              "Values in the boxes are on the map, each marked with what the latest update found.",
              (selected.agent_metadata?.changes || []).some(change => change.kind === "fact")
                && "A box marked Proposed has a change waiting below."].filter(Boolean).join(" ")}</p>`}
            <h4>${FIELDS.commonLightPull}</h4>
            <div class="review-boxes">
              ${lightBoxes.common.map(row => lightBox(html, row))}
            </div>

            <h4>${categoryLabel(draft.actor_category) || FIELDS.categoryLightPull}</h4>
            ${!lightBoxes.specific.length && html`
              <p class="muted">${SENTENCES.chooseCategoryForBoxes}</p>`}
            <div class="review-boxes">
              ${lightBoxes.specific.map(row => lightBox(html, row))}
            </div>

            <details class="review-subsection">
              <summary>${FACTS.history}</summary>
              ${!historyRows.length && html`<p class="muted">${SENTENCES.noFacts}</p>`}
              <div class="review-match"><table>
                <thead><tr>
                  <th>${FIELDS.field}</th><th>${FIELDS.value}</th><th>${FIELDS.dateRead}</th>
                  <th>${FIELDS.confidence}</th><th>${FACTS.current}</th>
                </tr></thead>
                <tbody>${historyRows.map((row, index) => html`<tr key=${row.key + index}>
                  <th scope="row">${row.label}</th>
                  <td>${formatFactValue(row.value)}</td>
                  <td>${row.dateRead || MISSING.notFound}</td>
                  <td>${row.confidence || MISSING.notFound}</td>
                  <td>${row.isCurrent ? FACTS.current : row.lifecycle || "Superseded"}</td>
                </tr>`)}</tbody></table></div>
            </details>
            ${deepFacts.length > 0 && html`<details class="review-subsection">
              <summary>Verified Deep Pull evidence</summary>
              <ul class="review-evidence">${deepFacts.map((fact, index) => html`<li key=${index}>
                <strong>${factRowLabel(selected, String(fact.fact_key))}</strong>
                <span>${formatFactValue(fact.value)}</span>
              </li>`)}</ul>
            </details>`}
          </section>`}

          <!-- Event and person records use their own field sets -->
          ${!isActor && html`<section class="review-section">
            <h3><span class="review-step">2</span>${selected.entity_type === "event"
              ? "Event Fields" : "Person Fields"}</h3>
            <div class="review-field-grid">
              ${(selected.editable_fields || [])
                .filter(field => !["name", "description", "website"].includes(field))
                .map(field => textField(html, selected, field, draft[field], edit, !pending || busy, draftErrors[field]))}
            </div>
            ${selected.entity_type === "event" && html`<div class="review-box">
              <h4>${FIELDS.ghusEventNotes}</h4>
              <p class="muted">${SENTENCES.eventNotesEmpty}</p>
            </div>`}
          </section>`}

          ${!isActor && collectedBlock(html, selected)}
          ${isFactReview(selected) && factChangeBlock(html, selected)}
          ${(() => {
            const others = relatedItems(data.candidates, selected);
            return others.length > 0 && html`<section class="review-section">
              <h3>Also waiting for this actor</h3>
              <ul class="review-evidence">${others.map(item => html`<li key=${item.id}>
                <strong>${item.label}</strong> <span>${item.run}</span>
                <button class="link" onClick=${() => openRecord(item.id)}>Open</button>
              </li>`)}</ul>
            </section>`;
          })()}
          ${twoWayKind(selected) === "update" && changesBlock(html, selected, {
            onDecide: decideChange, disabled: busy || writerDown, reviewer, setReviewer})}
          ${twoWayKind(selected) === "update" && updateHistoryBlock(html, selected)}
          ${["relationship", "hub"].includes(twoWayKind(selected)) && twoWayBlock(html, selected)}

          <!-- 5 POSSIBLE DUPLICATES -->
          ${matches.length > 0 && html`<section class="review-section">
            <h3><span class="review-step">5</span>${SECTIONS.duplicates}</h3>
            ${matches.map((match, index) => html`<div class="review-match" key=${index}>
              <strong>${match.name || match.entity_id}</strong>
              <table><thead><tr>
                <th>${FIELDS.field}</th><th>This Candidate</th><th>Existing Record</th>
              </tr></thead>
              <tbody>${diffFields(draft, match).map(row => html`<tr key=${row.field}>
                <th scope="row">${reviewFieldLabel(row.field)}</th>
                <td>${formatFactValue(row.candidate)}</td>
                <td>${formatFactValue(row.existing)}</td>
              </tr>`)}</tbody></table>
            </div>`)}
          </section>`}

          <!-- 6 AUDIT & DETAILS -->
          <details class="review-section review-audit">
            <summary><span class="review-step">6</span>${SECTIONS.audit}</summary>
            <dl class="review-facts">
              <div><dt>${FIELDS.candidateId}</dt><dd>${selected.candidate_id}</dd></div>
              <div><dt>${FIELDS.runId}</dt><dd>${selected.source_run_id}</dd></div>
              <div><dt>${FIELDS.created}</dt><dd>${formatDate(selected.created_at)}</dd></div>

            </dl>
            ${editableHere.length > 0 && html`<div class="review-field-grid">
              ${editableHere.map(field =>
                textField(html, selected, field, draft[field], edit, !pending || busy, draftErrors[field]))}
            </div>`}
            <details><summary>${FIELDS.rawCandidate}</summary>
              <pre>${JSON.stringify(selected.agent_metadata, null, 2)}</pre></details>
            <details><summary>${FIELDS.verificationHistory}</summary>
              <pre>${JSON.stringify(selected.agent_metadata?.verification_history
                || selected.agent_metadata?._verification || null, null, 2)}</pre></details>
          </details>

          <!-- DECISION + STICKY FOOTER -->
          <section class="review-section review-decision">
            <h3>Decision</h3>
            ${writerDown && html`<p class="review-hint">${SENTENCES.writerUnavailable}</p>`}
            ${isUpdateProfile(selected) && (selected.agent_metadata?.changes || []).length > 0 && html`
              <p class="review-hint">Decide the ${selected.agent_metadata.changes.length} change(s) above
                first; then mark this profile as reviewed.</p>`}
            <div class="review-field-grid">
              <label class="review-field"><span>Decision</span>
                <select value=${decisionKind} disabled=${!pending || busy}
                  onChange=${e => setDecisionKind(e.target.value)}>
                  ${decisionOptions(selected.entity_type, selected).map(option => html`
                    <option key=${option.value} value=${option.value}>${option.label}</option>`)}
                </select></label>
              ${decisionKind === "same_existing" && html`
                <label class="review-field"><span>Existing record</span>
                  <input value=${targetId} disabled=${!pending || busy}
                    onInput=${e => setTargetId(e.target.value)} placeholder="Existing record ID"/></label>`}
            </div>
            ${decisionKind === "reject" && !twoWayKind(selected) && html`<div class="review-field-grid">
              <label class="review-field"><span>${FIELDS.rejectionReason}</span>
                <select value=${rejectionReason} onChange=${e => setRejectionReason(e.target.value)}
                  disabled=${!pending || busy}>
                  <option value="">Select a reason</option>
                  ${REJECTION_REASONS.map(reason => html`
                    <option key=${reason} value=${reason}>${reason}</option>`)}
                </select></label>
              ${rejectionReason === "Other" && html`
                <label class="review-field"><span>Explain</span>
                  <input value=${rejectionOther} disabled=${!pending || busy}
                    onInput=${e => setRejectionOther(e.target.value)}/></label>`}
            </div>
            <p class="review-reason">${SENTENCES.noDeletion}</p>`}
            ${isActor && !twoWayKind(selected) && ["same_existing", "new"].includes(decisionKind) && html`
              <label class="review-field"><span>${BUTTONS.chooseHub}</span>
                <input type="checkbox" checked=${proposeHub} disabled=${!pending || busy}
                  onChange=${e => setProposeHub(e.target.checked)}/></label>`}
            ${proposeHub && html`<div class="review-field-grid">
              <label class="review-field"><span>Proposed hub name</span>
                <input value=${proposedHub.name} disabled=${!pending || busy}
                  onInput=${e => setProposedHub(current => ({...current, name: e.target.value}))}/></label>
              <label class="review-field"><span>Rationale</span>
                <input value=${proposedHub.rationale} disabled=${!pending || busy}
                  onInput=${e => setProposedHub(current => ({...current, rationale: e.target.value}))}/></label>
            </div>`}
            <div class="review-field-grid">
              <label class=${"review-field " + (pending && !reviewer.trim() ? "invalid" : "")}>
                <span>${FIELDS.reviewer}</span>
                <input value=${reviewer} disabled=${!pending || busy} required
                  onInput=${e => setReviewer(e.target.value)}/></label>
              <label class="review-field"><span>${FIELDS.notes}</span>
                <input value=${notes} disabled=${!pending || busy}
                  onInput=${e => setNotes(e.target.value)}/></label>
            </div>
          </section>

          <footer class="review-footer">
            <button class="btn danger" disabled=${!pending || busy || writerDown}
              onClick=${() => { setDecisionKind("reject"); }}>${twoWayKind(selected)
                ? TWO_WAY_ANSWERS[twoWayKind(selected)][1] : BUTTONS.reject}</button>
            <button class="btn ghost" disabled=${!pending || busy || writerDown}
              onClick=${() => { setDecisionKind("defer"); }}>${BUTTONS.park}</button>
            ${twoWayKind(selected) !== "update" && html`<button class="btn ghost"
              disabled=${!pending || busy || Object.keys(draftErrors).length > 0}
              onClick=${save}>${BUTTONS.saveEdits}</button>`}
            <button class="btn" onClick=${decide} disabled=${!canSubmitReview({
              candidate: selected, reviewer, rejectionReason, rejectionOther, decisionKind,
              targetId, busy, admissionConfigured: data.admission_configured, draftErrors,
            })}>${twoWayKind(selected) && decisionKind !== "defer"
              ? decisionOptions(selected.entity_type, selected).find(o => o.value === decisionKind)?.label
              : decisionKind === "reject" ? BUTTONS.reject
              : decisionKind === "defer" ? BUTTONS.park : BUTTONS.verify}</button>
          </footer>`}
        </article>`}
        </div>
      </div>`}
    </section>`;
  };
}
