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
// kind of missing it is — Not Found, Not Yet Checked, Not Provided, Pending
// Classification, Not Available, Not Applicable — because those six are not
// interchangeable.

import {
  CATEGORY_LIGHT_ROWS, COMMON_LIGHT_ROWS, MISSING, NON_US_REGION, NOT_APPLICABLE,
  NO_PARENT_TOOLTIP, PARENT_LINK_TYPES, RETIRED_CATCH_ALL, THEMATIC_SECTORS,
  categoryLabel, categoryOptions, isParentLink, isValidPair, linkTypeLabel,
  regionForState, sectorLabel, showsRankings, showsTrl, stateOptions, typeLabel,
  typeOptions,
} from "./taxonomy.js";
import {BADGES, BUTTONS, FACTS, FIELDS, QUEUE, SECTIONS, SENTENCES, TRIGGERS} from "./labels.js";

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
  category_doubt: BADGES.categoryDoubt,
  geocode_failed: BADGES.geocodeFailed,
  hub_needs_review: BADGES.hubNeedsReview,
  hub_assignment: BADGES.hubAssignment,
  hub_radius_overlap: BADGES.hubRadiusOverlap,
  hub_member_outside_radius: BADGES.hubMemberOutsideRadius,
  hub_center_drift: BADGES.hubCenterDrift,
  hub_proposal: BADGES.hubProposal,
  same_topic_overlap: BADGES.sameTopicOverlap,
  possible_duplicate: BADGES.possibleDuplicate,
  fact_conflict: BADGES.factConflict,
  pending_update: BADGES.pendingUpdate,
  // The remaining kinds the review_item CHECK constraint allows. Without these
  // a real queue row would show a raw lower-case code.
  identity: BADGES.identityReview,
  affiliation_change: BADGES.affiliationChange,
  classification: BADGES.classificationReview,
  geocode: BADGES.geocodeReview,
  new_hub: BADGES.newHubProposal,
  pending_human_update: BADGES.pendingHumanUpdate,
};
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

export function decisionOptions(entityType) {
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

export function formatFactValue(value) {
  if (value === null || value === undefined) return "No value recorded";
  if (typeof value === "string") return value;
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
 * layer ran and found nothing; "Not Yet Checked" means it has not run. The two
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
      };
    });
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
    badges.push({tone: "reason", label: reviewReasonLabel(candidate.review_reason)});
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

