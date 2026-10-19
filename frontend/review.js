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
} from "./taxonomy.js?v=20261015";
import {
  BADGES, BUTTONS, CADENCES, FACTS, FIELDS, QUEUE, SECTIONS, SENTENCES,
  TRIGGERS,
} from "./labels.js?v=20261015";

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

/** What an actor update wrote: one row per box, before and after, with its source. */
export function updateRows(candidate) {
  const meta = candidate?.agent_metadata || {};
  return (meta.written || []).map((fact) => ({
    field: fact.fact_key,
    before: fact.previous_value != null ? formatFactValue(fact.previous_value) : "—",
    after: fact.collection_state === "found" ? formatFactValue(fact.value) : "Not stated on its pages",
    how: fact.lifecycle_state === "conflict_flagged" ? "Conflict — in this run, for a decision"
      : fact.lifecycle_state === "pending_update" ? "GHUS value kept — change in this run, for a decision"
      : fact.collection_state !== "found" ? "Recorded as not found"
      : fact.previous_value != null ? "Replaced the earlier value (kept in history)" : "New",
    source_url: fact.source_url || null,
    confidence: fact.confidence || "—",
  }));
}

function updateBlock(html, candidate) {
  const meta = candidate?.agent_metadata || {};
  const rows = updateRows(candidate);
  return html`<section class="review-section">
    <h3>What this update wrote</h3>
    <p class="review-hint">Already on the map, written through the GHUS fact writer with its
      sources; earlier values stay in the history. ${meta.corroborated
        ? `${meta.corroborated} recorded value(s) were confirmed by its pages. ` : ""}Read
      ${(meta.pages_read || []).length} page(s) · ${typeof meta.spent_usd === "number"
        ? `$${meta.spent_usd.toFixed(3)}` : ""}.</p>
    <table><thead><tr><th>Box</th><th>Before</th><th>Now</th><th>What it did</th><th>Source</th></tr></thead>
    <tbody>${rows.map(row => html`<tr key=${row.field}>
      <th scope="row">${reviewFieldLabel(row.field)}</th><td>${row.before}</td><td>${row.after}</td>
      <td>${row.how}</td>
      <td>${row.source_url ? html`<a href=${row.source_url} target="_blank" rel="noreferrer">open</a>` : "—"}</td>
    </tr>`)}</tbody></table>
    ${(meta.pages_read || []).length > 0 && html`<p class="review-hint">Pages read:
      ${meta.pages_read.map((url, i) => html`${i ? " · " : ""}<a href=${url} target="_blank"
        rel="noreferrer">${url.replace(/^https?:\/\//, "")}</a>`)}</p>`}
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
    date_read: fact.date_read ? String(fact.date_read).slice(0, 10) : "—",
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
  recurring_pattern: "Recurrence", sponsoring_orgs: "Organizer",
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
  return (candidate?.agent_metadata?.facts || [])
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

/** Turn one key of a fact object into "Label: value", or null if it says nothing. */
function factEntry(key, value) {
  if (value === null || value === undefined) return null;
  if (FACT_DATE_KEYS.has(key)) return null;
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
  const layerRan = facts.size > 0;
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
        dateRead: present(fact.date_read),
        confidence: confidenceLabel(present(fact.confidence)),
        origin: present(fact.source_origin),
        // The organisation's own pages the Light Pull read for this box. A
        // "Not Found" with pages listed means those pages were read and none
        // of them states it - never that nobody looked.
        pagesRead: Array.isArray(fact.pages_read) ? fact.pages_read.filter(Boolean) : [],
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
      : formatFactValue(row.value)}</dd>
    ${row.state && row.pagesRead?.length > 0 && html`<small>Checked:
      ${row.pagesRead.map((url, index) => html`${index ? " · " : " "}<a href=${url}
        target="_blank" rel="noreferrer">${pageLabel(url)}</a>`)}
    </small>`}
    ${provenance && html`<small>
      ${row.source
        ? html`<a href=${row.source} target="_blank" rel="noreferrer">Source</a>`
        : ""}
      ${row.confidence ? (row.source ? ` · ${row.confidence}` : row.confidence) : ""}
    </small>`}
  </div>`;
}

function formatSync(lastSync) {
  const row = (lastSync || []).find(item => item.source === "postgresql");
  return row?.last_success_at
    ? new Date(row.last_success_at * 1000).toLocaleString()
    : "Not yet synchronized";
}

