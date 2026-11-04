// Discovery: ask the agent to find organizations on a topic, in an area, for a
// period, at a frequency. Actor discovery runs only for requests made here.
//
// The page never writes anything itself. Every call goes through
// /api/discovery/*, which hands it to the GHUS backend's own command.

import {createDateInput, eventSpan, usDate} from "./dates.js?v=20261104e";

export const CADENCE_LABELS = {
  once: "Once",
  daily: "Every day",
  weekly: "Every week",
  biweekly: "Every two weeks",
  monthly: "Every month",
  quarterly: "Every three months",
};

/** Reasons saved before the word changed read the same as new ones: "actor" -> "organization". */
export function orgWords(text) {
  // The agents write "actor" and British "organisation"; the platform says "organization".
  return String(text ?? "").replace(/\b([Aa])ctor(s?)\b(?![_.])/g,
    (_, a, s) => `${a === "A" ? "O" : "o"}rganization${s}`)
    .replace(/\b([Oo])rganis(ation|ations|e|es|ed|ing|er|ers)\b/g, "$1rganiz$2");
}

export function formatUsd(value) {
  const number = Number(value);
  return value === null || value === undefined || Number.isNaN(number) ? "" : `$${number.toFixed(2)}`;
}

// What one relevant actor cost: the run's spend over what it kept (added
// plus sent to Review). A run that kept nothing says so instead of a number.
export function costPerRelevantActor(run) {
  if (run.spent_usd === null || run.spent_usd === undefined) return "";
  const kept = Number(run.staged_count || 0) + Number(run.review_item_count || 0);
  if (!kept) return Number(run.spent_usd) > 0 ? "None kept" : "";
  return formatUsd(Number(run.spent_usd) / kept);
}

export const DURATION_PRESETS = [
  {id: "1m", label: "1 month", months: 1},
  {id: "3m", label: "3 months", months: 3},
  {id: "6m", label: "6 months", months: 6},
  {id: "12m", label: "12 months", months: 12},
];

// ------------------------------------------------------------- the schedule
//
// Every new request - organizations, events, people - is scheduled the same
// way (GHUS, 2026-10-29): Frequency, Start Date, Duration, each chosen from a
// placeholder. Once has no duration; a recurring request needs one, and its
// monitoring period begins on the start date. A request that starts today runs
// as soon as it is created.

export const FREQUENCY_LABELS = {once: "Once", daily: "Daily", weekly: "Weekly", monthly: "Monthly"};
const FREQUENCIES = {
  actor: ["once", "daily", "weekly", "monthly"],
  event: ["once", "daily", "weekly", "monthly"],
  person: ["once", "weekly", "monthly"],
  // Organizations Update (GHUS, 2026-10-30): Once, Weekly, Monthly.
  update: ["once", "weekly", "monthly"],
};
const SCHEDULE_FIELDS = ["frequency", "start", "duration"];

/** The frequencies a form offers: its own, among those the database accepts. */
export function frequencyOptions(kind, offered = null) {
  return (FREQUENCIES[kind] || FREQUENCIES.actor).filter((c) => !offered || offered.includes(c));
}

/** The last day of the monitoring period: the start for Once, else start + duration. */
export function scheduleEnd(form) {
  if (form.cadence === "once") return form.startDate || "";
  const preset = DURATION_PRESETS.find((d) => d.id === form.duration);
  return preset && form.startDate ? addMonths(form.startDate, preset.months) : "";
}

export function scheduleProblems(form, today = null) {
  const problems = {};
  if (!form.cadence) problems.frequency = "Select how often to search.";
  if (!form.startDate) problems.start = "Select a start date.";
  else if (today && form.startDate < today) problems.start = "Choose today or a later date.";
  if (form.cadence && form.cadence !== "once"
      && !DURATION_PRESETS.some((d) => d.id === form.duration)) {
    problems.duration = "Select how long to keep searching.";
  }
  return problems;
}

/** Problems that stop a preview: everything but the schedule, which a preview does not need. */
export function previewProblems(problems) {
  return Object.fromEntries(Object.entries(problems).filter(([key]) => !SCHEDULE_FIELDS.includes(key)));
}

/** A preview searches nothing and saves nothing: without a schedule, it looks at today. */
export function previewSchedule(payload, today) {
  return payload.cadence && payload.start_date && payload.end_date ? payload
    : {...payload, cadence: "once", start_date: today, end_date: today};
}

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
export function isEmail(value) {
  return EMAIL.test(String(value || "").trim());
}

/** The requester's email on a payload, when it is one (they are told about findings). */
function withRequester(payload, email) {
  return isEmail(email) ? {...payload, requested_by: String(email).trim()} : payload;
}

export const STATUS_LABELS = {
  // Active and waiting for its next run; "Running" is said only while a run is.
  active: "Scheduled",
  running: "Running",
  stalled: "Stopped responding",
  paused: "Paused",
  expired: "Finished",
  period_over: "Period over",
  cancelled: "Cancelled",
};

export const RESULT_LABELS = {
  auto_high: "Added to the directory · verified by Compass",
  met_criteria: "Sent to Review Results · met every criterion",
  review: "Sent to Review Results",
};

// What happened to a kept organisation. Meeting every criterion verifies it only
// where GHUS switched automatic verification on; otherwise it went to Review.
export function resultOutcome(row) {
  if (row.score_band !== "auto_high") return "review";
  return row.verified_by_compass === true ? "auto_high" : "met_criteria";
}

// Why a candidate was not added. Every exclusion carries its recorded reason.
export const EXCLUSION_LABELS = {
  rejected: "Rejected",
  not_read: "Not read",
  superseded: "Re-read on its official site",
  failed: "Could not be read",
  capped: "Held back by the per-run limit",
};

export function exclusionKind(row) {
  if (row.score_band === "analysis_failed" || row.triage_verdict === "analysis_failed") return "failed";
  if (["not_read", "superseded", "capped"].includes(row.triage_verdict)) return row.triage_verdict;
  return "rejected";
}

export function exclusionSummary(rows) {
  const counts = {};
  for (const row of rows) counts[exclusionKind(row)] = (counts[exclusionKind(row)] || 0) + 1;
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([kind, n]) => `${n} ${EXCLUSION_LABELS[kind].toLowerCase()}`)
    .join(" · ");
}

// Relevance decides whether an organisation is kept; engagement priority only
// orders what is kept.
export function scoreLine(row) {
  const parts = [`Relevance ${Number(row.fit_score).toFixed(2)}`];
  if (row.priority != null) parts.push(`Engagement priority ${Number(row.priority).toFixed(2)}`);
  return parts.join(" · ");
}

const CATEGORY_LABELS = {
  university_academic: "University", research_center: "Research centre", company: "Company",
  government: "Government", innovation_platform: "Innovation platform", investor: "Investor",
  association_network: "Association / network", nonprofit: "Non-profit",
  hospital_clinical: "Hospital / clinical", national_laboratory: "National laboratory",
  applied_facility: "Applied facility",
};

// The facts a reviewer needs at a glance, only those the page actually stated.
/** An event's or person's facts on its request card: only what was found. */
export function entityResultFacts(row) {
  return [
    // An event runs from its start to its closing day.
    [row.end_date ? "Dates" : "Date", row.start_date ? eventSpan(row.start_date, row.end_date) : null],
    ["Type", row.event_type],
    ["Role", row.role],
    ["Organization", row.affiliation],
    ["Place", [row.city, row.state].filter(Boolean).join(", ") || null],
    ["Completeness", row.completeness
      ? row.completeness.charAt(0).toUpperCase() + row.completeness.slice(1) : null],
  ].filter(([, value]) => value);
}

export function resultFacts(row) {
  const place = [row.city, row.state, row.country && row.country !== "United States" ? row.country : null]
    .filter(Boolean).join(", ");
  return [
    ["Location", place],
    ["Type", CATEGORY_LABELS[row.category] || (row.category || "").replaceAll("_", " ")],
    ["Focus", row.focus],
    ["Current activity", row.activities],
    ["Funding", row.funding],
    ["Why it matched", row.why_matched],
  ].filter(([, value]) => value && String(value).trim());
}

const SOURCE_LABELS = {
  official_parent: "its parent organization's official site", government: "a government site",
  third_party: "another credible site",
};

/** Where a page came from, when it was not the organization's own website. */
export function sourceLabel(kind) {
  return SOURCE_LABELS[kind] || "";
}

/** Ask the page to show an actor's update profile in Review (index.html, review.js). */
export const OPEN_IN_REVIEW = "ghus:open-review";
/** The Dashboard opens a page at one item: {tab, map_id | request_id | view | record}. */
export const NAVIGATE = "ghus:navigate";

export function openInReview(actor) {
  window.dispatchEvent(new CustomEvent(OPEN_IN_REVIEW, {detail: {
    actor_id: actor.actor_id, name: actor.name}}));
}

/** "4 new · 1 updated · 7 not found": what one update wrote. */
export function writtenLine(counts = {}) {
  const words = [["new", "new"], ["changed", "updated"], ["additional", "more detail"],
    ["corroborated", "confirmed"], ["conflict", "to review"], ["protected", "GHUS value kept"],
    ["not_found", "not found"]];
  return words.filter(([key]) => counts[key]).map(([key, word]) => `${counts[key]} ${word}`)
    .join(" · ") || "nothing new";
}

export function isRunning(request) {
  return (request.runs || []).some((run) => run.status === "running" && !run.stalled);
}

/** The run in progress, if any (a run that stopped responding is not "running"). */
export function runningRun(request) {
  return (request.runs || []).find((run) => run.status === "running" && !run.stalled) || null;
}

/** "Running", "Stopped responding", "Period over", or the request's own status. */
export function requestStatus(request) {
  if (isRunning(request)) return "running";
  if ((request.runs || []).some((run) => run.status === "running" && run.stalled)) return "stalled";
  // Still active, but nothing more is scheduled: it runs only when asked.
  if (request.status === "active" && !request.next_run && request.skip_reason === "expired") {
    return "period_over";
  }
  return request.status;
}

/** The run button: "Run again" once it has run or its period is over. */
export function runButtonLabel(request) {
  return (request.runs || []).length > 0 || requestStatus(request) === "period_over"
    ? "Run again" : "Run now";
}