async function request(url, options = {}) {
  const response = await fetch(url, options);
  let body = {};
  try { body = await response.json(); } catch {}
  if (!response.ok) throw new Error(errorMessage(body, response.status));
  return body;
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
        setDecisionKind(candidate.duplicate_state === "already_exists" ? "same_existing" : "new");
        setTargetId("");
        setRejectionReason("");
        setRejectionOther("");
        setHubIds([]);
        setProposeHub(false);
        setFactView("current");
      }).catch(exception => { if (active) setError(exception.message); });
      return () => { active = false; };
    }, [selectedId]);

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
      const lines = [`${selected.display_name} — ${decisionOptions(selected.entity_type)
        .find(option => option.value === kind)?.label}`];
      if (edits.length) {
        lines.push("", "Pending edits:");
        for (const item of edits) {
          lines.push(`  ${reviewFieldLabel(item.field)}: ${item.before ?? "—"} → ${item.after ?? "—"}`);
        }
      }
      if (kind === "new" || kind === "same_existing") {
        lines.push("", SENTENCES.verifyConsequences);
      }
      if (kind === "reject") {
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
    const groups = groupQueue(data.candidates, data.run_groups);
    const isActor = selected?.entity_type === "actor";
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
      <p class="lead">${SENTENCES.pageLead}</p>

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
      ${error && html`<div class="review-message error" role="alert">${error}</div>`}
      ${feedback && html`<div class="review-message success" role="status">${feedback}</div>`}

      <div class="review-workspace">
        <!-- QUEUE (left rail) -->
        <div class="review-queue" aria-label=${QUEUE.title}>
          <div class="review-queue-head">
            <strong>${QUEUE.title}</strong>
            <span>${data.candidates.length} ${QUEUE.shown.toLocaleLowerCase()}</span>
          </div>
          <div class="review-filters" aria-label="Review filters">
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
                ${Object.keys(REVIEW_REASON_LABELS).map(kind => html`
                  <option key=${kind} value=${kind}>${reviewReasonLabel(kind)}</option>`)}
              </select></label>
            <label><span>${FIELDS.sourceRun}</span>
              <select value=${filters.run_group} onChange=${e => setFilter("run_group", e.target.value)}>
                <option value="all">${QUEUE.allRuns}</option>
                ${(data.run_groups || []).map(group => html`
                  <option key=${group.key} value=${group.key}>
                    ${group.label}${group.trigger_label ? ` · ${group.trigger_label}` : ""}
                  </option>`)}
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
                <span key=${index} class=${"review-status " + badge.tone}>${badge.label}</span>`)}
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
              ${textField(html, selected, "country", draft.country, edit, !pending || busy, draftErrors.country)}
              <label class="review-field"><span>${FIELDS.state}</span>
                <select value=${draft.state ?? ""} disabled=${!pending || busy}
                  onChange=${e => editState(e.target.value)}>
                  <option value="">${MISSING.notProvided}</option>
                  ${stateOptions().map(option => html`
                    <option key=${option.value} value=${option.value}>${option.label}</option>`)}
                </select></label>
              <label class="review-field"><span>${FIELDS.region}</span>
                <input value=${summary.region} readonly disabled aria-readonly="true"/>
                <small class="review-hint">${SENTENCES.regionDerived}</small></label>
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
            <p class="review-hint">${SENTENCES.parentPickerRule}</p>
            <p class="muted">Parent link types offered: ${PARENT_LINK_TYPES.map(o => o.label).join(" · ")}</p>
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
                <p class="review-hint">${SENTENCES.sectorDecidesHub}</p>
                <ul class="review-checklist">
                  ${THEMATIC_SECTORS.map(([code, label]) => html`<li key=${code}>
                    <label><input type="checkbox" disabled=${!pending || busy}
                      checked=${(selected.agent_metadata?.sector_codes || []).includes(code)}
                      onChange=${() => setFeedback(
                        "Sector edits are recorded through the canonical writer; see the decision panel.")}/>
                      ${label}</label>
                  </li>`)}
                </ul>
                ${(selected.agent_metadata?.sector_codes || [])
                  .filter(code => !THEMATIC_SECTORS.some(([value]) => value === code))
                  .map(code => html`<p key=${code} class="muted">
                    ${sectorLabel(code)} <span class="review-chip">${BADGES.readOnly}</span>
                  </p>`)}
              </div>
              <div class="review-box">
                <h4>${FIELDS.whyItMatched}</h4>
                ${(() => {
                  const why = selected.agent_metadata?.why_matched;
                  if (!why) return html`<p class="muted">${MISSING.notYetChecked}</p>`;
                  return html`<dl class="review-facts">
                    <div><dt>${FIELDS.strength}</dt><dd>${matchStrengthLabel(why.strength)}</dd></div>
                    <div><dt>${FIELDS.dateRead}</dt><dd>${why.date_read || MISSING.notFound}</dd></div>
                  </dl>
                  <p>${why.reason || MISSING.notFound}</p>
                  ${why.source_url && html`
                    <a href=${why.source_url} target="_blank" rel="noreferrer">${why.source_url}</a>`}`;
                })()}
              </div>
            </div>
            <dl class="review-facts">
              <div><dt>${FIELDS.topic} <span class="review-chip">${BADGES.secondary}</span></dt><dd>
                ${present(selected.agent_metadata?.topic_label) || MISSING.notYetChecked}
              </dd></div>
            </dl>
            <p class="review-hint">${SENTENCES.topicIsSecondary}</p>
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
            ${memberships.length > 0 && html`<p class="review-hint">${SENTENCES.membershipsKept}</p>`}
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
            ${suggestions.length > 0 && html`<p class="review-hint">${SENTENCES.suggestionIsNotADecision}</p>`}
            <div class="review-field-grid">
              <label class="review-field"><span>${BUTTONS.chooseHub}</span>
                <select multiple value=${hubIds} disabled=${!pending || busy}
                  onChange=${e => setHubIds([...e.target.selectedOptions].map(option => option.value))}>
                  ${hubs.map(hub => html`
                    <option key=${hub.hub_id} value=${hub.hub_id}>${hub.name || hub.hub_id}</option>`)}
                </select></label>
              <label class="review-field"><span>${BUTTONS.leaveUnassigned}</span>
                <input type="checkbox" checked=${!hubIds.length} disabled=${!pending || busy}
                  onChange=${() => setHubIds([])}/></label>
            </div>
          </section>`}

          <!-- 4 LIGHT PULL FACTS -->
          ${isActor && html`<section class="review-section">
            <h3><span class="review-step">4</span>${SECTIONS.facts}</h3>
            <div class="review-toggle" role="group" aria-label=${SECTIONS.facts}>
              <button class=${"btn ghost " + (factView === "current" ? "active" : "")}
                onClick=${() => setFactView("current")}>${FACTS.current}</button>
              <button class=${"btn ghost " + (factView === "history" ? "active" : "")}
                onClick=${() => setFactView("history")}>${FACTS.history}</button>
            </div>
            ${showsTrl(draft.actor_category) && html`
              <p class="review-hint">${SENTENCES.trlStartupOnly}</p>`}
            ${showsRankings(draft.actor_category) && html`
              <p class="review-hint">${SENTENCES.rankingsUniversityOnly}</p>`}
            ${factView === "current" ? html`<div class="review-match"><table>
              <thead><tr>
                <th>${FIELDS.field}</th><th>${FIELDS.value}</th><th>${FIELDS.source}</th>
                <th>${FIELDS.dateRead}</th><th>${FIELDS.confidence}</th><th>${FIELDS.origin}</th>
              </tr></thead>
              <tbody>${factRows.map(row => html`<tr key=${row.key}>
                <th scope="row">${row.label}</th>
                <td>${row.state
                  ? html`<span class="review-missing">${row.state}</span>`
                  : formatFactValue(row.value)}</td>
                <td>${row.source
                  ? html`<a href=${row.source} target="_blank" rel="noreferrer">${row.source}</a>`
                  : html`<span class="review-missing">${row.metaState}</span>`}</td>
                <td>${row.dateRead
                  || html`<span class="review-missing">${row.metaState}</span>`}</td>
                <td>${row.confidence
                  || html`<span class="review-missing">${row.metaState}</span>`}</td>
                <td>${row.origin
                  || html`<span class="review-missing">${row.metaState}</span>`}</td>
              </tr>`)}</tbody>
            </table></div>` : html`<div class="review-match">
              ${!historyRows.length && html`<p class="muted">${SENTENCES.noFacts}</p>`}
              <table><thead><tr>
                <th>${FIELDS.field}</th><th>${FIELDS.value}</th><th>${FIELDS.dateRead}</th>
                <th>${FIELDS.confidence}</th><th>${FACTS.current}</th>
              </tr></thead>
              <tbody>${historyRows.map((row, index) => html`<tr key=${row.key + index}>
                <th scope="row">${row.label}</th>
                <td>${formatFactValue(row.value)}</td>
                <td>${row.dateRead || MISSING.notFound}</td>
                <td>${row.confidence || MISSING.notFound}</td>
                <td>${row.isCurrent ? FACTS.current : row.lifecycle || "Superseded"}</td>
              </tr>`)}</tbody></table>
            </div>`}
            <h4>${FIELDS.um6pOcpConnection}</h4>
            <p>${(() => {
              const link = selected.agent_metadata?.um6p_ocp_connection;
              if (!link) return MISSING.notYetChecked;
              if (link.found === false) return FACTS.notFoundInSources;
              return `${FACTS.found}: ${link.entity || MISSING.notFound}`;
            })()}</p>
            ${deepFacts.length > 0 && html`<details>
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
            ${selected.entity_type === "person" && html`
              <p class="review-hint">${SENTENCES.personDiscoveryDisabled}</p>`}
          </section>`}

          <!-- 5 POSSIBLE DUPLICATES -->
          ${matches.length > 0 && html`<section class="review-section">
            <h3><span class="review-step">5</span>${SECTIONS.duplicates}</h3>
            <p class="review-hint">${SENTENCES.duplicatesNoMerge}</p>
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
            <p class="review-hint">${SENTENCES.auditIntro}</p>
            <dl class="review-facts">
              <div><dt>${FIELDS.candidateId}</dt><dd>${selected.candidate_id}</dd></div>
              <div><dt>${FIELDS.runId}</dt><dd>${selected.source_run_id}</dd></div>
              <div><dt>${FIELDS.created}</dt><dd>${formatDate(selected.created_at)}</dd></div>
              <div><dt>${FIELDS.legacyActorType}</dt>
                <dd>${summary?.legacy_actor_type || MISSING.notProvided}</dd></div>
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
                  ${decisionOptions(selected.entity_type).map(option => html`
                    <option key=${option.value} value=${option.value}>${option.label}</option>`)}
                </select></label>
              ${decisionKind === "same_existing" && html`
                <label class="review-field"><span>Existing record</span>
                  <input value=${targetId} disabled=${!pending || busy}
                    onInput=${e => setTargetId(e.target.value)} placeholder="Existing record ID"/></label>`}
            </div>
            ${decisionKind === "reject" && html`<div class="review-field-grid">
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
                  onChange=${e => setProposeHub(e.target.checked)}/>
                <small class="review-hint">A new hub is only ever a proposal for GHUS.</small></label>`}
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
                  onInput=${e => setReviewer(e.target.value)}/>
                <small class="review-hint">${SENTENCES.reviewerRequired}</small></label>
              <label class="review-field"><span>${FIELDS.notes}</span>
                <input value=${notes} disabled=${!pending || busy}
                  onInput=${e => setNotes(e.target.value)}/></label>
            </div>
          </section>

          <footer class="review-footer">
            <button class="btn danger" disabled=${!pending || busy || writerDown}
              onClick=${() => { setDecisionKind("reject"); }}>${BUTTONS.reject}</button>
            <button class="btn ghost" disabled=${!pending || busy || writerDown}
              onClick=${() => { setDecisionKind("defer"); }}>${BUTTONS.park}</button>
            <button class="btn ghost" disabled=${!pending || busy || Object.keys(draftErrors).length > 0}
              onClick=${save}>${BUTTONS.saveEdits}</button>
            <button class="btn" onClick=${decide} disabled=${!canSubmitReview({
              candidate: selected, reviewer, rejectionReason, rejectionOther, decisionKind,
              targetId, busy, admissionConfigured: data.admission_configured, draftErrors,
            })}>${decisionKind === "reject" ? BUTTONS.reject
              : decisionKind === "defer" ? BUTTONS.park : BUTTONS.verify}</button>
          </footer>`}
        </article>
      </div>
    </section>`;
  };
}