function formatDate(seconds) {
  return seconds ? new Date(seconds * 1000).toLocaleDateString() : SENTENCES.noRunRecorded;
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
  const parts = String(value || "").split("-").map(Number);
  if (parts.length !== 3 || parts.some(Number.isNaN)) return String(value || "");
  return new Date(parts[0], parts[1] - 1, parts[2]).toLocaleDateString();
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
      status: "pending_review", entity_type: "all", run_group: "all",
      actor_category: "all", review_reason: "all", search: "",
    });
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
    const keys = useRef(new Map());

    async function load(signal, force = false) {
      setLoading(true);
      setError("");
      const params = new URLSearchParams();
      Object.entries(filters).forEach(([key, value]) => {
        if (value && value !== "all") params.set(key, value);
      });
      if (force) params.set("refresh", "true");
      try {
        const body = await request(`/api/review/candidates?${params}`, {signal});
        setData(body);
        setSelectedId(current =>
          body.candidates.some(item => item.candidate_id === current)
            ? current : body.candidates[0]?.candidate_id ?? null);
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
    }, [filters.status, filters.entity_type, filters.run_group, filters.actor_category,
        filters.review_reason, filters.search]);

    useEffect(() => {
      if (!selectedId) { setSelected(null); setDraft({}); return; }
      let active = true;
      request(`/api/review/candidates/${selectedId}`).then(candidate => {
        if (!active) return;
        setSelected(candidate);
        setDraft({...candidate.reviewed_payload});
        // Two values for one box: keeping the map's value is the safe default.
        // Keeping the map as it is is the safe default; a proposal waits.
        setDecisionKind(isFactReview(candidate) ? "reject" : twoWayKind(candidate) ? "defer"
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
    const groups = groupQueue(data.candidates, data.run_groups);
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
        <label><span>${FIELDS.recordKind}</span>
          <select value=${filters.entity_type} onChange=${e => setFilter("entity_type", e.target.value)}>
            <option value="all">${QUEUE.allTypes}</option>
            <option value="actor">${BADGES.actor}</option>
            <option value="person">${BADGES.person}</option>
            <option value="event">${BADGES.event}</option>
          </select></label>
        <label><span>${FIELDS.reviewReason}</span>
          <select value=${filters.review_reason} onChange=${e => setFilter("review_reason", e.target.value)}>
            <option value="all">${QUEUE.allReasons}</option>
            ${reasonOptions(data.reason_counts, filters.review_reason).map(([kind, count]) => html`
              <option key=${kind} value=${kind} title=${reviewReasonHint(kind)}>
                ${reviewReasonLabel(kind)}${count ? ` (${count})` : ""}</option>`)}
          </select></label>
        <label><span>${FIELDS.sourceRun}</span>
          <select value=${filters.run_group} onChange=${e => setFilter("run_group", e.target.value)}>
            <option value="all">${QUEUE.allRuns}</option>
            ${(data.run_groups || []).map(group => html`
              <option key=${group.key} value=${group.key}>${runOptionLabel(group)}</option>`)}
          </select></label>
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

      ${view === "queue" && html`<div class="review-workspace">
        <!-- QUEUE (left rail) -->
        <div class="review-queue" aria-label=${QUEUE.title}>
          <div class="review-queue-head">
            <strong>${QUEUE.title}</strong>
            <span>${data.candidates.length} ${QUEUE.shown.toLocaleLowerCase()}</span>
          </div>
          ${loading && html`<div class="review-empty" role="status">${SENTENCES.queueLoading}</div>`}
          ${!loading && !data.candidates.length && html`<div class="review-empty">${SENTENCES.queueEmpty}</div>`}
          ${groups.map(group => html`<div class="review-queue-group" key=${group.key}>
            <div class="review-group-head">
              <strong>${group.label}</strong>
              <span>${group.candidates.length}</span>
              ${group.is_backlog && html`<small title=${SENTENCES.backlogGroup}>${BADGES.readOnly}</small>`}
            </div>
            ${group.candidates.map(candidate => html`
              <button key=${candidate.candidate_id}
                class=${"review-row " + (selectedId === candidate.candidate_id ? "active" : "")}
                aria-pressed=${selectedId === candidate.candidate_id}
                onClick=${() => setSelectedId(candidate.candidate_id)}>
                <span class="review-row-main">
                  <strong>${candidate.display_name}</strong>
                  <small>${RECORD_KIND_LABELS[candidate.entity_type] || candidate.entity_type}
                    ${candidate.review_reason ? ` · ${reviewReasonLabel(candidate.review_reason)}` : ""}</small>
                </span>
                <span class=${"review-status " + candidate.status}>${reviewStatusLabel(candidate.status)}</span>
              </button>`)}
          </div>`)}
        </div>

        <article class="review-detail" aria-live="polite">
          ${!selected && html`<div class="review-empty">${SENTENCES.queueSelectOne}</div>`}
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

          ${isFactReview(selected) && factChangeBlock(html, selected)}
          ${twoWayKind(selected) === "update" && updateBlock(html, selected)}
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
            ${isActor && ["same_existing", "new"].includes(decisionKind) && html`
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
            <button class="btn ghost" disabled=${!pending || busy || Object.keys(draftErrors).length > 0}
              onClick=${save}>${BUTTONS.saveEdits}</button>
            <button class="btn" onClick=${decide} disabled=${!canSubmitReview({
              candidate: selected, reviewer, rejectionReason, rejectionOther, decisionKind,
              targetId, busy, admissionConfigured: data.admission_configured, draftErrors,
            })}>${twoWayKind(selected) && decisionKind !== "defer"
              ? decisionOptions(selected.entity_type, selected).find(o => o.value === decisionKind)?.label
              : decisionKind === "reject" ? BUTTONS.reject
              : decisionKind === "defer" ? BUTTONS.park : BUTTONS.verify}</button>
          </footer>`}
        </article>
      </div>`}
    </section>`;
  };
}