/** "45 s", "4 min", "1 h 12 min". */
export function durationLabel(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  if (s < 60) return `${s} s`;
  const minutes = Math.round(s / 60);
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

/** "Running for 4 min · $0.21 spent so far" - what a running run has taken. */
export function runningLine(run) {
  if (!run) return "";
  const spent = run.spent_usd === null || run.spent_usd === undefined ? null : Number(run.spent_usd);
  return `Running for ${durationLabel(run.elapsed_seconds)} · `
    + (spent ? `${formatUsd(spent)} spent so far` : "no spend recorded yet");
}

/** The Review run that holds a discovery run's results. */
export function reviewRunKey(run) {
  return run?.search_run_id ? `discovery:${run.search_run_id}` : null;
}

/** Open that run in Review, every record shown (index.html, review.js). */
export function openRunInReview(run, entity = "actor") {
  const key = reviewRunKey(run);
  if (!key) return;
  window.dispatchEvent(new CustomEvent(OPEN_IN_REVIEW, {detail: {
    run_key: key,
    run_type: {actor: "discovery_actors", event: "discovery_events",
      person: "discovery_people"}[entity] || "all"}}));
}

const RUN_STATUS = {succeeded: "Completed", attention: "Completed with limits", failed: "Failed",
  running: "Running"};

/** "4 updated · 2 confirmed · 2 not found": what a one-actor update found. */
export function updateCountsLine(counts = {}) {
  const words = [["new", "new"], ["changed", "updated"], ["additional", "more detail"],
    ["confirmed", "confirmed"], ["conflicts", "to review"], ["no_change", "unchanged"], ["missing", "not found"]];
  return words.filter(([key]) => counts[key]).map(([key, word]) => `${counts[key]} ${word}`)
    .join(" · ") || "Nothing new";
}

/**
 * Every actor update, saved request or one-time, as one list, newest first:
 * name, actors, when, status and what it found. Requests on an inactive (test)
 * sector are counted, not listed.
 */
export function updateRunList(listing = {}, sectors = []) {
  const rows = [];
  const sectorName = (code) => (sectors.find((x) => x.code === code) || {}).name || code;
  for (const r of listing.requests || []) {
    if (r.test_sector) continue;
    const last = (r.runs || [])[0];
    const names = r.actor_names || [];
    const live = r.status === "active" || r.status === "paused";
    const running = isRunning(r);
    rows.push({
      key: r.subscription_id, kind: "request", request: r,
      name: r.title || "Update request",
      actors: names.length
        ? (names.length <= 3 ? names.join(", ") : `${names.slice(0, 2).join(", ")} and ${names.length - 2} more`)
        : [(r.sector_codes || [])[0] && `Group: ${sectorName(r.sector_codes[0])}`, r.state_code]
          .filter(Boolean).join(" · ") || "A group",
      what: (ACTOR_UPDATE_SCOPES.find((x) => x.id === (r.update_options || {}).scope) || {}).label || "",
      date: last ? last.started_at : r.start_date,
      schedule: r.cadence === "once" ? "Once"
        : `${CADENCE_LABELS[r.cadence] || r.cadence} until ${formatDay(r.end_date)}`
          + (live && r.next_run ? ` · next ${formatDay(r.next_run)}` : ""),
      status: requestStatus(r),
      statusLabel: STATUS_LABELS[requestStatus(r)] || r.status,
      result: last ? `${last.found_count ?? 0} new or updated · ${last.review_item_count ?? 0} to Review Results`
        : "Not run yet",
      runs: r.runs || [],
    });
  }
  for (const u of listing.one_time || []) {
    rows.push({
      key: u.run_id, kind: "single", name: u.name, actors: u.name,
      what: (ACTOR_UPDATE_SCOPES.find((x) => x.id === u.scope) || {}).label || "",
      date: u.started_at, schedule: ["One-time update", u.topic_name].filter(Boolean).join(" · "),
      status: u.status === "failed" ? "failed" : "expired",
      statusLabel: RUN_STATUS[u.status] || u.status,
      result: updateCountsLine(u.counts), runs: [],
    });
  }
  return rows.sort((a, b) => String(b.date || "").localeCompare(String(a.date || "")));
}

const SKIP_LABELS = {
  not_due: null,
  not_started: "Starts later",
  paused: "Paused",
  expired: "Period over",
  cancelled: "Cancelled",
};

export function isoDate(date) {
  const d = date instanceof Date ? date : new Date(date);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function addMonths(isoStart, months) {
  const [y, m, d] = String(isoStart).split("-").map(Number);
  const target = new Date(y, m - 1 + months, 1);
  const lastDay = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate();
  target.setDate(Math.min(d, lastDay));
  // A 12-month request must fit the 365-day ceiling.
  const start = new Date(y, m - 1, d);
  const max = new Date(start.getTime() + 365 * 86400000);
  return isoDate(target > max ? max : target);
}

/** A day as MM/DD/YYYY; a timestamp is shown by the day it falls on here. */
export function formatDay(value) {
  if (!value) return "";
  const text = String(value);
  return usDate(/^\d{4}-\d{2}-\d{2}$/.test(text) ? text : new Date(text));
}

export function areaLabel(request, options) {
  if (request.city && request.state_code) return `${request.city}, ${request.state_code}`;
  if (request.state_code) {
    const state = (options?.states || []).find((s) => s.code === request.state_code);
    return state ? state.name : request.state_code;
  }
  if (request.region_code) {
    const region = (options?.regions || []).find((r) => r.code === request.region_code);
    // "in the Northeast", "in the Mountain West / Rocky Mountain".
    return `the ${region ? region.name : request.region_code}`;
  }
  return "the United States";
}

/** The sectors a request names. The backend calls these topics; a person
 * reading the page calls them sectors, and so does every label here. */
export const ANY_SECTOR = "ANY";

/** True when a request covers every sector ("Any sector", stored as all of them). */
export function coversEverySector(request, options) {
  const codes = (options?.topics || []).map((t) => t.code);
  const chosen = new Set(request.sector_codes || []);
  return chosen.has(ANY_SECTOR) || (codes.length > 1 && codes.every((c) => chosen.has(c)));
}

export function topicLabel(request, options) {
  if (coversEverySector(request, options)) return "any sector";
  const topics = options?.topics || [];
  const names = [
    ...(request.sector_codes || []).map((code) => topics.find((t) => t.code === code)?.name || code),
    ...(request.topic_ids || []).map((id) => topics.find((t) => t.topic_id === id)?.name || "Sector"),
  ];
  return names.join(", ") || "No sector";
}

// One sentence a person can check against what they meant.
export function requestSummary(request, options) {
  const cadence = (CADENCE_LABELS[request.cadence] || request.cadence || "").toLowerCase();
  const focus = (request.focus_terms || []).length
    ? ` focused on ${request.focus_terms.join(", ")}` : "";
  const when = request.cadence === "once"
    ? `Once, on ${formatDay(request.start_date) || "the start date"}`
    : `From ${formatDay(request.start_date)} to ${formatDay(request.end_date)}, ${cadence}`;
  const cap = request.max_new_actors_per_run
    ? ` At most ${request.max_new_actors_per_run} new organizations per run.` : "";
  const depth = (request.discovery_options || {}).pull_depth;
  const read = depth === "light" ? " Each organization kept is read on its own site."
    : depth === "none" ? " Organizations are not read beyond the search page." : "";
  return `${when}: find ${topicLabel(request, options)} organizations in ${areaLabel(request, options)}${focus}.${cap}${read}`;
}

export function nextRunLabel(request) {
  if (request.next_run) return formatDay(request.next_run);
  const skip = SKIP_LABELS[request.skip_reason];
  return skip || "No further runs";
}

// ---------------------------------------------------------------- the brief
//
// What the person types in their own words, turned into the fields the agent
// actually runs on. Nothing here is guessed quietly: every value this derives
// is shown back on the page, in the Details panel, where it can be changed.

/**
 * The sub-topics: every line AFTER the first, split further on commas,
 * semicolons or bullets.
 *
 * The first line names the request, so it is not a search term. It used to be
 * one, which meant the agent searched for the request's own name - and, worse,
 * demanded every word of it ("water organizations in Wisconsin") on the
 * organization's page before keeping it.
 */
export function briefTerms(text, limit = 8) {
  const terms = String(text || "")
    .split(/\n+/)
    .slice(1)
    .join("\n")
    .split(/[\n,;•]+/)
    .map((part) => part.replace(/^[\s\-*•\d.)]+/, "").trim())
    .filter(Boolean);
  return [...new Set(terms)].slice(0, limit);
}

/**
 * The word stems the agent will look for, exactly as actor_quality._stems
 * builds them: alphabetic words of four letters or more, cut to four.
 */
export function termStems(term) {
  return [...new Set((String(term || "").toLowerCase().match(/[a-z]{4,}/g) || [])
    .map((word) => word.slice(0, 4)))];
}

/** More stems than this in one term and the agent rarely matches it. */
const MAX_TERM_STEMS = 4;

/**
 * A term the agent is unlikely to match. Every one of its stems must appear on
 * the organization's own page for the term to count, so a whole sentence
 * almost never matches - and the actor is held for review as unconfirmed.
 */
export function termIsTooLong(term) {
  // No second parameter on purpose: `terms.some(termIsTooLong)` passes the
  // array index as the next argument, which read as the limit and flagged
  // every first term as too long.
  return termStems(term).length > MAX_TERM_STEMS;
}

/** The sector, region or state the brief names, by the catalog's own words. */
export function briefMatches(text, options = {}) {
  // Normalised, and matched on word boundaries: a name at the end of a line
  // or before a full stop counts, and "Cross-Thematic" is matched literally.
  const hay = ` ${String(text || "").toLowerCase().replace(/\s+/g, " ")} `;
  const escape = (value) => String(value).toLowerCase().replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const named = (value) =>
    Boolean(value) && new RegExp(`(^|[^a-z0-9])${escape(value)}([^a-z0-9]|$)`).test(hay);
  const byName = (rows, key = "name") => (rows || []).find((row) => named(row[key]));
  const sector = (options.topics || []).find((row) =>
    named(row.name) || new RegExp(`\\b${String(row.code).toLowerCase()}\\b`).test(hay));
  return {
    sector: sector ? sector.code : null,
    region: (byName(options.regions) || {}).code || null,
    state: (byName(options.states) || {}).code || null,
  };
}

/** The request's name: the brief's first line, which is what a person reads. */
export function briefTitle(text) {
  const first = String(text || "").split(/[\n.;]/)[0].trim();
  return first.slice(0, 160);
}

/**
 * The form the page would send: the typed fields win, and anything the person
 * has not set is taken from the brief.
 */
export function resolveDraft(form, options = {}) {
  const brief = String(form.brief || "").trim();
  if (!brief) return form;
  const found = briefMatches(brief, options);
  const resolved = {
    ...form,
    title: form.title.trim() || briefTitle(brief),
    sector: form.sector || found.sector || "",
    focusTerms: form.focusTerms.length
      ? form.focusTerms
      : briefTerms(brief, options.max_focus_terms || 8),
  };
  if (!form.areaTouched) {
    resolved.areaKind = found.state ? "state" : found.region ? "region" : "us";
    resolved.region = found.region || "";
    resolved.state = found.state || "";
  }
  return resolved;
}

// --------------------------------------------------------------- actor updates

/** The backend's scope words (actor_updates.SCOPES), for reading saved requests back. */
export const ACTOR_UPDATE_SCOPES = [
  {id: "general", label: "General Update"},
  {id: "topic", label: "Specific Changes"},
  {id: "missing", label: "Missing information"},
  {id: "outdated", label: "Outdated information"},
  {id: "specific", label: "Specific Changes"},
];

/** What to update: the page offers only these two. */
export const UPDATE_KINDS = [
  {id: "general", label: "General Update",
    hint: "Check the selected organizations for new, missing, or outdated information."},
  {id: "specific", label: "Specific Changes",
    hint: "Look for updates about a particular topic or type of information."},
];

/**
 * "What information are you interested in?" Each choice is a set of the
 * backend's change categories; only the boxes an organization's own category
 * has are ever read (the category Light Pull rules), so nothing irrelevant is
 * researched.
 */
export const INFORMATION_FOCUS = [
  {id: "research", label: "Research, Projects & Technology",
    words: "research, projects and technology", categories: ["research", "products"]},
  {id: "funding", label: "Funding & Partnerships",
    words: "funding and partnerships", categories: ["funding", "partnerships"]},
  {id: "organization", label: "Organization & Activities",
    words: "the organization and its activities", categories: ["organization", "category"]},
  {id: "locations", label: "Locations & Operations",
    words: "locations and operations", categories: ["geography"]},
];

export const UPDATE_QUESTION_EXAMPLE =
  "Has this organization launched any new battery storage projects or partnerships?";

/** How often a schedule checks. A one-time check is the separate Run Now. */
export const UPDATE_FREQUENCIES = [
  {id: "weekly", label: "Every Week", words: "every week", first: "next week", days: 7},
  {id: "biweekly", label: "Every 2 Weeks", words: "every two weeks", first: "in two weeks", days: 14},
  {id: "monthly", label: "Every Month", words: "every month", first: "next month", months: 1},
  {id: "quarterly", label: "Every 3 Months", words: "every three months", first: "in three months", months: 3},
];

export const UPDATE_DURATIONS = [
  {months: 1, label: "1 month", words: "one month"},
  {months: 3, label: "3 months", words: "three months"},
  {months: 6, label: "6 months", words: "six months"},
  {months: 12, label: "12 months", words: "twelve months"},
];

export function addDays(isoStart, days) {
  const [y, m, d] = String(isoStart).split("-").map(Number);
  return isoDate(new Date(y, m - 1, d + days));
}

/**
 * When a schedule runs: the first check comes one interval after today -
 * never on the day it is made - and checking stops `months` after today.
 */
export function updateSchedule(today, cadence, months) {
  const frequency = UPDATE_FREQUENCIES.find((f) => f.id === cadence) || UPDATE_FREQUENCIES[0];
  const duration = UPDATE_DURATIONS.find((d) => d.months === Number(months)) || UPDATE_DURATIONS[1];
  const start = frequency.days ? addDays(today, frequency.days) : addMonths(today, frequency.months);
  const end = addMonths(today, duration.months);
  const problem = start > end
    ? `Checking ${frequency.words} needs longer than ${duration.label}: the first check would come after it ends.`
    : "";
  return {start_date: start, end_date: end, problem};
}

/** The backend change categories behind the chosen information, in order. */
export function focusCategories(interests = []) {
  return [...new Set(INFORMATION_FOCUS.filter((x) => interests.includes(x.id))
    .flatMap((x) => x.categories))];
}

/** Why the choices cannot be sent yet, or "". */
export function updateChoiceProblem(form) {
  if (form.kind === "specific" && !(form.interests || []).length && !String(form.focus || "").trim()) {
    return "Choose the information you are interested in, or write a topic or question.";
  }
  return "";
}

/**
 * What the page sends to plan or check an update, in the backend's words.
 * General Update reads every box the organization's category has, so it finds
 * what is new, missing or out of date; the chosen information is read first
 * (the backend's change categories reorder, never add). Specific Changes reads
 * only the boxes of the chosen information (scope "specific"); with only a
 * question, every box, steered by the question's words.
 */
export function updateRequestBody(form) {
  const body = {scope: "general", depth: form.depth};
  if (form.topic) body.topic = form.topic;
  const categories = focusCategories(form.interests);
  if (form.kind !== "specific" && categories.length) body.categories = categories;
  if (form.kind === "specific") {
    if (categories.length) {
      body.scope = "specific";
      body.categories = categories;
    } else if (form.topic) {
      body.scope = "topic";
    }
    const focus = String(form.focus || "").trim();
    if (focus) body.focus = focus.slice(0, 200);
  }
  return body;
}

/**
 * What the page sends to plan or save an update request. One actor sends its
 * id; several send the picked ids, or the group (a sector is required: a
 * request never sweeps the whole map). Run Now is a one-time request that
 * starts today; a schedule starts one interval from today. The backend keeps
 * its own per-run and per-actor safeguards; a group's run reaches the actors
 * with the most gaps first.
 */
export function updateRequestDraft({mode, form, selected, picked = [], group = {}, useGroup,
  today, runNow = false}) {
  const draft = {...updateRequestBody(form)};
  if (mode === "one") {
    draft.actor_ids = selected ? [selected.actor_id] : [];
    draft.max_actors_per_run = 1;
  } else if (useGroup) {
    draft.group = Object.fromEntries(Object.entries({
      sector: group.sector, category: group.category, state: group.state,
    }).filter(([, v]) => v));
  } else {
    draft.actor_ids = picked.map((a) => a.actor_id);
    draft.max_actors_per_run = picked.length || 1;
  }
  if (runNow) {
    draft.cadence = "once";
  } else {
    const when = updateSchedule(today, form.cadence, form.months);
    Object.assign(draft, {cadence: form.cadence, start_date: when.start_date, end_date: when.end_date});
  }
  return draft;
}

/**
 * The request in one or two sentences: "Check these organizations every week
 * for three months, starting next week. Look for new research, projects and
 * technology, and funding and partnerships using Light Refresh."
 */
export function updateSummary({form, count = 0, runNow = false, deep = false}) {
  const who = count === 1 ? "this organization" : "these organizations";
  const frequency = UPDATE_FREQUENCIES.find((f) => f.id === form.cadence) || UPDATE_FREQUENCIES[0];
  const duration = UPDATE_DURATIONS.find((d) => d.months === Number(form.months)) || UPDATE_DURATIONS[1];
  const when = runNow ? `Check ${who} now, once.`
    : `Check ${who} ${frequency.words} for ${duration.words}, starting ${frequency.first}.`;
  const depth = deep ? "Light Refresh, then a Deep Pull" : "Light Refresh";
  const focus = String(form.focus || "").trim();
  const chosen = INFORMATION_FOCUS.filter((x) => (form.interests || []).includes(x.id)).map((x) => x.words);
  const list = chosen.length === 1 ? chosen[0]
    : `${chosen.slice(0, -1).join(", ")}${chosen.length > 2 ? "," : ""} and ${chosen[chosen.length - 1]}`;
  let what;
  if (form.kind !== "specific") {
    what = "Look for new, missing, or outdated information"
      + (chosen.length ? ` (${list} first)` : "");
  } else if (chosen.length) {
    what = `Look for updates on ${list}` + (focus ? `, with this question in mind: “${focus}”` : "");
  } else {
    what = focus ? `Look for updates about “${focus}”` : "Look for updates";
  }
  // After a quoted question, a comma keeps the sentence readable.
  return `${when} ${what}${what.endsWith("”") ? "," : ""} using ${depth}.`;
}

/** "About $0.04 a check; about $0.52 over 13 checks." Only from real past reads. */
export function estimateLine(cost, runs = 1) {
  if (!cost) return "";
  if (cost.expected_usd == null && cost.typical_usd == null) {
    return `No past checks to estimate from yet; each organization costs at most ${formatUsd(cost.per_actor_cap_usd ?? cost.cap_usd)} a check.`;
  }
  const each = cost.expected_usd ?? cost.typical_usd;
  return runs > 1 ? `About ${formatUsd(each)} a check; about ${formatUsd(each * runs)} over ${runs} checks.`
    : `About ${formatUsd(each)}.`;
}

/** "Specific Changes (Funding & Partnerships) · Water · Company · CA". Reads old requests too. */
export function updateRequestScope(request, sectors = []) {
  const options = request.update_options || {};
  const interests = INFORMATION_FOCUS.filter((x) => x.categories.some((c) => (options.categories || []).includes(c)))
    .map((x) => x.label);
  const scope = (ACTOR_UPDATE_SCOPES.find((s) => s.id === options.scope) || {}).label
    + (options.scope === "specific" && interests.length ? ` (${interests.join(", ")})` : "");
  const sectorName = (code) => (sectors.find((x) => x.code === code) || {}).name || code;
  const names = request.actor_names || [];
  const who = names.length
    ? (names.length <= 3 ? names.join(", ") : `${names.slice(0, 2).join(", ")} and ${names.length - 2} more`)
    : [(request.sector_codes || [])[0] && sectorName(request.sector_codes[0]),
      options.category && (CATEGORY_LABELS[options.category] || options.category), request.state_code]
      .filter(Boolean).join(" · ");
  return [scope, who, options.focus && `“${options.focus}”`].filter(Boolean).join(" · ");
}

// ---------------------------------------------------------- Organizations Update
// One page (GHUS, 2026-10-30): search the Ecosystem Directory, add organizations
// to one list, choose which to include, then what to update and when.

export const MONITOR_TITLE = "What would you like to monitor?";
export const MONITOR_LEAD = "Monitor topics and discover relevant organizations, people, and events "
  + "over time, or track updates to records already saved in Compass.";
export const SPECIFIC_PLACEHOLDER = "Describe the information you’d like to update, such as research "
  + "projects, technologies, funding, partnerships, leadership, facilities, or capabilities in "
  + "another sector. Include relevant topics, dates, or requirements. Name a sector (for example "
  + "Water or Energy Transition) to look for updates in that sector.";

/** The sector the update instructions name, if any: the update then looks in that sector. */
export function updateSector(focus, sectors = []) {
  const code = briefMatches(focus, {topics: sectors}).sector;
  return code ? sectors.find((s) => s.code === code) || null : null;
}
export const MAX_SPECIFIC_CHARS = 1000;

/** Add a directory record to the list, checked; never twice. */
export function addOrganization(list, actor) {
  if (!actor || list.some((row) => row.actor.actor_id === actor.actor_id)) return list;
  return [...list, {actor, checked: true}];
}

/** The header checkbox: "all", "some" or "none" of the list checked. */
export function selectionState(list) {
  const checked = list.filter((row) => row.checked).length;
  return !checked ? "none" : checked === list.length ? "all" : "some";
}

/** "2 organizations selected." */
export function selectionLine(list) {
  const n = list.filter((row) => row.checked).length;
  return `${n} ${n === 1 ? "organization" : "organizations"} selected.`;
}

/** "28 October 2026", or "Not recorded" when it was never checked successfully. */
export function lastCheckedLabel(value) {
  if (!value) return "Not recorded";
  const [y, m, d] = String(value).slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return "Not recorded";
  return new Date(y, m - 1, d).toLocaleDateString("en-GB", {day: "numeric", month: "long", year: "numeric"});
}

/** Verified or Parked, next to the organization's name. */
export function directoryStatus(actor) {
  const status = String(actor?.status || "").toLowerCase();
  return status === "verified" ? "Verified" : status === "parked" ? "Parked"
    : status === "imported" ? "Imported" : "";
}

/** Why Create Request is not ready yet: {organizations, frequency, start, duration}. */
export function orgUpdateProblems({list, form}, today = null) {
  const problems = {};
  if (!list.some((row) => row.checked)) problems.organizations = "Add an organization and check it.";
  return {...problems, ...scheduleProblems(form, today)};
}

/**
 * What Create Request sends: only the checked organizations, with one set of
 * instructions and one schedule for all of them. Instructions research that
 * scope; left blank, it is a general update of the full profile, the priority
 * areas first (GHUS, 2026-11-01).
 */
export function orgUpdatePayload({list, interests = [], focus = "", form, requester = "", sectors = []}) {
  const ids = list.filter((row) => row.checked).map((row) => row.actor.actor_id);
  const payload = {actor_ids: ids, max_actors_per_run: Math.max(ids.length, 1), depth: "light",
    cadence: form.cadence, start_date: form.startDate, end_date: scheduleEnd(form)};
  const instructions = String(focus || "").trim();
  if (instructions) {
    Object.assign(payload, {scope: "topic", focus: instructions.slice(0, MAX_SPECIFIC_CHARS)});
    // A sector named in the instructions wins over each organization's own (the backend's rule).
    const sector = updateSector(instructions, sectors);
    if (sector) payload.topic = sector.code;
  } else {
    payload.scope = "general";
    const categories = focusCategories(interests);
    if (categories.length) payload.categories = categories;
  }
  return withRequester(payload, requester);
}

/** Requests stay with whoever made them; those made before requesters were recorded stay shared. */
export function visibleRequests(requests = [], email = "") {
  const me = String(email || "").trim().toLowerCase();
  // No signed-in user yet: every request is shown (nobody types an email any more).
  if (!me) return requests;
  return requests.filter((r) => {
    const by = String(r.requested_by || "").trim().toLowerCase();
    return !by || !by.includes("@") || (me && by === me);
  });
}

const FIT_WORDS = {
  fits: "fits",
  outside_radius: "now outside its radius — kept, for a person to look at",
  sector_no_longer_matches: "sector no longer matches — kept, for a person to look at",
  location_unknown: "location unknown — kept",
};

/** Hub fit today: "In Bay Area Water Hub (fits) · Newly fits: Delta Hub (12 mi), to Review". */
export function hubSummary(hubs) {
  if (!hubs || hubs.ok === false) return "";
  const parts = [];
  if (hubs.memberships?.length) {
    parts.push("In " + hubs.memberships.map((m) => `${m.name} (${FIT_WORDS[m.fit] || m.fit}`
      + `${m.preserved ? ", GHUS membership" : ""})`).join(", "));
  }
  if (hubs.proposals?.length) {
    parts.push("Newly fits " + hubs.proposals.map((p) => `${p.name}`
      + (p.distance_miles != null ? ` (${p.distance_miles} mi)` : "")).join(", ")
      + " — proposed to Review Results when written, never assigned directly");
  }
  if (hubs.note) parts.push(hubs.note);
  return parts.join(" · ") || "In no hub.";
}

/** An actor with no Category Type: the type its own pages point to, for Review to confirm. */
export function typeProposalLine(proposal) {
  if (!proposal) return "";
  const type = proposal.category_type === "not_applicable" ? "Not Applicable" : proposal.type_label;
  return `Category Type: it had none; its pages point to ${type} — proposed to Review Results `
    + "when written, never set directly.";
}

const RELATED_STATUS = {
  on_map: "In the directory — the link goes to Review Results when written",
  ambiguous: "Several records match — nothing is written; a person decides",
  not_on_map: "Not in the directory",
};

/** One organisation the pages name: "Acme Water · funder · On the map — ...". */
export function relatedLine(item) {
  const relation = {partner: "partner", funder: "funder", funded_by_this: "funded by it",
    parent: "parent", unit: "a unit of it", body_this_is_member_of: "it is a member",
    member: "member", operator: "operator", investor: "investor"}[item.relation] || item.relation;
  return `${item.name} · ${relation} · ${RELATED_STATUS[item.status] || item.status}`;
}

/** One actor in a run: "CPower: 2 new · 1 changed · 1 to Review · $0.03". */
export function actorResultLine(result) {
  if (!result.ok) return `${result.name}: not updated — ${result.error || "no reason recorded"}`;
  const counts = result.counts || {};
  const parts = [["new", "new"], ["changed", "changed"], ["additional", "more detail"], ["corroborated", "confirmed"],
    ["not_found", "not found"]].filter(([k]) => counts[k]).map(([k, w]) => `${counts[k]} ${w}`);
  if (result.review_items) parts.push(`${result.review_items} to Review Results`);
  if (!parts.length) parts.push("nothing new");
  return `${result.name}: ${parts.join(" · ")} · ${formatUsd(result.spent_usd)}`;
}

/** One word per finding, the way the backend (actor_updates.classify) means it. */
export const OUTCOME_LABELS = {
  new: "New",
  changed: "Changed",
  additional: "More detail",
  corroborated: "Confirmed",
  conflict: "Conflict",
  protected: "GHUS value kept",
  unchanged: "No change",
  not_found: "Not found",
  not_yet_collected: "Not yet collected",
};

/** The result groups, most consequential first. */
export const RESULT_GROUPS = [
  {id: "new", label: "New"},
  {id: "changed", label: "Changed"},
  {id: "additional", label: "Additional details"},
  {id: "conflicts", label: "Conflicts requiring review"},
  {id: "confirmed", label: "Confirmed"},
  {id: "missing", label: "Missing"},
  {id: "no_change", label: "No change"},
];

/** "Usually $0.031 (12 past reads, $0.020–$0.052); never more than $0.15." */
export function costLine(cost) {
  if (!cost) return "";
  const cap = `never more than ${formatUsd(cost.cap_usd)}`;
  if (cost.typical_usd === null || cost.typical_usd === undefined) {
    return `No update has run yet, so there is no history; ${cap}.`;
  }
  return `Usually ${formatUsd(cost.typical_usd)} (${cost.runs} past ${cost.runs === 1 ? "read" : "reads"}, `
    + `${formatUsd(cost.low_usd)}–${formatUsd(cost.high_usd)}); ${cap}.`;
}

export function findingsIn(findings, group) {
  return (findings || []).filter((f) => !group || group === "all" || f.group === group);
}

const BOX_LABELS = {
  funding_signal: "Funding",
  recent_activity: "Recent activity",
  international_connection: "International links",
  um6p_ocp_connection: "UM6P / OCP link",
  why_matched: "Why it matters",
  location: "Location",
};

export function boxLabel(field) {
  const known = BOX_LABELS[field];
  if (known) return known;
  const words = String(field || "").replaceAll("_", " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** A recorded value in one readable line: "Aug 12, 2026 — Opened ...". */
export function factLine(value) {
  if (value === null || value === undefined || value === "") return "";
  let v = value;
  if (typeof v === "string") {
    try { v = JSON.parse(v); } catch { return v; }
  }
  if (v && typeof v === "object" && !Array.isArray(v)) {
    if (v.date && v.description) return `${usDate(v.date)} — ${v.description}`;
    if (v.reason) return v.reason;
    // Flags (is_multi_location: false) are not something to read out.
    const text = Object.entries(v).filter(([key, x]) => key !== "carried_over"
      && x !== null && x !== "" && typeof x !== "boolean").map(([, x]) => factLine(x)).join(" · ");
    const carried = Array.isArray(v.carried_over) ? v.carried_over : [];
    return text + (carried.length ? ` (kept from earlier reading: ${carried.map(boxLabel).join(", ")})` : "");
  }
  if (Array.isArray(v)) return v.map(factLine).join("; ");
  return String(v);
}

/** The query string for an actor search: words typed plus the chosen group. */
export function actorSearchParams(query, group = {}) {
  const params = new URLSearchParams();
  if (String(query || "").trim()) params.set("q", String(query).trim());
  if (group.sector) params.set("sector", group.sector);
  if (group.category) params.set("category", group.category);
  if (group.state) params.set("state", group.state);
  if (group.everyone) params.set("everyone", "true");
  return params.toString();
}

/**
 * A name split around what was typed, for highlighting a suggestion:
 * "CPower Energy" + "pow" -> [{"C"}, {"Pow", match}, {"er Energy"}].
 * Case-insensitive; every occurrence; plain text in, plain text out.
 */
export function highlightParts(text, query) {
  const source = String(text || "");
  const needle = String(query || "").trim();
  if (!needle) return [{text: source, match: false}];
  const parts = [];
  const lower = source.toLowerCase();
  const target = needle.toLowerCase();
  let at = 0;
  for (let hit = lower.indexOf(target); hit !== -1; hit = lower.indexOf(target, at)) {
    if (hit > at) parts.push({text: source.slice(at, hit), match: false});
    parts.push({text: source.slice(hit, hit + needle.length), match: true});
    at = hit + needle.length;
  }
  if (at < source.length) parts.push({text: source.slice(at), match: false});
  return parts.length ? parts : [{text: source, match: false}];
}

/** "17 actors · Water · Research centre · showing 12" - what the list is drawn from. */
export function groupCaption(total, shown, group = {}, sectors = [], states = []) {
  const sector = group.sector && ((sectors.find((s) => s.code === group.sector) || {}).name || group.sector);
  const type = group.category && (CATEGORY_LABELS[group.category] || group.category);
  const state = group.state && ((states.find((s) => s.code === group.state) || {}).name || group.state);
  return [`${total} ${total === 1 ? "organization" : "organizations"}`, sector, type, state,
    shown < total ? `showing ${shown}` : null].filter(Boolean).join(" · ");
}

/**
 * Sectors, types and states whose name contains what was typed: picking one
 * narrows the directory to that group, as a filter would. Chosen ones are left out.
 */
export function groupSuggestions(query, sectors = [], states = [], chosen = {}, limit = 6) {
  const q = String(query || "").trim().toLowerCase();
  if (q.length < 2) return [];
  const all = [
    ...sectors.map((s) => ({key: "sector", kind: "Sector", code: s.code, label: s.name})),
    ...Object.entries(CATEGORY_LABELS).map(([code, label]) => ({key: "category", kind: "Type", code, label})),
    ...states.map((s) => ({key: "state", kind: "State", code: s.code, label: s.name})),
  ];
  return all.filter((g) => chosen[g.key] !== g.code && String(g.label || "").toLowerCase().includes(q))
    .sort((a, b) => Number(!a.label.toLowerCase().startsWith(q)) - Number(!b.label.toLowerCase().startsWith(q)))
    .slice(0, limit);
}

/** "1 new · 2 changed · 1 conflicts requiring review", most consequential first. */
export function outcomeSummary(counts = {}) {
  return RESULT_GROUPS.filter((g) => counts[g.id])
    .map((g) => `${counts[g.id]} ${g.label.toLowerCase()}`)
    .join(" · ");
}

// What the form sends. Empty optional fields are left out, never sent blank.
export const PULL_DEPTH_LABELS = {
  light: "Read each organization's own pages (recommended)",
  none: "Search page only: do not read the organizations' sites",
};

export function draftPayload(form) {
  const payload = {
    title: form.title.trim(),
    sector_codes: form.sector ? [form.sector] : [],
    focus_terms: form.focusTerms,
    start_date: form.startDate,
    end_date: scheduleEnd(form),
    cadence: form.cadence,
    max_new_actors_per_run: Number(form.cap),
    // New requests read what they keep (Light Pull) unless a person opts out.
    discovery_options: {pull_depth: form.pullDepth || "light"},
  };
  if (form.areaKind === "region" && form.region) payload.region_code = form.region;
  if (form.areaKind === "state" && form.state) {
    payload.state_code = form.state;
    if (form.city.trim()) payload.city = form.city.trim();
  }
  return payload;
}

export function draftProblems(rawForm, options) {
  const form = resolveDraft(rawForm, options);
  const problems = {};
  if (!form.title.trim()) {
    problems.brief = "Say what you are looking for.";
    problems.title = "Give the request a name.";
  }
  if (form.sector === ANY_SECTOR && !form.focusTerms.length) {
    problems.sector = "All sectors needs a sub-topic to search for.";
    problems.brief = "With all sectors, add at least one line naming what to search for.";
  }
  if (!form.sector) {
    problems.sector = "Choose a sector.";
    if (String(rawForm.brief || "").trim()) {
      // The brief named no sector the catalog knows, so the agent has no part
      // of the map to grow. Said here rather than only in the hidden panel.
      problems.brief = "Name one of the sectors below, or choose one in Details.";
    }
  }
  if (form.areaKind === "region" && !form.region) problems.area = "Choose a region.";
  if (form.areaKind === "state" && !form.state) problems.area = "Choose a state.";
  const cap = Number(form.cap);
  const maxCap = options?.max_new_actors_per_run || 50;
  if (!Number.isInteger(cap) || cap < 1 || cap > maxCap) problems.cap = `Between 1 and ${maxCap}.`;
  return {...problems, ...scheduleProblems(form)};
}

// ------------------------------------------------------- events and people
//
// The same request, for events or people (backend migration 580). The
// organization form above is untouched; these forms ask only what an event or
// people search needs, and use the same request storage, scheduler and Review.

export const DISCOVERY_KINDS = [
  {id: "actor", label: "Organizations"},
  {id: "person", label: "People"},
  {id: "event", label: "Events"},
];

export const EVENT_TYPE_LABELS = {
  conference: "Conference", summit: "Summit", symposium: "Symposium", forum: "Forum",
  training: "Training",
  // No longer offered; still named on requests saved with them.
  workshop: "Workshop", expo: "Expo", webinar: "Webinar", hackathon: "Hackathon",
};

export function blankEntityForm(today, kind) {
  return {
    kind, brief: "", title: "", sector: "", focusTerms: [], focusInput: "",
    areaKind: "us", region: "", state: "", city: "",
    dateFrom: "", dateTo: "", eventTypes: [], institution: "", role: "",
    // Chosen, never assumed: each starts on its placeholder.
    startDate: "", cadence: "", duration: "",
  };
}

/**
 * An events request from its description: the first line names it, the lines
 * after it are what to search for (the first line itself when there are none);
 * a sector, region or state the description names is used unless one is chosen.
 */
export function resolveEventDraft(form, options = {}) {
  const brief = String(form.brief || "").trim();
  if (!brief) return form;
  const found = briefMatches(brief, options);
  const terms = briefTerms(brief, options.max_focus_terms || 8);
  const resolved = {...form, title: briefTitle(brief),
    sector: form.sector || found.sector || ANY_SECTOR,
    focusTerms: terms.length ? terms : [briefTitle(brief)]};
  if (!form.areaTouched) {
    resolved.areaKind = found.state ? "state" : found.region ? "region" : "us";
    resolved.region = found.region || "";
    resolved.state = found.state || "";
  }
  return resolved;
}

/** The payload with its date range: upcoming events for EVENT_WINDOW_MONTHS when none is chosen. */
export function withEventWindow(payload) {
  const options = payload.discovery_options || {};
  if (payload.discovery_entity !== "event" || options.date_from || options.date_to
      || !payload.start_date) return payload;
  return {...payload, discovery_options: {...options, date_from: payload.start_date,
    date_to: addMonthsIso(payload.start_date, EVENT_WINDOW_MONTHS)}};
}

function addMonthsIso(iso, months) {
  const [y, m, d] = String(iso).split("-").map(Number);
  const last = new Date(Date.UTC(y, m - 1 + months + 1, 0)).getUTCDate();
  return new Date(Date.UTC(y, m - 1 + months, Math.min(d, last))).toISOString().slice(0, 10);
}

/** What an event or people form sends. Empty optional fields are left out. */
export function entityDraftPayload(form) {
  const options = {};
  if (form.kind === "event") {
    if (form.dateFrom) options.date_from = form.dateFrom;
    if (form.dateTo) options.date_to = form.dateTo;
    if (form.eventTypes.length) options.event_types = form.eventTypes;
  } else {
    if (form.institution.trim()) options.institution = form.institution.trim();
    if (form.role.trim()) options.role = form.role.trim();
  }
  const payload = {
    title: form.title.trim(),
    sector_codes: form.sector ? [form.sector] : [],
    focus_terms: form.focusTerms,
    start_date: form.startDate,
    end_date: scheduleEnd(form),
    cadence: form.cadence,
    discovery_entity: form.kind,
    discovery_options: options,
  };
  if (form.areaKind === "region" && form.region) payload.region_code = form.region;
  if (form.areaKind === "state" && form.state) {
    payload.state_code = form.state;
    if (form.city.trim()) payload.city = form.city.trim();
  }
  return payload;
}

export function entityDraftProblems(form, options = {}) {
  const problems = {};
  if (!form.title.trim()) problems.title = "Give the request a name.";
  if (!form.sector) problems.sector = "Choose a sector.";
  if (!form.focusTerms.length && !String(form.focusInput || "").trim()) {
    problems.topic = form.kind === "event" ? "Name the topic to search for."
      : "Name the topic or expertise to search for.";
  }
  if (form.areaKind === "region" && !form.region) problems.area = "Choose a region.";
  if (form.areaKind === "state" && !form.state) problems.area = "Choose a state.";
  if (form.kind === "event") {
    if (form.dateFrom && form.dateTo && form.dateTo < form.dateFrom) {
      problems.dates = "The range ends before it starts.";
    }
    if (form.eventTypes.length > (options.max_event_types || 5)) {
      problems.types = `Choose at most ${options.max_event_types || 5}.`;
    }
  }
  return {...problems, ...scheduleProblems(form)};
}

// People (GHUS, 2026-10-29): one question answered in the person's own words;
// the backend reads it into search themes, a role and a name
// (agents/collection/people_brief.py) and keeps the whole description.
export const ORG_QUESTION = "Which organizations would you like to monitor?";
export const ORG_PLACEHOLDER = "Describe the types of organizations you want to monitor. Include your "
  + "objective, sector or topic, geographic focus, and any specific capabilities of interest.";
export const EVENT_QUESTION = "Which events would you like to monitor?";
export const EVENT_PLACEHOLDER = "Describe the events you want to monitor. Include your objective, "
  + "sector or topic, geographic focus, and any specific themes of interest.";
export const REVIEW_NOTE = "Review findings and check their sources before you verify them and add "
  + "them to the Ecosystem Directory.";
// Events with no date range chosen: upcoming ones, from the request's start.
export const EVENT_WINDOW_MONTHS = 14;
export const PEOPLE_QUESTION = "Who would you like to find?";
export const PEOPLE_PLACEHOLDER = "Describe the expertise and professional profiles you’re looking "
  + "for. Include your objective, sector or topic, geographic focus, and any relevant affiliations "
  + "or experience.";

export function blankPeopleForm() {
  return {brief: "", sector: ANY_SECTOR, region: "", state: "", startDate: "", cadence: "", duration: ""};
}

/** The states a region holds; every state when no region is chosen. */
export function statesForRegion(options, region) {
  const states = options?.states || [];
  const chosen = (options?.regions || []).find((r) => r.code === region);
  return chosen ? states.filter((s) => (chosen.states || []).includes(s.code)) : states;
}

export function peopleDraftPayload(form) {
  const payload = {
    title: "",
    sector_codes: [form.sector || ANY_SECTOR],
    focus_terms: [],
    start_date: form.startDate,
    end_date: scheduleEnd(form),
    cadence: form.cadence,
    discovery_entity: "person",
    discovery_options: {brief: String(form.brief || "").trim()},
  };
  // A state is the narrower choice; the backend takes one or the other.
  if (form.state) payload.state_code = form.state;
  else if (form.region) payload.region_code = form.region;
  return payload;
}

export function peopleDraftProblems(form, today = null) {
  const problems = {};
  if (String(form.brief || "").trim().length < 10) {
    problems.brief = "Describe who you would like to find in a sentence or two.";
  }
  return {...problems, ...scheduleProblems(form, today)};
}

/** One sentence a person can check against what they meant. */
export function entitySummary(request, options) {
  const kind = request.discovery_entity || request.kind;
  const opts = request.discovery_options || {
    date_from: request.dateFrom, date_to: request.dateTo, event_types: request.eventTypes,
    institution: request.institution, role: request.role,
  };
  const cadence = (CADENCE_LABELS[request.cadence] || request.cadence || "").toLowerCase();
  const when = request.cadence === "once"
    ? `Once, on ${formatDay(request.start_date) || "the start date"}`
    : `From ${formatDay(request.start_date)} to ${formatDay(request.end_date)}, ${cadence}`;
  const topic = (request.focus_terms || []).length ? request.focus_terms.join(", ")
    : topicLabel(request, options);
  if (kind === "event") {
    const types = (opts.event_types || []).map((t) => (EVENT_TYPE_LABELS[t] || t).toLowerCase());
    const range = opts.date_from || opts.date_to
      ? ` taking place ${opts.date_from ? `from ${formatDay(opts.date_from)}` : ""}${
        opts.date_from && opts.date_to ? " " : ""}${opts.date_to ? `to ${formatDay(opts.date_to)}` : ""}`
      : "";
    return `${when}: find ${types.length ? types.join(" or ") + "s" : "events"} on ${topic} in ${
      areaLabel(request, options)}${range}.`;
  }
  const role = opts.role ? `${opts.role}s` : "people";
  const at = opts.institution ? ` at ${opts.institution}` : ` in ${areaLabel(request, options)}`;
  return `${when}: find ${role} working on ${topic}${at}.`;
}

// ------------------------------------------------- the Requests list (27 Oct mockup)
export const REQUEST_TYPES = {find: "Find New Records", update: "Update Existing Records"};

/** One row per request: monitoring requests find new records, update requests
 * refresh records already in the directory. Newest first. */
export function requestRows(requests = [], updates = []) {
  const noun = {actor: "Organizations", event: "Events", person: "People"};
  const row = (r, type) => ({
    key: `${type}:${r.subscription_id}`, type, request: r,
    title: r.title || (type === "update" ? "Update request" : "Untitled request"),
    recordType: type === "update" ? "Organizations" : noun[r.discovery_entity || "actor"],
    status: requestStatus(r),
  });
  return [...requests.map((r) => row(r, "find")), ...updates.filter((r) => !r.test_sector).map((r) => row(r, "update"))]
    .sort((a, b) => String(b.request.created_at || "").localeCompare(String(a.request.created_at || "")));
}

/** "Once", "3 months", "2 weeks" - the span from start to end date. */
export function requestDuration(request) {
  if (request.cadence === "once") return "Once";
  const start = Date.parse(request.start_date), end = Date.parse(request.end_date);
  if (!start || !end || end < start) return "Not recorded";
  const days = Math.round((end - start) / 86400000);
  if (days < 28) return days < 14 ? `${days} days` : `${Math.round(days / 7)} weeks`;
  const months = Math.round(days / 30.44);
  return months === 1 ? "1 month" : `${months} months`;
}

/** What a run produced: records added plus records sent to Review Results. */
export function runFindings(run) {
  if (run.actor_results) return run.found_count ?? 0;
  return (run.staged_count ?? 0) + (run.review_item_count ?? 0);
}

function blankForm() {
  return {
    brief: "", areaTouched: false,
    title: "", sector: "", focusTerms: [], focusInput: "",
    areaKind: "region", region: "", state: "", city: "",
    startDate: "", duration: "", cadence: "", cap: 10, pullDepth: "light",
  };
}

/**
 * The form a Build the Map hand-off opens with: the proposed brief, monthly.
 * Unless the brief was edited, the sector and area the map resolved are set
 * explicitly, so a sub-topic that happens to name another sector or a place
 * cannot change them.
 */
export function handoffForm(handoff, today) {
  const form = {...blankForm(), brief: handoff.brief || "", cadence: "monthly", startDate: today,
    duration: "3m"};
  if (handoff.edited) return form;
  form.sector = handoff.sector_code || "";
  form.areaTouched = true;
  form.areaKind = handoff.state_code ? "state" : handoff.region_code ? "region" : "us";
  form.state = handoff.state_code || "";
  form.region = handoff.region_code || "";
  return form;
}

// Sent to the signed-in user's own email: there is no address to type.
export const EMAIL_NOTE = "You’ll receive an email notification when your results are ready to "
  + "review in Review Results.";

export function createDiscoveryPage({html, useState, useEffect, useRef = () => ({current: null})}) {
  // Dates are typed and shown as MM/DD/YYYY whatever the computer's language.
  const DateInput = createDateInput({html, useState, useEffect});
  async function api(path, options = {}) {
    const response = await fetch(path, {
      headers: {"Content-Type": "application/json"}, ...options,
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(orgWords(body.detail) || `Request failed (${response.status})`);
    return body;
  }

  function Field({label, error, children, wide}) {
    // A div, not a label: a label forwards clicks on its text to the first
    // button inside it, which would flip the segmented controls.
    return html`<div role="group" aria-label=${label} class=${"discovery-field" + (wide ? " wide" : "") + (error ? " invalid" : "")}>
      <span class="discovery-label">${label}</span>${children}
      ${error && html`<small class="field-error">${error}</small>`}
    </div>`;
  }

  /** Frequency · Start Date · Duration, in one row; Duration only for a recurring request. */
  /** Where the results are emailed: typed once here, kept in this browser (no sign-in yet). */
  function EmailNote() {
    return html`<p class="discovery-email-note"><svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M12 11v6M12 7.5v.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
      <span>${EMAIL_NOTE}</span></p>`;
  }

  function RequestFooter({requester, setRequester, working, disabled, onCreate, note = ""}) {
    return html`<div class="org-footer">
      <div class="org-notes">
        ${note && html`<p class="discovery-email-note"><svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M12 11v6M12 7.5v.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg><span>${note}</span></p>`}
        <${EmailNote} requester=${requester} setRequester=${setRequester}/>
      </div>
      <button type="button" class="btn org-create" disabled=${disabled} onClick=${onCreate}>
        ${working ? "Creating…" : "Create Request"}</button>
    </div>`;
  }

  function ScheduleRow({form, set, kind, options, today, shown}) {
    return html`<div class="discovery-row3">
      <${Field} label="Frequency" error=${shown.frequency}>
        <select value=${form.cadence} onChange=${(e) => set({cadence: e.target.value})}>
          <option value="" disabled>Select frequency…</option>
          ${frequencyOptions(kind, options.cadences).map((c) => html`<option key=${c} value=${c}>${FREQUENCY_LABELS[c]}</option>`)}
        </select>
      <//>
      <${Field} label="Start Date" error=${shown.start}>
        <${DateInput} ariaLabel="Start Date" placeholder="Select a date…" value=${form.startDate}
          min=${today} onChange=${(v) => set({startDate: v})}/>
      <//>
      ${form.cadence !== "once" && html`<${Field} label="Duration" error=${shown.duration}>
        <select value=${form.duration} onChange=${(e) => set({duration: e.target.value})}>
          <option value="" disabled>Select duration…</option>
          ${DURATION_PRESETS.map((d) => html`<option key=${d.id} value=${d.id}>${d.label}</option>`)}
        </select>
      <//>`}
    </div>`;
  }

  /**
   * Save a request; when it starts today, start its first run now - for Once
   * that is the run, for a recurring request the first of its period.
   */
  async function createRequest(payload, today) {
    const created = await api("/api/discovery/requests", {method: "POST", body: JSON.stringify(payload)});
    const started = payload.start_date === today;
    if (started) await api(`/api/discovery/requests/${created.subscription_id}/run`, {method: "POST"});
    return {created, started};
  }

  function createdMessage({created, started}, payload) {
    const title = payload.title || created?.request?.title || "Your request";
    const email = payload.requested_by ? ` ${payload.requested_by} gets an email when findings are ready.` : "";
    return started
      ? `“${title}” is created and running now. Its findings go to Review Results for you to verify.${email}`
      : `“${title}” is created. Its first run is on ${formatDay(payload.start_date)}; findings go to Review Results.${email}`;
  }

  function PeopleRequestForm({options, today, requester, setRequester, onSaved}) {
    const [form, setForm] = useState(blankPeopleForm);
    const [touched, setTouched] = useState(false);
    const [working, setWorking] = useState("");
    const [message, setMessage] = useState(null);
    const set = (patch) => setForm((f) => ({...f, ...patch}));
    const problems = peopleDraftProblems(form, today);
    const shown = touched ? problems : {};
    const ready = options.entity_requests_ready !== false;
    const states = statesForRegion(options, form.region);

    async function create() {
      setTouched(true);
      if (Object.keys(problems).length) return;
      setWorking("create"); setMessage(null);
      try {
        const payload = withRequester(peopleDraftPayload(form), requester);
        const result = await createRequest(payload, today);
        setMessage({kind: "success", text: createdMessage(result, payload)});
        setForm(blankPeopleForm()); setTouched(false);
        onSaved(result.started);
      } catch (err) { setMessage({kind: "error", text: err.message}); }
      setWorking("");
    }

    return html`<section class="discovery-card">
      ${!ready && html`<p class="discovery-message error">People requests need migration 580 on this database.</p>`}
      ${message && html`<p class=${"discovery-message " + message.kind}>${message.text}</p>`}
      <${Field} label=${PEOPLE_QUESTION} error=${shown.brief} wide=${true}>
        <textarea class="discovery-brief" rows="5" maxLength="2000" value=${form.brief}
          placeholder=${PEOPLE_PLACEHOLDER} onInput=${(e) => set({brief: e.target.value})}></textarea>
      <//>
      <div class="discovery-row3">
        <${Field} label="Sector">
          <select value=${form.sector} onChange=${(e) => set({sector: e.target.value})}>
            <option value=${ANY_SECTOR}>All</option>
            ${options.topics.map((s) => html`<option key=${s.code} value=${s.code}>${s.name}</option>`)}
          </select>
        <//>
        <${Field} label="Region">
          <select value=${form.region} onChange=${(e) => {
            const region = e.target.value;
            const keep = statesForRegion(options, region).some((s) => s.code === form.state);
            set({region, state: keep ? form.state : ""});
          }}>
            <option value="">All Regions</option>
            ${options.regions.map((r) => html`<option key=${r.code} value=${r.code}>${r.name}</option>`)}
          </select>
        <//>
        <${Field} label="State">
          <select value=${form.state} onChange=${(e) => set({state: e.target.value})}>
            <option value="">All States</option>
            ${states.map((s) => html`<option key=${s.code} value=${s.code}>${s.name}</option>`)}
          </select>
        <//>
      </div>
      <${ScheduleRow} form=${form} set=${set} kind="person" options=${options} today=${today} shown=${shown}/>
      <${RequestFooter} requester=${requester} setRequester=${setRequester} working=${working === "create"}
        disabled=${!!working || !ready} onCreate=${create}/>
    </section>`;
  }

  /** A recurring request's end date: Save appears once it changes; the old schedule holds until then. */
  function EndDate({request, today, onSaved}) {
    const [value, setValue] = useState(request.end_date || "");
    const [state, setState] = useState({saving: false, ok: "", error: ""});
    // What was just saved: Save hides at once, before the list reloads.
    const [saved, setSaved] = useState(null);
    useEffect(() => { setValue(request.end_date || ""); setSaved(null); }, [request.end_date]);
    const editable = (request.status === "active" || request.status === "paused") && request.cadence !== "once";
    if (!editable) {
      return html`<div class="discovery-enddate"><span class="discovery-label">End date</span>
        <span>${formatDay(request.end_date)}</span></div>`;
    }
    const changed = Boolean(value) && value !== (saved || request.end_date);
    const earliest = request.start_date > today ? request.start_date : today;
    async function saveEnd() {
      setState({saving: true, ok: "", error: ""});
      try {
        await api(`/api/discovery/requests/${request.subscription_id}/end-date`,
          {method: "POST", body: JSON.stringify({end_date: value})});
        setSaved(value);
        setState({saving: false, ok: `Saved. The request now ends on ${formatDay(value)}.`, error: ""});
        setTimeout(() => setState((s) => ({...s, ok: ""})), 4000);
        onSaved();
      } catch (err) {
        // The edit stays, so it can be corrected or tried again.
        setState({saving: false, ok: "", error: err.message});
      }
    }
    return html`<div class="discovery-enddate">
      <span class="discovery-label">End date</span>
      <${DateInput} ariaLabel="End date" value=${value} min=${earliest}
        max=${addMonths(request.start_date, 12)} onChange=${(v) => { setValue(v); setState({saving: false, ok: "", error: ""}); }}/>
      ${changed && html`<button class="btn" disabled=${state.saving} onClick=${saveEnd}>${state.saving ? "Saving…" : "Save"}</button>`}
      ${state.ok && html`<small class="discovery-saved" role="status">${state.ok}</small>`}
      ${state.error && html`<small class="field-error" role="alert">${state.error}</small>`}
    </div>`;
  }

  function OrganizationsUpdate({sectors, options, today, requester, setRequester, onCreated}) {
    const [query, setQuery] = useState("");
    // Narrow the directory by a sector, type or state picked from the suggestions; with one
    // chosen, the group is listed.
    const [group, setGroup] = useState({sector: "", category: "", state: ""});
    const [results, setResults] = useState([]);
    const [total, setTotal] = useState(0);
    const [searching, setSearching] = useState(false);
    const [searched, setSearched] = useState(false);
    const [active, setActive] = useState(0);
    const [list, setList] = useState([]);
    const [focus, setFocus] = useState("");
    const [form, setForm] = useState({cadence: "", startDate: "", duration: ""});
    const [touched, setTouched] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const headerBox = useRef(null);
    const allSectors = sectors || [];
    const sectorName = (code) => (allSectors.find((x) => x.code === code) || {}).name || code;

    // Matching directory records, by the words typed and/or the filters. Last answer wins.
    const grouped = Boolean(group.sector || group.category || group.state);
    useEffect(() => {
      const q = query.trim();
      if (q.length < 2 && !grouped) {
        setResults([]); setTotal(0); setSearching(false); setSearched(false);
        return undefined;
      }
      let live = true;
      setSearching(true);
      const timer = setTimeout(async () => {
        try {
          const body = await api(`/api/discovery/actors?${actorSearchParams(q, group)}&limit=50`);
          if (live) {
            setResults(body.actors || []); setTotal(body.total || 0); setActive(0);
            setSearched(true); setError("");
          }
        } catch (err) { if (live) setError(err.message); }
        if (live) setSearching(false);
      }, 200);
      return () => { live = false; clearTimeout(timer); };
    }, [query, group.sector, group.category, group.state]);

    const state = selectionState(list);
    useEffect(() => { if (headerBox.current) headerBox.current.indeterminate = state === "some"; }, [state]);

    const inList = (actor) => list.some((row) => row.actor.actor_id === actor.actor_id);
    const states = options?.states || [];
    const groupHits = groupSuggestions(query, allSectors, states, group);
    // Suggestions in one list: matching groups first, then organizations.
    const items = [...groupHits.map((g) => ({group: g})), ...results.map((a) => ({actor: a}))];
    const chips = [
      group.sector && {key: "sector", kind: "Sector", label: sectorName(group.sector)},
      group.category && {key: "category", kind: "Type", label: CATEGORY_LABELS[group.category] || group.category},
      group.state && {key: "state", kind: "State", label: (states.find((s) => s.code === group.state) || {}).name || group.state},
    ].filter(Boolean);

    function pickGroup(g) {
      setGroup((current) => ({...current, [g.key]: g.code}));
      setQuery(""); setActive(0); setError("");
    }

    // One click adds it. The filters stay, so several can be added from one group.
    function addActor(actor) {
      if (inList(actor)) { setError(`${actor.name} is already in the list.`); return; }
      setError("");
      setList((rows) => addOrganization(rows, actor));
      setQuery("");
    }

    function add() {
      const item = items[active];
      if (item?.group) pickGroup(item.group);
      else if (item?.actor) addActor(item.actor);
      else setError(searching ? "Still searching; one moment."
        : "Type an organization's name, or a sector, type or state.");
    }

    function onKey(e) {
      if (e.key === "ArrowDown" && items.length) { e.preventDefault(); setActive((i) => (i + 1) % items.length); }
      else if (e.key === "ArrowUp" && items.length) { e.preventDefault(); setActive((i) => (i - 1 + items.length) % items.length); }
      else if (e.key === "Backspace" && !query && chips.length) {
        setGroup((current) => ({...current, [chips[chips.length - 1].key]: ""}));
      }
      else if (e.key === "Enter") { e.preventDefault(); add(); }
    }

    const setAll = (checked) => setList((rows) => rows.map((row) => ({...row, checked})));
    const setOne = (id, checked) => setList((rows) => rows.map((row) =>
      row.actor.actor_id === id ? {...row, checked} : row));
    const setSchedule = (patch) => setForm((f) => ({...f, ...patch}));

    const problems = orgUpdateProblems({list, form}, today);
    const ready = Object.keys(problems).length === 0;
    const shown = touched ? problems : {};
    const tooMany = list.filter((row) => row.checked).length > (options?.max_update_actors || 20);

    async function create() {
      setTouched(true);
      if (!ready || busy || tooMany) return;
      setBusy(true); setError("");
      const payload = orgUpdatePayload({list, focus, form, requester, sectors: allSectors});
      try {
        const made = await api("/api/discovery/update-requests", {method: "POST", body: JSON.stringify(payload)});
        // A request that starts today runs its first check now, like every Monitor request.
        const started = payload.start_date === today;
        if (started) await api(`/api/discovery/update-requests/${made.subscription_id}/run`, {method: "POST"});
        const n = payload.actor_ids.length;
        onCreated({started, text: started
          ? `Request created and running now for ${n} ${n === 1 ? "organization" : "organizations"}. `
            + "Its findings go to Review Results; you can follow it under Requests."
          : `Request created for ${n} ${n === 1 ? "organization" : "organizations"}. `
            + `Its first check is on ${formatDay(payload.start_date)}; you can manage it under Requests.`});
        setList([]); setFocus("");
        setForm({cadence: "", startDate: "", duration: ""}); setTouched(false);
      } catch (err) { setError(err.message); }
      setBusy(false);
    }

    return html`<section class="discovery-card org-update">
      <h3 class="org-update-h">Select Organizations</h3>
      <p class="muted org-update-sub">Type an organization's name, or a sector, type or state to list
        a group, and add organizations from the Ecosystem Directory.</p>
      ${chips.length > 0 && html`<div class="org-chips" role="group" aria-label="Narrowed to">
        ${chips.map((c) => html`<span key=${c.key} class="org-chip"><span class="muted">${c.kind}:</span> ${c.label}
          <button type="button" aria-label=${`Remove ${c.kind.toLowerCase()} ${c.label}`}
            onClick=${() => setGroup((g) => ({...g, [c.key]: ""}))}>×</button></span>`)}
      </div>`}
      <div class="org-search">
        <div class="org-search-box">
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" stroke-width="2"/><path d="M20 20l-3.5-3.5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
          <input role="combobox" aria-expanded=${items.length > 0} aria-controls="org-suggestions"
            aria-autocomplete="list" autocomplete="off" value=${query}
            placeholder=${grouped ? "Type to narrow this group..." : "Organization, sector, type or state..."}
            onInput=${(e) => setQuery(e.target.value)} onKeyDown=${onKey}/>
        </div>
        <button type="button" class="btn org-add" disabled=${!items.length} onClick=${add}>Add</button>
      </div>
      ${searching && html`<p class="muted org-none" role="status">Searching the directory…</p>`}
      ${!searching && searched && items.length === 0 && html`
        <p class="muted org-none">No organization in the Ecosystem Directory matches this search.</p>`}
      ${items.length > 0 && html`<div class="org-results">
        ${results.length > 0 && html`<p class="muted org-results-head">${groupCaption(total, results.length, group, allSectors, states)}. Click an organization to add it.</p>`}
        <ul id="org-suggestions" role="listbox" class="org-suggest">
          ${groupHits.map((g, i) => html`<li key=${`${g.key}-${g.code}`} role="option" aria-selected=${i === active}>
            <button type="button" class=${"org-group" + (i === active ? " active" : "")}
              onMouseEnter=${() => setActive(i)} onClick=${() => pickGroup(g)}>
              <strong>${g.label}</strong><span>${g.kind} · list every organization</span>
            </button></li>`)}
          ${results.map((a, n) => { const i = groupHits.length + n; return html`<li key=${a.actor_id} role="option" aria-selected=${i === active}>
            <button type="button" class=${i === active ? "active" : ""} disabled=${inList(a)}
              onMouseEnter=${() => setActive(i)} onClick=${() => addActor(a)}>
              <strong>${a.name}</strong>${inList(a) ? " · Added" : ""}
              <span>${[directoryStatus(a), a.actor_category && (CATEGORY_LABELS[a.actor_category] || a.actor_category.replaceAll("_", " ")),
                (a.sectors || []).map(sectorName).join(", "),
                [a.city, a.state].filter(Boolean).join(", ")].filter(Boolean).join(" · ")}</span>
            </button></li>`; })}
        </ul>
      </div>`}

      ${list.length > 0 && html`<table class="org-table">
        <thead><tr>
          <th class="org-check"><input type="checkbox" ref=${headerBox} aria-label="Select all organizations"
            checked=${state === "all"} onChange=${(e) => setAll(e.target.checked)}/></th>
          <th>Organization</th><th>Mapped Sectors</th><th>Last Checked</th>
        </tr></thead>
        <tbody>${list.map(({actor, checked}) => html`<tr key=${actor.actor_id} class=${checked ? "" : "off"}>
          <td class="org-check"><input type="checkbox" checked=${checked} aria-label=${`Include ${actor.name}`}
            onChange=${(e) => setOne(actor.actor_id, e.target.checked)}/></td>
          <td><span class="org-name">${actor.name}</span>
            ${directoryStatus(actor) && html`<span class=${"org-status " + directoryStatus(actor).toLowerCase()}>${directoryStatus(actor)}</span>`}</td>
          <td class="muted">${(actor.sectors || []).map(sectorName).join(", ") || "None mapped"}</td>
          <td class="muted">${lastCheckedLabel(actor.last_checked)}</td>
        </tr>`)}</tbody>
      </table>`}
      <p class=${"org-count" + (shown.organizations ? " error" : "")}>${list.length
        ? selectionLine(list) : shown.organizations || "No organizations added yet."}</p>
      ${tooMany && html`<p class="discovery-message error">One request covers at most ${options?.max_update_actors || 20} organizations; uncheck some, or make a second request.</p>`}

      <h3 class="org-update-h">What would you like to update?</h3>
      <textarea class="org-specific" rows="3" maxLength=${MAX_SPECIFIC_CHARS}
        aria-label="Update instructions (optional)" placeholder=${SPECIFIC_PLACEHOLDER} value=${focus}
        onInput=${(e) => setFocus(e.target.value)}></textarea>
      ${updateSector(focus, allSectors) && html`<p class="org-hint org-sector">Looking for updates in the
        <strong>${updateSector(focus, allSectors).name}</strong> sector.</p>`}
      <p class="muted org-hint">Leave this blank for a general update: the full profile is checked for
        new, missing, or outdated information. These instructions apply to all selected organizations.</p>

      <${ScheduleRow} form=${form} set=${setSchedule} kind="update" options=${options} today=${today} shown=${shown}/>

      <div class="org-footer">
        <div class="org-notes">
          <p><svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M12 11v6M12 7.5v.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
            Existing directory information remains unchanged until you verify the proposed updates.</p>
          <${EmailNote} requester=${requester} setRequester=${setRequester}/>
        </div>
        <button type="button" class="btn org-create" disabled=${!ready || busy || tooMany} onClick=${create}>
          ${busy ? "Creating…" : "Create Request"}</button>
      </div>
      ${error && html`<p class="discovery-message error">${error}</p>`}
    </section>`;
  }

  function UpdateRequestCard({request, sectors, busy, onAction, today, onChanged, focused}) {
    const [open, setOpen] = useState(false);
    const runs = request.runs || [];
    const live = request.status === "active" || request.status === "paused";
    const current = runningRun(request);
    const status = requestStatus(request);
    const names = request.actor_names || [];
    const sum = (key) => runs.reduce((total, run) => total + Number(run[key] || 0), 0);
    const showResults = () => (names.length === 1 && (request.actor_ids || []).length === 1
      ? openInReview({actor_id: request.actor_ids[0], name: names[0]})
      : window.dispatchEvent(new CustomEvent(OPEN_IN_REVIEW, {detail: {}})));
    return html`<article class=${"discovery-request" + (focused ? " focused" : "")} id=${"request-" + request.subscription_id}>
      <div class="discovery-request-head">
        <div>
          <span class="discovery-kind">Organizations Update</span>
          <h3>${request.title || "Organizations update"}</h3>
          <p>${updateRequestScope(request, sectors)}</p>
        </div>
        <span class=${"discovery-status " + status}>${STATUS_LABELS[status] || status}</span>
      </div>
      <dl class="discovery-facts">
        <div><dt>Next run</dt><dd>${current ? "Running now" : live ? nextRunLabel(request) : "None"}</dd></div>
        <div><dt>Runs so far</dt><dd>${runs.length}</dd></div>
        <div><dt>New or updated</dt><dd>${sum("found_count")}</dd></div>
        <div><dt>Sent to Review Results</dt><dd>${sum("review_item_count")}</dd></div>
      </dl>
      <${EndDate} request=${request} today=${today} onSaved=${onChanged}/>
      ${runs[0] && runs[0].status === "failed" && html`<p class="discovery-message error">Last run failed: ${orgWords(runs[0].status_reason) || "no reason recorded"}</p>`}
      ${current && html`<p class="discovery-message running" role="status"><strong>Running</strong> ·
        ${runningLine(current)}. Reading each organization's sources; results appear in Review Results when it finishes.</p>`}
      <div class="discovery-actions">
        ${current ? html`<button class="btn running" disabled aria-live="polite">Running…</button>`
          : request.status === "active" && html`<button class="btn" disabled=${busy} onClick=${() => onAction(request, "run")}>${runButtonLabel(request)}</button>`}
        ${runs.some((run) => run.status !== "running") && html`<button class="btn ghost" onClick=${showResults}>Show Results</button>`}
        ${request.status === "active" && html`<button class="btn ghost" disabled=${busy} onClick=${() => onAction(request, "pause")}>Pause</button>`}
        ${request.status === "paused" && html`<button class="btn ghost" disabled=${busy} onClick=${() => onAction(request, "resume")}>Resume</button>`}
        ${live && html`<button class="btn ghost danger" disabled=${busy} onClick=${() => onAction(request, "cancel")}>Cancel request</button>`}
        ${runs.length > 0 && html`<button class="btn ghost" onClick=${() => setOpen(!open)}>${open ? "Hide run details" : "Run details"}</button>`}
      </div>
      ${open && html`<div class="discovery-results">
        <h4>Organizations</h4>
        <p class="muted">${names.join(", ") || "—"}</p>
        <h4>Runs</h4>
        ${runs.map((run) => html`<div key=${run.collection_run_id} class="update-run">
          <p><strong>${formatDay(run.started_at)}</strong> · ${RUN_STATUS[run.status] || run.status}
            · ${run.found_count ?? 0} new or updated · ${run.review_item_count ?? 0} to Review Results
            · ${formatUsd(run.spent_usd)}</p>
          ${run.status_reason && html`<p class="muted">${orgWords(run.status_reason)}</p>`}
          ${(run.actor_results || []).length > 0 && html`<ul class="skipped">${run.actor_results.map((a) =>
            html`<li key=${a.actor_id} class=${a.ok ? "" : "warn"}>${actorResultLine(a)}</li>`)}</ul>`}
        </div>`)}
      </div>`}
    </article>`;
  }

  function EntityRequestForm({kind, options, today, requester, setRequester, onSaved}) {
    const [form, setForm] = useState(() => blankEntityForm(today, kind));
    const [touched, setTouched] = useState(false);
    const [working, setWorking] = useState("");
    const [message, setMessage] = useState(null);
    useEffect(() => { setForm(blankEntityForm(today, kind)); setTouched(false); setMessage(null); }, [kind]);
    const set = (patch) => setForm((f) => ({...f, ...patch}));
    const draft = resolveEventDraft(form, options);
    const problems = entityDraftProblems(draft, options);
    const shown = touched ? problems : {};
    const ready = options.entity_requests_ready !== false;
    const regionShown = draft.areaKind === "us" ? "" : draft.region;

    async function create() {
      setTouched(true);
      if (Object.keys(problems).length) return;
      setWorking("create"); setMessage(null);
      try {
        const payload = withRequester(withEventWindow(entityDraftPayload(draft)), requester);
        const result = await createRequest(payload, today);
        setMessage({kind: "success", text: createdMessage(result, payload)});
        setForm(blankEntityForm(today, kind)); setTouched(false);
        onSaved(result.started);
      } catch (err) { setMessage({kind: "error", text: err.message}); }
      setWorking("");
    }

    return html`<section class="discovery-card">
      ${!ready && html`<p class="discovery-message error">Event requests need migration 580 on this database.</p>`}
      ${message && html`<p class=${"discovery-message " + message.kind}>${message.text}</p>`}
      <${Field} label=${EVENT_QUESTION} error=${shown.title || shown.topic ? "Describe the events to monitor." : ""} wide=${true}>
        <textarea class="discovery-brief" rows="3" maxLength="2000" value=${form.brief}
          placeholder=${EVENT_PLACEHOLDER} onInput=${(e) => set({brief: e.target.value})}></textarea>
      <//>
      <div class="discovery-row4">
        <${Field} label="Sector" error=${shown.sector}>
          <select value=${draft.sector || ANY_SECTOR} onChange=${(e) => set({sector: e.target.value})}>
            <option value=${ANY_SECTOR}>Any</option>
            ${options.topics.map((t) => html`<option key=${t.code} value=${t.code}>${t.name}</option>`)}
          </select>
        <//>
        <${Field} label="Region" error=${shown.area}>
          <select value=${regionShown} onChange=${(e) => {
            const region = e.target.value;
            const keep = draft.areaKind === "state"
              && statesForRegion(options, region).some((s) => s.code === draft.state);
            set({region, state: keep ? draft.state : "", areaTouched: true,
              areaKind: keep ? "state" : region ? "region" : "us"});
          }}>
            <option value="">All Regions</option>
            ${options.regions.map((r) => html`<option key=${r.code} value=${r.code}>${r.name}</option>`)}
          </select>
        <//>
        <${Field} label="State">
          <select value=${draft.areaKind === "state" ? draft.state : ""} onChange=${(e) => {
            const state = e.target.value;
            set({state, areaTouched: true, areaKind: state ? "state" : draft.region ? "region" : "us"});
          }}>
            <option value="">All States</option>
            ${statesForRegion(options, regionShown).map((s) => html`<option key=${s.code} value=${s.code}>${s.name}</option>`)}
          </select>
        <//>
        <${Field} label="Event Type" error=${shown.types}>
          <select value=${form.eventTypes[0] || ""} onChange=${(e) => set({eventTypes: e.target.value ? [e.target.value] : []})}>
            <option value="">All Event Types</option>
            ${(options.event_types || Object.keys(EVENT_TYPE_LABELS)).map((type) => html`
              <option key=${type} value=${type}>${EVENT_TYPE_LABELS[type] || type}</option>`)}
          </select>
        <//>
      </div>
      <div class="discovery-daterange">
        <span class="discovery-label">Event Date Range</span>
        <div class="discovery-daterange-row">
          <label><span>From</span><${DateInput} ariaLabel="Events from" value=${form.dateFrom}
            onChange=${(v) => set({dateFrom: v})}/></label>
          <label><span>To</span><${DateInput} ariaLabel="Events to" value=${form.dateTo} min=${form.dateFrom}
            onChange=${(v) => set({dateTo: v})}/></label>
        </div>
        ${shown.dates ? html`<small class="field-error">${shown.dates}</small>`
          : html`<small class="muted">Defaults to upcoming events within the next ${EVENT_WINDOW_MONTHS} months.</small>`}
      </div>
      <${ScheduleRow} form=${form} set=${set} kind=${kind} options=${options} today=${today} shown=${shown}/>
      <${RequestFooter} requester=${requester} setRequester=${setRequester} working=${working === "create"}
        disabled=${!!working || !ready} onCreate=${create} note=${REVIEW_NOTE}/>
    </section>`;
  }

  function RequestCard({request, options, busy, onAction, onRun, today, onChanged, focused}) {
    const [open, setOpen] = useState(false);
    const runs = request.runs || [];
    const results = request.results || [];
    const excluded = request.excluded || [];
    const last = runs[0];
    const live = request.status === "active" || request.status === "paused";
    const current = runningRun(request);
    const status = requestStatus(request);
    const finished = runs.find((run) => run.status !== "running" && reviewRunKey(run));
    const entity = request.discovery_entity || "actor";
    const noun = {actor: "Organizations", event: "Events", person: "People"}[entity];
    return html`<article class=${"discovery-request" + (focused ? " focused" : "")} id=${"request-" + request.subscription_id}>
      <div class="discovery-request-head">
        <div>
          ${entity !== "actor" && html`<span class="discovery-kind">${noun}</span>`}
          <h3>${request.title || "Untitled request"}</h3>
          <p>${entity === "actor" ? requestSummary(request, options) : entitySummary(request, options)}</p>
        </div>
        <span class=${"discovery-status " + status}>${STATUS_LABELS[status] || status}</span>
      </div>
      <dl class="discovery-facts">
        <div><dt>Next run</dt><dd>${current ? "Running now" : live ? nextRunLabel(request) : "None"}</dd></div>
        <div><dt>Runs so far</dt><dd>${runs.length}</dd></div>
        ${entity === "actor" ? html`
        <div><dt>Added to the directory</dt><dd>${results.filter((r) => resultOutcome(r) === "auto_high").length}</dd></div>
        <div><dt>Sent to Review Results</dt><dd>${results.filter((r) => resultOutcome(r) !== "auto_high").length}</dd></div>` : html`
        <div><dt>Sent to Review Results</dt><dd>${results.length}</dd></div>
        <div><dt>Excluded</dt><dd>${excluded.length}</dd></div>`}
      </dl>
      <${EndDate} request=${request} today=${today} onSaved=${onChanged}/>
      ${last && last.status === "failed" && html`<p class="discovery-message error">Last run failed: ${orgWords(last.status_reason) || "no reason recorded"}</p>`}
      ${current && html`<p class="discovery-message running" role="status"><strong>Running</strong> ·
        ${runningLine(current)}. Searching, reading pages and scoring; results appear in Review Results when it finishes.</p>`}
      ${status === "stalled" && html`<p class="discovery-message error">The last run stopped responding before it finished. Its spend so far is recorded; you can run the request again.</p>`}
      <div class="discovery-actions">
        ${current ? html`<button class="btn running" disabled aria-live="polite">Running…</button>`
          : request.status === "active" && html`<button class="btn" disabled=${busy} onClick=${() => onRun(request)}>${runButtonLabel(request)}</button>`}
        ${finished && html`<button class="btn ghost" onClick=${() => openRunInReview(finished, entity)}>Show Results</button>`}
        ${request.status === "active" && html`<button class="btn ghost" disabled=${busy} onClick=${() => onAction(request, "pause")}>Pause</button>`}
        ${request.status === "paused" && html`<button class="btn ghost" disabled=${busy} onClick=${() => onAction(request, "resume")}>Resume</button>`}
        ${live && html`<button class="btn ghost danger" disabled=${busy} onClick=${() => onAction(request, "cancel")}>Cancel request</button>`}
        ${(runs.length > 0 || results.length > 0) && html`<button class="btn ghost" onClick=${() => setOpen(!open)}>${open ? "Hide run details" : "Run details"}</button>`}
      </div>
      ${open && html`<div class="discovery-results">
        <h4>${noun} found</h4>
        ${results.length === 0 ? html`<p class="muted">Nothing has passed the quality checks yet.</p>`
          : html`<ul>${results.map((r) => html`<li key=${r.candidate_id}>
              <div><strong>${r.name || r.url}</strong>
                ${r.website && html` · <a href=${r.website} target="_blank" rel="noopener noreferrer">${r.website.replace(/^https?:\/\//, "").replace(/\/$/, "")}</a>`}</div>
              ${r.description && html`<p>${r.description}</p>`}
              <span class=${"discovery-band " + r.score_band}>${entity === "actor"
                ? RESULT_LABELS[resultOutcome(r)] : "Sent to Review Results"}</span>
              ${r.fit_score != null && html`<span class="discovery-scores">${scoreLine(r)}</span>`}
              <dl class="discovery-detail">
                ${(entity === "actor" ? resultFacts(r) : entityResultFacts(r)).map(([label, value]) => html`<div key=${label}><dt>${label}</dt><dd>${value}</dd></div>`)}
              </dl>
              ${r.score_band === "review" && r.triage_reason && html`<p class="discovery-held"><strong>Why a person should look:</strong> ${orgWords(r.triage_reason)}</p>`}
              <a class="discovery-source" href=${r.url} target="_blank" rel="noopener noreferrer">Page read</a>
            </li>`)}</ul>`}
        ${excluded.length > 0 && html`<details class="discovery-excluded">
          <summary>Not added (${excluded.length}): ${exclusionSummary(excluded)}</summary>
          <ul>${excluded.map((x) => html`<li key=${x.url}>
            <strong>${x.name || x.url}</strong> <span class="muted">${EXCLUSION_LABELS[exclusionKind(x)]}</span>
            <p>${orgWords(x.triage_reason) || "No reason was recorded."}</p>
          </li>`)}</ul>
        </details>`}
        <h4>Runs</h4>
        ${runs.length === 0 ? html`<p class="muted">Not run yet.</p>` : html`<table class="discovery-runs">
          <thead><tr><th>Date</th><th>Result</th><th>Time</th><th>Pages found</th><th>Added</th><th>To Review</th><th>Spent</th><th>Per Relevant Organization</th><th></th></tr></thead>
          <tbody>${runs.map((run) => html`<tr key=${run.collection_run_id}>
            <td>${formatDay(run.started_at)}</td>
            <td>${run.status === "running" && run.stalled ? "Stopped responding"
              : {succeeded: "Completed", attention: "Completed with limits", failed: "Failed", running: "Running"}[run.status] || run.status}</td>
            <td>${durationLabel(run.elapsed_seconds)}</td>
            <td>${run.found_count ?? ""}</td><td>${run.staged_count ?? ""}</td><td>${run.review_item_count ?? ""}</td>
            <td>${formatUsd(run.spent_usd)}${run.status === "running" ? " so far" : ""}</td><td>${costPerRelevantActor(run)}</td>
            <td>${run.status !== "running" && reviewRunKey(run) && html`<button class="link" onClick=${() => openRunInReview(run, entity)}>Show Results</button>`}</td>
          </tr>`)}</tbody></table>`}
      </div>`}
    </article>`;
  }

  function RequestsTable({rows, onOpen}) {
    const [query, setQuery] = useState("");
    const [status, setStatus] = useState("");
    const [type, setType] = useState("");
    const statuses = [...new Set(rows.map((r) => r.status))];
    const shown = rows.filter((r) => (!status || r.status === status) && (!type || r.type === type)
      && (!query.trim() || r.title.toLowerCase().includes(query.trim().toLowerCase())));
    return html`<section class="requests-view">
      <div class="discovery-card requests-filters">
        <input class="requests-search" type="search" placeholder="Search requests…" aria-label="Search requests"
          value=${query} onInput=${(e) => setQuery(e.target.value)}/>
        <div class="requests-selects">
          <label><span>Status</span>
            <select value=${status} onChange=${(e) => setStatus(e.target.value)}>
              <option value="">All Statuses</option>
              ${statuses.map((s) => html`<option key=${s} value=${s}>${STATUS_LABELS[s] || s}</option>`)}
            </select></label>
          <label><span>Request Type</span>
            <select value=${type} onChange=${(e) => setType(e.target.value)}>
              <option value="">All Types</option>
              ${Object.entries(REQUEST_TYPES).map(([id, label]) => html`<option key=${id} value=${id}>${label}</option>`)}
            </select></label>
        </div>
      </div>
      <div class="discovery-card requests-table">
        ${!rows.length ? html`<p class="discovery-empty">No requests yet.</p>`
          : !shown.length ? html`<p class="discovery-empty">No requests match these filters.</p>`
          : html`<table>
            <thead><tr><th>Request</th><th>Request Type</th><th>Record Type</th><th>Status</th><th>Next Run</th><th aria-hidden="true"></th></tr></thead>
            <tbody>${shown.map((r) => html`<tr key=${r.key} tabindex="0" onClick=${() => onOpen(r.key)}
                onKeyDown=${(e) => { if (e.key === "Enter") onOpen(r.key); }}>
              <td class="requests-name">${r.title}</td><td>${REQUEST_TYPES[r.type]}</td><td>${r.recordType}</td>
              <td><span class=${"requests-pill " + r.status}>${STATUS_LABELS[r.status] || r.status}</span></td>
              <td>${runningRun(r.request) ? "Running now" : ["active", "paused"].includes(r.request.status) ? nextRunLabel(r.request) : "None"}</td>
              <td class="requests-go" aria-hidden="true">›</td></tr>`)}</tbody>
          </table>`}
        <p class="requests-note"><span aria-hidden="true">ⓘ</span> Open a request to view its criteria, schedule, and run history.</p>
      </div>
    </section>`;
  }

  function RequestDrawer({row, options, busy, onAction, onRun, today, onChanged, onClose}) {
    const [editing, setEditing] = useState(false);
    useEffect(() => {
      const close = (e) => { if (e.key === "Escape") onClose(); };
      window.addEventListener("keydown", close);
      return () => window.removeEventListener("keydown", close);
    }, []);
    const request = row.request;
    const find = row.type === "find";
    const runs = request.runs || [];
    const results = request.results || [];
    const excluded = request.excluded || [];
    const last = runs[0];
    const live = request.status === "active" || request.status === "paused";
    const current = runningRun(request);
    const entity = request.discovery_entity || "actor";
    const canEdit = find && live && request.cadence !== "once";
    const brief = !find ? updateRequestScope(request, options?.topics || [])
      : entity === "actor" ? requestSummary(request, options) : entitySummary(request, options);
    return html`<div class="requests-backdrop" onClick=${onClose}></div>
    <aside class="requests-drawer" role="dialog" aria-modal="true" aria-label="Request details">
      <header><h2>Request Details</h2>
        <button type="button" class="requests-close" aria-label="Close" onClick=${onClose}>×</button></header>
      <section>
        <h3>${row.title}</h3>
        <span class=${"requests-pill " + row.status}>${STATUS_LABELS[row.status] || row.status}</span>
        <dl class="requests-pair">
          <div><dt>Request Type</dt><dd>${REQUEST_TYPES[row.type]}</dd></div>
          <div><dt>Record Type</dt><dd>${row.recordType}</dd></div>
        </dl>
      </section>
      <section><h4>Search Brief</h4><p>${brief || "Not recorded"}</p></section>
      <section><h4>Schedule</h4>
        <dl class="requests-pair">
          <div><dt>Frequency</dt><dd>${CADENCE_LABELS[request.cadence] || request.cadence || "Not recorded"}</dd></div>
          <div><dt>Start Date</dt><dd>${formatDay(request.start_date) || "Not recorded"}</dd></div>
          <div><dt>Duration</dt><dd>${requestDuration(request)}</dd></div>
          <div><dt>Next Run</dt><dd>${current ? "Running now" : live ? nextRunLabel(request) : "None"}</dd></div>
        </dl>
        ${editing && html`<${EndDate} request=${request} today=${today} onSaved=${onChanged}/>`}
      </section>
      ${last && last.status === "failed" && html`<p class="discovery-message error">Last run failed: ${last.status_reason || "no reason recorded"}</p>`}
      ${current && html`<p class="discovery-message running" role="status"><strong>Running</strong> ·
        ${runningLine(current)}. Results appear in Review Results when it finishes.</p>`}
      ${row.status === "stalled" && html`<p class="discovery-message error">The last run stopped responding before it finished. Its spend so far is recorded; you can run the request again.</p>`}
      <div class="requests-actions">
        ${current ? html`<button class="btn running" disabled aria-live="polite">Running…</button>`
          : request.status === "active" && html`<button class="btn" disabled=${!!busy} onClick=${() => onRun(row)}>${runButtonLabel(request)}</button>`}
        ${canEdit && html`<button class="btn ghost" onClick=${() => setEditing(!editing)}>${editing ? "Done editing" : "✎ Edit Request"}</button>`}
        ${request.status === "active" && html`<button class="btn ghost" disabled=${!!busy} onClick=${() => onAction(row, "pause")}>❚❚ Pause</button>`}
        ${request.status === "paused" && html`<button class="btn ghost" disabled=${!!busy} onClick=${() => onAction(row, "resume")}>▶ Resume</button>`}
        ${live && html`<button class="btn ghost danger requests-cancel" disabled=${!!busy} onClick=${() => onAction(row, "cancel")}>🗑 Cancel Request</button>`}
      </div>
      ${editing && html`<p class="muted requests-hint">For now the end date is the part of a request that can be changed.</p>`}
      <section><h4>Run History</h4>
        ${runs.length === 0 ? html`<p class="muted">Not run yet.</p>` : html`<ul class="requests-runs">
          ${runs.map((run) => html`<li key=${run.collection_run_id}>
            <span>${formatDay(run.started_at)}</span>
            <span class=${"requests-pill " + (run.status === "running" && run.stalled ? "stalled" : run.status)}>${
              run.status === "running" && run.stalled ? "Stopped responding" : RUN_STATUS[run.status] || run.status}</span>
            <span>${runFindings(run)} ${runFindings(run) === 1 ? "finding" : "findings"}</span>
            ${find && run.status !== "running" && reviewRunKey(run)
              ? html`<button class="link" onClick=${() => openRunInReview(run, entity)}>Show Results</button>` : html`<span></span>`}
          </li>`)}</ul>
        <p class="requests-note"><span aria-hidden="true">ⓘ</span> ${find
          ? "Show Results opens the selected run in Review Results." : "What an update changed is listed in Organization Updates."}</p>`}
      </section>
      ${find && (results.length > 0 || excluded.length > 0) && html`<details class="discovery-results requests-found">
        <summary>What was found (${results.length})</summary>
        <ul>${results.map((r) => html`<li key=${r.candidate_id}>
            <div><strong>${r.name || r.url}</strong>
              ${r.website && html` · <a href=${r.website} target="_blank" rel="noopener noreferrer">${r.website.replace(/^https?:\/\//, "").replace(/\/$/, "")}</a>`}</div>
            ${r.description && html`<p>${r.description}</p>`}
            <span class=${"discovery-band " + r.score_band}>${entity === "actor"
              ? RESULT_LABELS[resultOutcome(r)] : "Sent to Review Results"}</span>
            ${r.fit_score != null && html`<span class="discovery-scores">${scoreLine(r)}</span>`}
            <dl class="discovery-detail">
              ${(entity === "actor" ? resultFacts(r) : entityResultFacts(r)).map(([label, value]) => html`<div key=${label}><dt>${label}</dt><dd>${value}</dd></div>`)}
            </dl>
            ${r.score_band === "review" && r.triage_reason && html`<p class="discovery-held"><strong>Why a person should look:</strong> ${orgWords(r.triage_reason)}</p>`}
            <a class="discovery-source" href=${r.url} target="_blank" rel="noopener noreferrer">Page read</a>
          </li>`)}</ul>
        ${excluded.length > 0 && html`<details class="discovery-excluded">
          <summary>Not added (${excluded.length}): ${exclusionSummary(excluded)}</summary>
          <ul>${excluded.map((x) => html`<li key=${x.url}>
            <strong>${x.name || x.url}</strong> <span class="muted">${EXCLUSION_LABELS[exclusionKind(x)]}</span>
            <p>${orgWords(x.triage_reason) || "No reason was recorded."}</p>
          </li>`)}</ul>
        </details>`}
      </details>`}
    </aside>`;
  }

  return function Discovery({handoff = null, onHandoffUsed = () => {}} = {}) {
    const today = isoDate(new Date());
    const [status, setStatus] = useState({loaded: false, configured: false});
    const [options, setOptions] = useState(null);
    const [requests, setRequests] = useState([]);
    // Organizations Update requests, listed under Requests too.
    const [updates, setUpdates] = useState([]);
    const [view, setView] = useState("new");
    // The Dashboard opens Requests, or one request in it.
    const [focusId, setFocusId] = useState(null);
    useEffect(() => {
      const on = (e) => {
        if (e.detail?.tab !== "discovery") return;
        if (e.detail.request_id || e.detail.view === "requests") setView("requests");
        setFocusId(e.detail.request_id || null);
      };
      window.addEventListener(NAVIGATE, on);
      return () => window.removeEventListener(NAVIGATE, on);
    }, []);
    useEffect(() => {
      if (view !== "requests" || !focusId) return;
      document.getElementById(`request-${focusId}`)?.scrollIntoView({block: "center", behavior: "smooth"});
    }, [view, focusId, requests, updates]);
    // What the new request finds. Organizations keep their form exactly.
    const [kind, setKind] = useState("actor");
    const [form, setForm] = useState(blankForm);
    // Who asked is the signed-in user: their results go to their account's email
    // (the server sets it). Nobody types an address (3 Nov 2026).
    const requester = "";
    const setRequester = () => {};
    const [touched, setTouched] = useState(false);
    const [busy, setBusy] = useState(false);
    const [working, setWorking] = useState("");
    const [message, setMessage] = useState(null);
    const [loadFailed, setLoadFailed] = useState(false);

    const set = (patch) => setForm((f) => ({...f, ...patch}));

    async function load() {
      let s;
      try {
        s = await api("/api/discovery/status");
      } catch (err) {
        setStatus({loaded: true, configured: false});
        setMessage({kind: "error", text: err.message});
        return;
      }
      setStatus({loaded: true, configured: !!s.configured});
      if (!s.configured) return;
      // A list that fails once (the backend under load) is an error to retry, never
      // "not available on this instance" (3 Nov 2026).
      try {
        const [o, r, u] = await Promise.all([api("/api/discovery/options"), api("/api/discovery/requests"),
          api("/api/discovery/update-requests").catch(() => ({requests: []}))]);
        setOptions(o);
        setRequests(r.requests || []);
        setUpdates((u.requests || []).filter((x) => !x.test_sector));
        setLoadFailed(false);
      } catch (err) {
        setLoadFailed(true);
        setMessage({kind: "error", text: err.message});
      }
    }
    useEffect(() => { load(); }, []);

    // A request proposed from a Build the Map result: open it, unsaved, for editing.
    useEffect(() => {
      if (!handoff) return;
      setForm(handoffForm(handoff, today));
      setView("new"); setTouched(false);
      if (status.configured) setMessage({kind: "running", text: "Proposed from your map. Check the "
        + "description, sector and area before creating the request. "
        + "Monitoring doesn't know this map's results, so its first run may send some of the same "
        + "organizations to Review Results again."});
      onHandoffUsed();
    }, [handoff]);

    // Everything that is sent, summarised or validated runs on the RESOLVED
    // draft, so the brief and the panel can never disagree about what will run.
    const draft = resolveDraft(form, options || {});
    const problems = draftProblems(form, options || {});
    const valid = Object.keys(problems).length === 0;
    const shown = touched ? problems : {};

    async function create() {
      setTouched(true);
      if (!valid) return;
      setBusy(true); setWorking("create"); setMessage(null);
      try {
        const payload = withRequester(draftPayload(draft), requester);
        const result = await createRequest(payload, today);
        setMessage({kind: "success", text: createdMessage(result, payload)});
        setForm(blankForm()); setTouched(false);
        await load();
        if (result.started) setWatchUntil(Date.now() + 20 * 60 * 1000);
        setView("requests");
      } catch (err) { setMessage({kind: "error", text: err.message}); }
      setBusy(false); setWorking("");
    }

    // While anything is running (or was just started), refresh every 15 s.
    const [watchUntil, setWatchUntil] = useState(0);
    useEffect(() => {
      const active = requests.some(isRunning) || updates.some(isRunning) || Date.now() < watchUntil;
      if (!active) return undefined;
      const timer = setInterval(() => { load(); }, 15000);
      return () => clearInterval(timer);
    }, [requests, updates, watchUntil]);

    async function runNow(request) {
      if (!window.confirm(`Run “${request.title}” now? It searches the web live and adds what passes the quality checks.`)) return;
      setBusy(true); setMessage(null);
      try {
        await api(`/api/discovery/requests/${request.subscription_id}/run`, {method: "POST"});
        setMessage({kind: "success", text: `“${request.title}” is running. This takes a few minutes; the page updates by itself.`});
        setWatchUntil(Date.now() + 20 * 60 * 1000);
        setTimeout(load, 4000);
      } catch (err) { setMessage({kind: "error", text: err.message}); }
      setBusy(false);
    }

    async function onAction(request, action) {
      if (action === "cancel" && !window.confirm(`Cancel “${request.title}”? It will not run again.`)) return;
      setBusy(true); setMessage(null);
      try {
        await api(`/api/discovery/requests/${request.subscription_id}/${action}`, {method: "POST"});
        await load();
      } catch (err) { setMessage({kind: "error", text: err.message}); }
      setBusy(false);
    }

    async function onUpdateAction(request, action) {
      if (action === "cancel" && !window.confirm(`Cancel “${request.title}”? It will not run again.`)) return;
      if (action === "run" && !window.confirm(`Run “${request.title}” now? It reads each organization's `
        + "sources; findings go to Review Results.")) return;
      setBusy(true); setMessage(null);
      try {
        await api(`/api/discovery/update-requests/${request.subscription_id}/${action}`, {method: "POST"});
        if (action === "run") setWatchUntil(Date.now() + 20 * 60 * 1000);
        await load();
      } catch (err) { setMessage({kind: "error", text: err.message}); }
      setBusy(false);
    }

    // The table and panel act on a row; monitoring and update requests keep their own handlers.
    const [openKey, setOpenKey] = useState(null);
    const rowRun = (row) => (row.type === "update" ? onUpdateAction(row.request, "run") : runNow(row.request));
    const rowAction = (row, action) => (row.type === "update" ? onUpdateAction(row.request, action) : onAction(row.request, action));

    // Requests are private to whoever made them (their email); older ones stay shared.
    const mine = visibleRequests(requests, requester);
    const myUpdates = visibleRequests(updates, requester);
    const rows = requestRows(mine, myUpdates);
    const openRow = rows.find((r) => r.key === openKey);

    return html`<div class="discovery-page">
      <h1 class="hero-h">${MONITOR_TITLE}</h1>
      <p class="lead">${MONITOR_LEAD}</p>

      ${message && html`<p class=${"discovery-message " + message.kind}>${message.text}</p>`}
      ${loadFailed && html`<div class="discovery-actions"><button class="btn ghost"
        onClick=${() => { setMessage(null); load(); }}>Try again</button></div>`}
      ${status.loaded && !status.configured && html`<p class="discovery-message error">Discovery requests are not available on this instance.</p>`}
      ${status.loaded && !status.configured && form.brief && html`<section class="discovery-card">
        <p class="muted">The request proposed from your map, kept here until Discovery is set up:</p>
        <pre class="discovery-brief">${form.brief}</pre>
      </section>`}

      ${status.configured && options && html`
      <div class="subnav">
        <button class=${view === "new" ? "active" : ""} onClick=${() => setView("new")}>New Request</button>
        <button class=${view === "requests" ? "active" : ""} onClick=${() => setView("requests")}>Requests</button>
        <button class=${view === "actors" ? "active" : ""} onClick=${() => setView("actors")}>Organization Updates</button>
      </div>

      ${view === "new" && html`<div class="discovery-segment discovery-kinds" role="group" aria-label="What to discover">
        ${DISCOVERY_KINDS.map((k) => html`<button type="button" key=${k.id}
          class=${kind === k.id ? "active" : ""} aria-pressed=${kind === k.id}
          onClick=${() => setKind(k.id)}>${k.label}</button>`)}
      </div>`}

      ${view === "new" && kind === "event" && html`<${EntityRequestForm} kind=${kind} options=${options}
        today=${today} requester=${requester} setRequester=${setRequester}
        onSaved=${async (started) => { await load(); if (started) setWatchUntil(Date.now() + 20 * 60 * 1000); }}/>`}
      ${view === "new" && kind === "person" && html`<${PeopleRequestForm} options=${options}
        today=${today} requester=${requester} setRequester=${setRequester}
        onSaved=${async (started) => { await load(); if (started) setWatchUntil(Date.now() + 20 * 60 * 1000); }}/>`}

      ${view === "new" && kind === "actor" && html`<section class="discovery-card">
        <${Field} label=${ORG_QUESTION} error=${shown.brief} wide=${true}>
          <textarea class="discovery-brief" rows="4" value=${form.brief} placeholder=${ORG_PLACEHOLDER}
            onInput=${(e) => set({brief: e.target.value})}></textarea>
        <//>
        <div class="discovery-row3">
          <${Field} label="Sector" error=${shown.sector}>
            <select value=${draft.sector} onChange=${(e) => set({sector: e.target.value})}>
              ${!draft.sector && html`<option value="">Choose a sector</option>`}
              <option value=${ANY_SECTOR}>Any</option>
              ${options.topics.map((t) => html`<option key=${t.code} value=${t.code}>${t.name}</option>`)}
            </select>
          <//>
          <${Field} label="Region" error=${shown.area}>
            <select value=${draft.areaKind === "us" ? "" : draft.region} onChange=${(e) => {
              const region = e.target.value;
              const keep = draft.areaKind === "state"
                && statesForRegion(options, region).some((s) => s.code === draft.state);
              set({region, state: keep ? draft.state : "", areaTouched: true,
                areaKind: keep ? "state" : region ? "region" : "us"});
            }}>
              <option value="">All Regions</option>
              ${options.regions.map((r) => html`<option key=${r.code} value=${r.code}>${r.name}</option>`)}
            </select>
          <//>
          <${Field} label="State">
            <select value=${draft.areaKind === "state" ? draft.state : ""} onChange=${(e) => {
              const state = e.target.value;
              set({state, areaTouched: true, areaKind: state ? "state" : draft.region ? "region" : "us"});
            }}>
              <option value="">All States</option>
              ${statesForRegion(options, draft.areaKind === "us" ? "" : draft.region).map((s) => html`
                <option key=${s.code} value=${s.code}>${s.name}</option>`)}
            </select>
          <//>
        </div>
        <${ScheduleRow} form=${form} set=${set} kind="actor" options=${options} today=${today} shown=${shown}/>
        <${RequestFooter} requester=${requester} setRequester=${setRequester} working=${working === "create"}
          disabled=${busy} onCreate=${create} note=${REVIEW_NOTE}/>
      </section>`}

      ${view === "actors" && html`<${OrganizationsUpdate} sectors=${options.topics} options=${options}
        today=${today} requester=${requester} setRequester=${setRequester}
        onCreated=${async ({started, text}) => {
          setMessage({kind: "success", text}); await load();
          if (started) setWatchUntil(Date.now() + 20 * 60 * 1000);
          setView("requests");
        }}/>`}

      ${view === "requests" && html`<${RequestsTable} rows=${rows} onOpen=${setOpenKey}/>`}
      ${view === "requests" && openRow && html`<${RequestDrawer} key=${openRow.key} row=${openRow} options=${options}
        busy=${busy} onAction=${rowAction} onRun=${rowRun} today=${today} onChanged=${load}
        onClose=${() => setOpenKey(null)}/>`}
      `}
    </div>`;
  };
}
