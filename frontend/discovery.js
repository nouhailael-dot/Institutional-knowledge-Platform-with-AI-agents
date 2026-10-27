// Discovery: ask the agent to find organizations on a topic, in an area, for a
// period, at a frequency. Actor discovery runs only for requests made here.
//
// The page never writes anything itself. Every call goes through
// /api/discovery/*, which hands it to the GHUS backend's own command.

import {usDate} from "./dates.js?v=20261027a";

export const CADENCE_LABELS = {
  once: "Once",
  weekly: "Every week",
  biweekly: "Every two weeks",
  monthly: "Every month",
  quarterly: "Every three months",
};

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
  {id: "custom", label: "Custom", months: null},
];

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
  auto_high: "Added to the map · verified by the agent",
  review: "Sent to Review",
};

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
    ["Date", row.start_date ? formatDay(row.start_date) : null],
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
      result: last ? `${last.found_count ?? 0} new or updated · ${last.review_item_count ?? 0} to Review`
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
  const read = depth === "light" ? " Each organization kept is read on its own site (Light Pull)."
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
      + " — proposed to Review when written, never assigned directly");
  }
  if (hubs.note) parts.push(hubs.note);
  return parts.join(" · ") || "In no hub.";
}

const RELATED_STATUS = {
  on_map: "On the map — the link goes to Review when written",
  ambiguous: "Several records match — nothing is written; a person decides",
  not_on_map: "Not on the map",
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
  if (result.review_items) parts.push(`${result.review_items} to Review`);
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
    if (v.date && v.description) return `${v.date} — ${v.description}`;
    if (v.reason) return v.reason;
    // Flags (is_multi_location: false) are not something to read out.
    return Object.values(v).filter((x) => x !== null && x !== "" && typeof x !== "boolean").join(" · ");
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
  return [`${total} ${total === 1 ? "actor" : "actors"}`, sector, type, state,
    shown < total ? `showing ${shown}` : null].filter(Boolean).join(" · ");
}

/** "1 new · 2 changed · 1 conflicts requiring review", most consequential first. */
export function outcomeSummary(counts = {}) {
  return RESULT_GROUPS.filter((g) => counts[g.id])
    .map((g) => `${counts[g.id]} ${g.label.toLowerCase()}`)
    .join(" · ");
}

// What the form sends. Empty optional fields are left out, never sent blank.
export const PULL_DEPTH_LABELS = {
  light: "Light Pull: read each organization's own pages (recommended)",
  none: "Search page only: do not read the organizations' sites",
};

export function draftPayload(form) {
  const payload = {
    title: form.title.trim(),
    sector_codes: form.sector ? [form.sector] : [],
    focus_terms: form.focusTerms,
    start_date: form.startDate,
    end_date: form.cadence === "once" ? form.startDate : form.endDate,
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
    problems.sector = "Any sector needs a sub-topic to search for.";
    problems.brief = "With any sector, add at least one line naming what to search for.";
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
  if (form.cadence !== "once") {
    if (!form.endDate) problems.duration = "Choose how long the request runs.";
    else if (form.endDate < form.startDate) problems.duration = "The end date is before the start.";
  }
  return problems;
}

// ------------------------------------------------------- events and people
//
// The same request, for events or people (backend migration 580). The
// organization form above is untouched; these forms ask only what an event or
// people search needs, and use the same request storage, scheduler and Review.

export const DISCOVERY_KINDS = [
  {id: "actor", label: "Organizations / Actors"},
  {id: "event", label: "Events"},
  {id: "person", label: "People"},
];

export const EVENT_TYPE_LABELS = {
  conference: "Conference", summit: "Summit", symposium: "Symposium", forum: "Forum",
  training: "Training",
  // No longer offered; still named on requests saved with them.
  workshop: "Workshop", expo: "Expo", webinar: "Webinar", hackathon: "Hackathon",
};

export function blankEntityForm(today, kind) {
  return {
    kind, title: "", sector: "", focusTerms: [], focusInput: "",
    areaKind: "us", region: "", state: "", city: "",
    dateFrom: "", dateTo: "", eventTypes: [], institution: "", role: "",
    startDate: today, cadence: "once", duration: "3m", endDate: addMonths(today, 3),
  };
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
    end_date: form.cadence === "once" ? form.startDate : form.endDate,
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
  if (form.cadence !== "once") {
    if (!form.endDate) problems.duration = "Choose how long the request runs.";
    else if (form.endDate < form.startDate) problems.duration = "The end date is before the start.";
  }
  return problems;
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

function blankForm(today) {
  return {
    brief: "", areaTouched: false,
    title: "", sector: "", focusTerms: [], focusInput: "",
    areaKind: "region", region: "", state: "", city: "",
    startDate: today, duration: "3m", endDate: addMonths(today, 3),
    cadence: "weekly", cap: 10, pullDepth: "light",
  };
}

export function createDiscoveryPage({html, useState, useEffect}) {
  async function api(path, options = {}) {
    const response = await fetch(path, {
      headers: {"Content-Type": "application/json"}, ...options,
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
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

  function ActorUpdates({onFindNew, sectors, states}) {
    const [query, setQuery] = useState("");
    const [group, setGroup] = useState({sector: "", category: "", state: "", everyone: false});
    const [results, setResults] = useState([]);
    const [total, setTotal] = useState(0);
    const [searched, setSearched] = useState(null);
    const [open, setOpen] = useState(false);
    const [active, setActive] = useState(0);
    const [selected, setSelected] = useState(null);
    const [form, setForm] = useState({kind: "general", interests: [], focus: "", topic: "",
      depth: "light", cadence: "weekly", months: 3});
    const [plan, setPlan] = useState(null);
    const [planning, setPlanning] = useState(false);
    const [busy, setBusy] = useState("");
    const [result, setResult] = useState(null);
    const [applied, setApplied] = useState(null);
    const [error, setError] = useState("");
    // Update requests: several actors, or any actor on a frequency.
    const [mode, setMode] = useState("one");
    const [picked, setPicked] = useState([]);
    const [useGroup, setUseGroup] = useState(false);
    const [reqPlan, setReqPlan] = useState(null);
    const [reqPlanning, setReqPlanning] = useState(false);
    const [saved, setSaved] = useState({requests: [], one_time: [], ready: true, loaded: false});
    const [notice, setNotice] = useState("");
    // Every update is a Light Refresh. A Deep Pull follows only when asked for,
    // and is offered only where GHUS verified this actor for this sector.
    const [deepPlan, setDeepPlan] = useState(null);
    const [wantDeep, setWantDeep] = useState(false);
    const [deepResult, setDeepResult] = useState(null);
    const topic = form.topic;
    const today = isoDate(new Date());
    const when = updateSchedule(today, form.cadence, form.months);
    const choiceProblem = updateChoiceProblem(form);
    // Every sector (the page's own Discovery options), so an actor with no
    // sector link yet can still be updated: facts are kept per sector, and
    // choosing it is a person's decision.
    const allSectors = sectors || [];
    const grouped = Boolean(group.sector || group.category || group.state);

    // Suggestions as the person types, within the chosen group; with a group
    // chosen and nothing typed, the group itself is listed. Last answer wins.
    useEffect(() => {
      const q = query.trim();
      if (q.length < 2 && !grouped) { setResults([]); setTotal(0); setSearched(null); return undefined; }
      let live = true;
      const timer = setTimeout(async () => {
        try {
          const body = await api(`/api/discovery/actors?${actorSearchParams(q, group)}`);
          if (live) {
            setResults(body.actors || []); setTotal(body.total || 0);
            setSearched(q); setActive(0); setError("");
          }
        } catch (err) { if (live) setError(err.message); }
      }, 200);
      return () => { live = false; clearTimeout(timer); };
    }, [query, group.sector, group.category, group.state, group.everyone]);

    function setGroupField(patch) {
      setGroup((g) => ({...g, ...patch})); setSelected(null); setResult(null); setOpen(true);
    }

    function onKey(e) {
      if (!results.length) return;
      if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((i) => (i + 1) % results.length); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => (i - 1 + results.length) % results.length); }
      else if (e.key === "Enter" || (e.key === "Tab" && open && query.trim())) {
        e.preventDefault(); choose(results[active] || results[0]);
      } else if (e.key === "Escape") { setOpen(false); }
    }

    function choose(actor) {
      if (mode === "several") {
        // Several actors: each choice is added to the list (at most 10).
        setPicked((list) => list.some((a) => a.actor_id === actor.actor_id) || list.length >= 10
          ? list : [...list, actor]);
        setUseGroup(false); setQuery(""); setOpen(false);
        setForm((f) => ({...f, topic: f.topic || (actor.sectors || [])[0] || group.sector || ""}));
        return;
      }
      setSelected(actor); setResult(null); setApplied(null); setError(""); setOpen(false);
      setQuery(actor.name);
      setWantDeep(false); setDeepResult(null);
      setForm((f) => ({...f, topic: (actor.sectors || [])[0] || group.sector || ""}));
    }

    function change(patch) {
      setForm((f) => ({...f, ...patch})); setResult(null); setApplied(null);
    }

    function toggle(name, id) {
      const list = form[name] || [];
      change({[name]: list.includes(id) ? list.filter((x) => x !== id) : [...list, id]});
    }

    // The request preview follows every choice. It is free: nothing is read
    // from the web and nothing is written; it only asks the backend what the
    // request would do. Last answer wins.
    useEffect(() => {
      if (!selected || !form.topic || choiceProblem) { setPlan(null); setPlanning(false); return undefined; }
      let live = true;
      setPlanning(true);
      const timer = setTimeout(async () => {
        try {
          const body = await api(`/api/discovery/actors/${selected.actor_id}/plan`, {
            method: "POST", body: JSON.stringify(updateRequestBody(form))});
          if (live) { setPlan(body); setError(""); }
        } catch (err) { if (live) { setPlan(null); setError(err.message); } }
        if (live) setPlanning(false);
      }, 350);
      return () => { live = false; clearTimeout(timer); };
    }, [selected?.actor_id, form.topic, form.kind, form.depth, form.focus, form.interests.join(",")]);

    // The Deep Pull on offer, when the gate permits it: its items and cost. Free.
    const deepPermitted = mode === "one" && Boolean(plan?.deep?.permitted);
    useEffect(() => {
      if (!deepPermitted || !selected) { setDeepPlan(null); setWantDeep(false); return undefined; }
      let live = true;
      api(`/api/discovery/actors/${selected.actor_id}/plan`, {method: "POST",
        body: JSON.stringify({...updateRequestBody(form), scope: "general", depth: "deep"})})
        .then((body) => { if (live) setDeepPlan(body); })
        .catch(() => { if (live) setDeepPlan(null); });
      return () => { live = false; };
    }, [deepPermitted, selected?.actor_id, form.topic]);
    const deepReady = deepPermitted && Boolean(deepPlan?.can_check);

    function draft(runNow = false) {
      return updateRequestDraft({mode, form, selected, picked, group, useGroup, today, runNow});
    }

    const requestReady = mode === "one" ? Boolean(selected && form.topic)
      : useGroup ? Boolean(group.sector) : picked.length > 0;

    async function refreshRequests() {
      try {
        const body = await api("/api/discovery/update-requests");
        setSaved({requests: body.requests || [], one_time: body.one_time || [],
          ready: body.ready !== false, loaded: true});
      } catch (err) { setSaved((v) => ({...v, loaded: true})); setError(err.message); }
    }
    useEffect(() => { refreshRequests(); }, []);
    // While a run is going, look again every 15 s; it records its result itself.
    useEffect(() => {
      if (!saved.requests.some(isRunning)) return undefined;
      const timer = setInterval(refreshRequests, 15000);
      return () => clearInterval(timer);
    }, [saved.requests.map((r) => (r.runs || [])[0]?.status).join(",")]);

    // Deep Enrichment is asked for one organization at a time and never scheduled.
    const canSchedule = requestReady && !choiceProblem && !when.problem && form.depth === "light";

    // The schedule preview: which actors the first run reads, its cost and its
    // runs. Free, like the one-actor preview. Last answer wins.
    useEffect(() => {
      if (!canSchedule) { setReqPlan(null); setReqPlanning(false); return undefined; }
      let live = true;
      setReqPlanning(true);
      const timer = setTimeout(async () => {
        try {
          const body = await api("/api/discovery/update-requests/plan", {
            method: "POST", body: JSON.stringify(draft())});
          if (live) { setReqPlan(body); setError(""); }
        } catch (err) { if (live) { setReqPlan(null); setError(err.message); } }
        if (live) setReqPlanning(false);
      }, 400);
      return () => { live = false; clearTimeout(timer); };
    }, [canSchedule, JSON.stringify(canSchedule ? draft() : null)]);

    const count = mode === "one" ? (selected ? 1 : 0) : useGroup ? (reqPlan?.matched ?? 0) : picked.length;

    // Save the schedule. Its first check is one interval from today, run by the
    // existing request runner; nothing runs when it is saved.
    async function saveSchedule() {
      if (!reqPlan?.can_save) return;
      if (!window.confirm(`Save this schedule?\n\n${updateSummary({form, count})}\n\nFirst check: `
        + `${formatDay(when.start_date)}. Last: by ${formatDay(when.end_date)}.`)) return;
      setBusy("save"); setError(""); setNotice("");
      try {
        await api("/api/discovery/update-requests", {method: "POST", body: JSON.stringify(draft())});
        setNotice(`Saved. The first check is on ${formatDay(when.start_date)}; you can pause, resume or `
          + "cancel it in the list below.");
        await refreshRequests();
      } catch (err) { setError(err.message); }
      setBusy("");
    }

    // Run Now: one organization is read and written now, then shown in Review,
    // in its own boxes; several are run once by the request runner.
    async function runNow() {
      if (mode === "one") { runOne(); return; }
      if (!window.confirm(`Check ${count} organization(s) now, once? It reads their own websites `
        + "and writes what changed; conflicts and changes to GHUS values go to Review.")) return;
      setBusy("run"); setError(""); setNotice("");
      try {
        const made = await api("/api/discovery/update-requests", {
          method: "POST", body: JSON.stringify(draft(true))});
        await api(`/api/discovery/update-requests/${made.subscription_id}/run`, {method: "POST"});
        setNotice("Started. The check appears in the list below when it finishes.");
        await refreshRequests();
      } catch (err) { setError(err.message); }
      setBusy("");
    }

    async function requestAction(request, action) {
      if (action === "cancel" && !window.confirm(`Cancel “${request.title}”? It will not run again.`)) return;
      if (action === "run" && !window.confirm(`Run “${request.title}” now? It reads the actors' `
        + "websites and writes what changed; conflicts go to Review.")) return;
      setBusy(`${action}:${request.subscription_id}`); setError("");
      try {
        await api(`/api/discovery/update-requests/${request.subscription_id}/${action}`, {method: "POST"});
        await refreshRequests();
      } catch (err) { setError(err.message); }
      setBusy("");
    }

    // Read its pages, write what they state through the GHUS fact writer, and
    // open its profile in Review: each finding in its own box. A value set by
    // GHUS, or a weaker reading of a recorded one, is never written over - it
    // waits under "Changes to Review" in the same profile.
    async function runOne() {
      const deep = wantDeep && deepReady;
      if (!selected || !(plan?.can_check || deep)) return;
      const lines = [`Update ${selected.name} now${deep ? ", then run a Deep Pull" : ""}?`, ""];
      if (deep) {
        lines.push(`Deep Pull: ${deepPlan.fields.map(boxLabel).join(", ")}. ${estimateLine(deepPlan.cost)}`, "");
      }
      lines.push("The agent reads its pages and writes what they state to the map, each with its "
        + "source; earlier values stay in the history. Values set by GHUS and conflicting readings "
        + "are not written over: they wait for you in Review. The result opens in Review.");
      if (!window.confirm(lines.join("\n"))) return;
      setBusy("check"); setError(""); setResult(null); setApplied(null); setDeepResult(null);
      let wrote = false;
      try {
        if (plan?.can_check) {
          const checked = await api(`/api/discovery/actors/${selected.actor_id}/check`, {
            method: "POST", body: JSON.stringify(updateRequestBody(form))});
          setResult(checked);
          if (checked.check_id && checked.writes) {
            setBusy("apply");
            setApplied(await api(`/api/discovery/actor-checks/${checked.check_id}/apply`,
              {method: "POST"}));
            wrote = true;
          }
        }
        if (deep) {
          setBusy("deep");
          const body = JSON.stringify({...updateRequestBody(form), scope: "general", depth: "deep"});
          const checked = await api(`/api/discovery/actors/${selected.actor_id}/check`, {method: "POST", body});
          const applied = checked.check_id && checked.writes
            ? await api(`/api/discovery/actor-checks/${checked.check_id}/apply`, {method: "POST"}) : null;
          setDeepResult({checked, applied});
          wrote = wrote || Boolean(applied);
        }
        if (wrote) openInReview(selected);
        refreshRequests();
      } catch (err) { setError(err.message); }
      setBusy("");
    }

    const where = (a) => [a.city, a.state].filter(Boolean).join(", ");

    // One form for one organization, picked organizations, or a group.
    function updateBuilder({sectorControl}) {
      const kind = UPDATE_KINDS.find((x) => x.id === form.kind);
      return html`<div class="update-builder">
        ${Field({label: "What to update", wide: true, children: html`
          <div class="discovery-segment">
            ${UPDATE_KINDS.map((x) => html`<button type="button" key=${x.id}
              aria-pressed=${form.kind === x.id}
              class=${form.kind === x.id ? "active" : ""} onClick=${() => change({kind: x.id})}>${x.label}</button>`)}
          </div>
          <small class="muted">${kind?.hint}</small>`})}

        ${Field({label: "What information are you interested in?", wide: true, children: html`
          <div class="chips">${INFORMATION_FOCUS.map((x) => html`<label key=${x.id} class=${"chip" + (form.interests.includes(x.id) ? " on" : "")}>
            <input type="checkbox" checked=${form.interests.includes(x.id)} onChange=${() => toggle("interests", x.id)}/>${x.label}</label>`)}</div>
          <small class="muted">${form.kind === "specific"
            ? "Only this information is checked, and only what each organization's type has."
            : form.interests.length ? "Checked first; everything else its type has is checked too."
              : "Optional: choose what to check first. Everything its type has is checked."}</small>`})}

        ${form.kind === "specific" && Field({label: "Specific topic or question (optional)", wide: true, children: html`
          <input value=${form.focus} maxLength="200" placeholder=${UPDATE_QUESTION_EXAMPLE}
            onInput=${(e) => change({focus: e.target.value})}/>`})}

        ${Field({label: "Sector", children: sectorControl})}

        ${Field({label: "How often should we check for updates?", children: html`
          <select value=${form.cadence} onChange=${(e) => change({cadence: e.target.value})}>
            ${UPDATE_FREQUENCIES.map((x) => html`<option key=${x.id} value=${x.id}>${x.label}</option>`)}
          </select>`})}

        ${Field({label: "For how long should we keep checking?", children: html`
          <select value=${form.months} onChange=${(e) => change({months: Number(e.target.value)})}>
            ${UPDATE_DURATIONS.map((d) => html`<option key=${d.months} value=${d.months}>${d.label}</option>`)}
          </select>`})}
      </div>`;
    }

    // The request preview in plain words, and the two actions.
    function requestPanel() {
      const organizations = mode === "one" ? selected?.name
        : useGroup ? (reqPlan ? `${reqPlan.matched} in this group` : "")
          : `${picked.length} chosen`;
      const cost = reqPlan?.cost || (plan?.cost && {...plan.cost, expected_usd: plan.cost.typical_usd});
      const deep = mode === "one" && wantDeep && deepReady;
      const ready = requestReady && !choiceProblem;
      return html`<div class="update-request">
        <div class=${"update-preview" + (reqPlanning || planning ? " loading" : "")}>
          <h4>Request preview ${(reqPlanning || planning) && html`<span class="muted">· updating…</span>`}</h4>
          ${choiceProblem && html`<p class="discovery-message error">${choiceProblem}</p>`}
          ${!choiceProblem && html`<p>${updateSummary({form, count, deep})}</p>`}
          <dl class="actor-now">
            <div><dt>Organizations</dt><dd>${organizations || "—"}</dd></div>
            <div><dt>Next run</dt><dd>${formatDay(when.start_date)}</dd></div>
            <div><dt>Ends</dt><dd>${formatDay(when.end_date)}${reqPlan ? ` · ${reqPlan.runs} ${reqPlan.runs === 1 ? "check" : "checks"}` : ""}</dd></div>
            <div><dt>Depth</dt><dd>${deep ? "Light Refresh, then Deep Pull" : "Light Refresh"}</dd></div>
            <div><dt>Estimated cost</dt><dd>${estimateLine(cost, reqPlan?.runs || 1) || "—"}</dd></div>
          </dl>
          ${when.problem && html`<p class="discovery-message error">${when.problem}</p>`}
          ${mode === "one" && plan?.access?.blocked && html`<p class="discovery-message warn">
            ${plan.access.blocked.plain} It is not tried again before ${formatDay(plan.access.blocked.retry_after)};
            this update reads other sources that name it instead.</p>`}
          ${mode === "one" && plan?.access?.fallback && html`<p class="muted">${plan.access.fallback}</p>`}
          ${mode === "one" && plan?.refusal && html`<p class="discovery-message error">${plan.refusal}</p>`}
          ${deepReady && html`<label class="update-deep">
            <input type="checkbox" checked=${wantDeep} onChange=${(e) => setWantDeep(e.target.checked)}/>
            <span><strong>Also run a Deep Pull</strong> — GHUS verified this organization for
              ${" " + (plan.topic?.name || "this sector")}. It reads ${deepPlan.fields.length} selected items:
              ${" " + deepPlan.fields.map(boxLabel).join(", ")}. ${estimateLine(deepPlan.cost)}
              <small class="muted">With Run now only; a saved schedule is a Light Refresh.</small></span>
          </label>`}
          ${mode === "one" && plan && !deepPermitted && plan.topic && html`<p class="muted">A Deep Pull becomes
            available here once GHUS verifies this organization for ${plan.topic.name} in Review.</p>`}
          ${mode === "one" && plan?.error && html`<p class="discovery-message error">${plan.error}</p>`}
          ${mode === "one" && plan?.fields && html`<details><summary>What will be checked: ${plan.fields.length} of ${plan.schema_size} items</summary>
            <p class="muted">${plan.fields.map(boxLabel).join(", ") || "Nothing needs checking."}</p>
            ${plan.skipped.length > 0 && html`<ul class="skipped">${plan.skipped.map((x) => html`<li key=${x.field}><strong>${boxLabel(x.field)}</strong> — ${x.reason}</li>`)}</ul>`}
            <p class="muted">Hubs: ${hubSummary(plan.hubs) || "—"}</p></details>`}
          ${mode === "several" && reqPlan && html`
            ${useGroup && html`<p class="muted">${`${reqPlan.matched} organization(s) match. Each check reaches up to `
              + `${reqPlan.options?.max_actors_per_run} of them, those with the most missing or out-of-date `
              + "information first; the others wait for a later check."}</p>`}
            ${reqPlan.waiting.length > 0 && html`<details><summary>${reqPlan.waiting.length} organization(s) not in the first check, and why</summary>
              <ul class="skipped">${reqPlan.waiting.map((x) => html`<li key=${x.actor_id}><strong>${x.name}</strong> — ${x.reason}</li>`)}</ul></details>`}`}
          ${reqPlan?.needs_migration && html`<p class="discovery-message error">${reqPlan.needs_migration}</p>`}
        </div>

        <div class="discovery-actions">
          <button class="btn" disabled=${!!busy || !ready || (mode === "one" ? (planning || !(plan?.can_check || deep))
            : !reqPlan?.chosen?.length)} onClick=${runNow}>
            ${busy === "check" ? "Reading its pages…" : busy === "apply" ? "Writing…"
              : busy === "deep" ? "Running Deep Pull…" : busy === "run" ? "Starting…" : "Run now"}</button>
          <button class="btn ghost" disabled=${!!busy || !canSchedule || reqPlanning || !reqPlan?.can_save}
            onClick=${saveSchedule}>${busy === "save" ? "Saving…" : "Save schedule"}</button>
        </div>
        ${busy === "check" && html`<p class="muted">Reading up to three of its own pages — about half a minute.</p>`}
      </div>`;
    }

    function updateRequestList() {
      if (!saved.loaded) return null;
      const rows = updateRunList(saved, allSectors);
      const hidden = (saved.requests || []).filter((r) => r.test_sector).length;
      return html`<div class="update-requests">
        <div class="update-requests-head">
          <h3>Update runs</h3>
          <button type="button" class="btn ghost" onClick=${refreshRequests}>Refresh</button>
        </div>
        ${!saved.ready && html`<p class="muted">Saved schedules need migration 570 on this database.
          One-time updates of one actor work without it.</p>`}
        ${!rows.length && html`<p class="muted">None yet. Update an organization above, or save a schedule.</p>`}
        ${rows.length > 0 && html`<ul class="update-run-list">${rows.map((row) => {
          const r = row.request;
          const live = r && (r.status === "active" || r.status === "paused");
          const doing = (action) => r && busy === `${action}:${r.subscription_id}`;
          return html`<li key=${row.key} class="update-run-row">
            <div class="update-run-name"><strong>${row.name}</strong>
              <span>${[row.actors !== row.name && row.actors, row.what].filter(Boolean).join(" · ")}</span></div>
            <div class="update-run-when">${formatDay(row.date)}<span>${row.schedule}</span></div>
            <div class="update-run-result">${row.result}</div>
            <span class=${"discovery-status " + row.status}>${row.statusLabel}</span>
            ${r && (r.status === "active" || live) && html`<div class="update-run-actions">
              ${isRunning(r) ? html`<button class="btn running" disabled>Running…</button>`
                : r.status === "active" && html`<button class="btn" disabled=${!!busy}
                onClick=${() => requestAction(r, "run")}>${doing("run") ? "Starting…" : runButtonLabel(r)}</button>`}
              ${r.status === "active" && html`<button class="btn ghost" disabled=${!!busy}
                onClick=${() => requestAction(r, "pause")}>Pause</button>`}
              ${r.status === "paused" && html`<button class="btn ghost" disabled=${!!busy}
                onClick=${() => requestAction(r, "resume")}>Resume</button>`}
              ${live && html`<button class="btn ghost danger" disabled=${!!busy}
                onClick=${() => requestAction(r, "cancel")}>Cancel</button>`}
            </div>`}
            ${row.runs.length > 0 && html`<details class="update-run-details">
              <summary>${row.runs.length === 1 ? "1 run" : `${row.runs.length} runs`}</summary>
              ${row.runs.map((run) => html`<div key=${run.collection_run_id} class="update-run">
                <p><strong>${formatDay(run.started_at)}</strong> · ${RUN_STATUS[run.status] || run.status}
                  · ${run.found_count ?? 0} new or updated · ${run.review_item_count ?? 0} to Review</p>
                ${run.status_reason && html`<p class="muted">${run.status_reason}</p>`}
                ${(run.actor_results || []).length > 0 && html`<ul class="skipped">${run.actor_results.map((a) =>
                  html`<li key=${a.actor_id} class=${a.ok ? "" : "warn"}>${actorResultLine(a)}</li>`)}</ul>`}
              </div>`)}
            </details>`}
          </li>`;
        })}</ul>`}
        ${hidden > 0 && html`<p class="muted">${hidden} test request(s) on inactive sectors are not listed.</p>`}
      </div>`;
    }

    return html`<section class="discovery-card actor-updates">
      <p class="muted actor-updates-lead">Pick an organization already on the map. The agent
        re-reads its own website and tells you what changed — nothing is written until you say so.</p>

      <div class="discovery-segment actor-mode" role="group" aria-label="How many actors">
        <button type="button" class=${mode === "one" ? "active" : ""}
          onClick=${() => { setMode("one"); setReqPlan(null); }}>One actor</button>
        <button type="button" class=${mode === "several" ? "active" : ""}
          onClick=${() => { setMode("several"); setSelected(null); setResult(null);
            setForm((f) => ({...f, depth: "light"})); }}>Several actors</button>
      </div>

      <div class="actor-group" role="group" aria-label="Which actors">
        <select aria-label="Sector" value=${group.sector} onChange=${(e) => setGroupField({sector: e.target.value})}>
          <option value="">Every sector</option>
          ${allSectors.map((x) => html`<option key=${x.code} value=${x.code}>${x.name}</option>`)}
        </select>
        <select aria-label="Type" value=${group.category} onChange=${(e) => setGroupField({category: e.target.value})}>
          <option value="">Every type</option>
          ${Object.entries(CATEGORY_LABELS).map(([code, label]) => html`<option key=${code} value=${code}>${label}</option>`)}
        </select>
        <select aria-label="State" value=${group.state} onChange=${(e) => setGroupField({state: e.target.value})}>
          <option value="">Every state</option>
          ${(states || []).map((x) => html`<option key=${x.code} value=${x.code}>${x.name}</option>`)}
        </select>
        <label class="actor-everyone"><input type="checkbox" checked=${group.everyone}
          onChange=${(e) => setGroupField({everyone: e.target.checked})}/> Include actors with no website</label>
      </div>

      ${mode === "several" && html`<div class="several-choice">
        <label class="actor-everyone"><input type="checkbox" checked=${useGroup} disabled=${!group.sector}
          onChange=${(e) => { setUseGroup(e.target.checked); setOpen(false); if (e.target.checked) setPicked([]); }}/>
          ${group.sector ? `Update the whole group (${groupCaption(total, total, group, allSectors, states)}), most gaps first`
            : "To update a whole group, choose its sector in the filters above"}</label>
        ${!useGroup && html`<div class="picked" role="group" aria-label="Chosen actors">
          ${picked.map((a) => html`<span key=${a.actor_id} class="chip on">${a.name}
            <button type="button" class="link" aria-label=${`Remove ${a.name}`}
              onClick=${() => setPicked((list) => list.filter((x) => x.actor_id !== a.actor_id))}>×</button></span>`)}
          ${!picked.length && html`<span class="muted">Or type below to add actors one by one (up to 10).</span>`}
        </div>`}
      </div>`}

      ${!(mode === "several" && useGroup) && html`<div class="actor-combo">
        <input class="actor-search" role="combobox" aria-expanded=${open && results.length > 0}
          aria-controls="actor-suggestions" aria-autocomplete="list" autocomplete="off"
          value=${query} placeholder=${grouped ? "Type to narrow this group…" : "Start typing a name or website — e.g. CPo, calwep"}
          onInput=${(e) => { setQuery(e.target.value); setSelected(null); setResult(null); setOpen(true); }}
          onFocus=${() => setOpen(true)} onKeyDown=${onKey}/>

        ${!selected && open && results.length > 0 && html`<div class="actor-suggest">
          <div class="actor-suggest-head">${groupCaption(total, results.length, group, allSectors, states)}
            <span class="muted">↑ ↓ to move · Enter to choose</span></div>
          <ul id="actor-suggestions" role="listbox" class="actor-results">
            ${results.map((a, i) => html`<li key=${a.actor_id} role="option" aria-selected=${i === active}>
              <button type="button" class=${i === active ? "active" : ""}
                onMouseEnter=${() => setActive(i)} onClick=${() => choose(a)}>
                <strong>${highlightParts(a.name, query).map((part, k) =>
                  part.match ? html`<mark key=${k}>${part.text}</mark>` : part.text)}</strong>
                <span>${[a.actor_category ? (CATEGORY_LABELS[a.actor_category] || a.actor_category.replaceAll("_", " ")) : "Unclassified",
                  where(a), (a.sectors || []).join(" / ")].filter(Boolean).join(" · ")}</span>
                <span class="actor-flags">
                  ${a.funding_signal && html`<em>funding on record</em>`}
                  ${a.recent_activity && html`<em>activity on record</em>`}
                  ${!a.website && html`<em class="warn">no website</em>`}
                </span>
              </button></li>`)}
          </ul>
        </div>`}
      </div>`}

      ${!selected && searched !== null && results.length === 0 && html`<div class="actor-none">
        <span>${searched ? `“${searched}” is not on the map${grouped ? " in this group" : ""}.` : "No actor on the map in this group."}</span>
        ${searched && html`<button type="button" class="btn ghost" onClick=${() => onFindNew(searched)}>Find it with Discovery</button>`}
      </div>`}

      ${selected && html`<div class="actor-selected">
        <div class="actor-head">
          <div>
            <h3>${selected.name}</h3>
            ${selected.website
              ? html`<a href=${selected.website} target="_blank" rel="noreferrer">${selected.website}</a>`
              : html`<span class="warn">No website on record</span>`}
          </div>
          <button type="button" class="link" onClick=${() => { setSelected(null); setResult(null); }}>Change</button>
        </div>

        <dl class="actor-now">
          <div><dt>Type</dt><dd>${selected.actor_category ? (CATEGORY_LABELS[selected.actor_category] || selected.actor_category.replaceAll("_", " ")) : "Unclassified"}</dd></div>
          <div><dt>Where</dt><dd>${where(selected) || "—"}</dd></div>
          <div><dt>Sectors</dt><dd>${(selected.sectors || []).map((code) =>
            (allSectors.find((x) => x.code === code) || {}).name || code).join(", ") || "Not linked yet"}</dd></div>
          <div><dt>Status</dt><dd>${plan?.actor?.status || selected.status || "—"}</dd></div>
          <div><dt>Last update</dt><dd>${plan?.last_update
            ? `${formatDay(plan.last_update.finished_at)} · ${formatUsd(plan.last_update.spent_usd)}`
            : "Never updated here"}</dd></div>
        </dl>

        ${updateBuilder({sectorControl: html`
            <select value=${topic} onChange=${(e) => change({topic: e.target.value})}>
              ${!(selected.sectors || []).length && html`<option value="">Choose a sector</option>`}
              ${(selected.sectors || []).length > 0 && html`<optgroup label="Its sectors">
                ${selected.sectors.map((code) => html`<option key=${code} value=${code}>
                  ${(allSectors.find((x) => x.code === code) || {}).name || code}</option>`)}
              </optgroup>`}
              <optgroup label=${(selected.sectors || []).length ? "Other sectors" : "Sectors"}>
                ${allSectors.filter((x) => !(selected.sectors || []).includes(x.code)).map((x) =>
                  html`<option key=${x.code} value=${x.code}>${x.name}</option>`)}
              </optgroup>
            </select>
            ${!(selected.sectors || []).length && html`<small class="muted">Not linked to a sector yet —
              facts are kept per sector, so choose the one this update is for.</small>`}`})}

        ${requestPanel()}
      </div>`}

      ${mode === "several" && html`<div class="actor-selected">
        ${updateBuilder({sectorControl: html`
          <select value=${topic} onChange=${(e) => change({topic: e.target.value})}>
            <option value="">${useGroup && group.sector ? "The group's sector" : "Each actor's own sector"}</option>
            ${allSectors.map((x) => html`<option key=${x.code} value=${x.code}>${x.name}</option>`)}
          </select>`})}
        ${requestPanel()}
      </div>`}

      ${error && html`<p class="discovery-message error">${error}</p>`}

      ${result && html`<div class="actor-result">
        <p class="actor-result-head"><strong>${applied ? "Written to the map" : "Nothing new to write"}</strong>
          · ${selected?.name} · ${result.topic?.name} · ${formatUsd(result.cost_usd)}</p>
        <p>${applied ? writtenLine(applied.counts)
          : result.note || "Its pages state nothing new, so nothing was written."}
          ${applied?.review_items > 0 ? ` · ${applied.review_items} change(s) wait for you in Review.` : ""}
          ${applied?.failed > 0 ? ` · ${applied.failed} box(es) could not be written; run it again to retry.` : ""}</p>
        <p class="muted">Read from: ${(result.pages_read || []).map((url, i) => html`${i ? " · " : ""}<a href=${url}
          target="_blank" rel="noreferrer">${url.replace(/^https?:\/\//, "")}</a>${
          sourceLabel(result.sources?.[url]) && ` (${sourceLabel(result.sources[url])})`}`)}</p>
        ${(result.attempts || []).length > 0 && html`<details class="update-attempts">
          <summary>Its own website was closed to the agent — what was tried</summary>
          <ul class="skipped">${result.attempts.map((attempt, i) => html`<li key=${i}>
            <strong>${attempt.url.replace(/^https?:\/\//, "")}</strong> — ${attempt.plain}</li>`)}</ul>
        </details>`}
        ${(result.related || []).some((r) => r.status === "not_on_map") && html`<p class="muted">Its pages name
          organizations not yet on the map: ${result.related.filter((r) => r.status === "not_on_map").map((r, i) =>
            html`${i ? ", " : ""}<button type="button" class="link" onClick=${() => onFindNew(r.name)}>${r.name}</button>`)}</p>`}
        ${applied && html`<div class="discovery-actions">
          <button class="btn" onClick=${() => openInReview(selected)}>Open in Review</button></div>`}
      </div>`}

      ${deepResult && html`<div class="actor-result">
        <p class="actor-result-head"><strong>Deep Pull</strong> · ${selected?.name}
          · ${deepResult.checked.topic?.name} · ${formatUsd(deepResult.checked.cost_usd)}</p>
        <p>${deepResult.checked.ok === false ? deepResult.checked.error
          : deepResult.applied ? writtenLine(deepResult.applied.counts)
            : "Its pages state none of the selected items, so nothing was written."}</p>
      </div>`}

      ${notice && html`<p class="discovery-message">${notice}</p>`}
      ${updateRequestList()}
    </section>`;
  }

  function EntityRequestForm({kind, options, today, onSaved}) {
    const [form, setForm] = useState(() => blankEntityForm(today, kind));
    const [touched, setTouched] = useState(false);
    const [preview, setPreview] = useState(null);
    const [working, setWorking] = useState("");
    const [message, setMessage] = useState(null);
    useEffect(() => { setForm(blankEntityForm(today, kind)); setPreview(null); setTouched(false); setMessage(null); }, [kind]);
    const set = (patch) => { setForm((f) => ({...f, ...patch})); setPreview(null); };
    const isEvent = kind === "event";
    const problems = entityDraftProblems(form, options);
    const shown = touched ? problems : {};
    const ready = options.entity_requests_ready !== false;

    function withTyped() {
      // A term still in the box counts, so "Preview" never ignores it.
      const term = form.focusInput.trim();
      return term && !form.focusTerms.includes(term)
        ? {...form, focusTerms: [...form.focusTerms, term].slice(0, options.max_focus_terms || 8), focusInput: ""}
        : form;
    }
    function addTerm() {
      const next = withTyped();
      if (next !== form) set({focusTerms: next.focusTerms, focusInput: ""});
    }
    function setDuration(id) {
      const preset = DURATION_PRESETS.find((p) => p.id === id);
      set({duration: id, endDate: preset?.months ? addMonths(form.startDate, preset.months) : form.endDate});
    }
    function toggleType(type) {
      set({eventTypes: form.eventTypes.includes(type)
        ? form.eventTypes.filter((t) => t !== type) : [...form.eventTypes, type]});
    }
    async function send(action) {
      setTouched(true);
      const draft = withTyped();
      if (Object.keys(entityDraftProblems(draft, options)).length) return;
      if (draft !== form) setForm(draft);
      const body = JSON.stringify(entityDraftPayload(draft));
      if (action === "run" && !window.confirm(`Run “${draft.title.trim()}” now? It searches the web live, `
          + `reads the pages it finds and sends what passes the quality checks to Review.`)) return;
      setWorking(action); setMessage(null);
      try {
        if (action === "preview") {
          setPreview(await api("/api/discovery/preview", {method: "POST", body}));
        } else {
          const created = await api("/api/discovery/requests", {method: "POST", body});
          if (action === "run") {
            await api(`/api/discovery/requests/${created.subscription_id}/run`, {method: "POST"});
          }
          setMessage({kind: "success", text: action === "run"
            ? `“${draft.title.trim()}” is running. Results go to Review under ${isEvent ? "Discovery Events" : "Discovery People"}, as their own named run.`
            : `Request “${draft.title.trim()}” saved.`});
          setForm(blankEntityForm(today, kind)); setTouched(false); setPreview(null);
          onSaved(action);
        }
      } catch (err) { setMessage({kind: "error", text: err.message}); }
      setWorking("");
    }

    const summary = entitySummary({...entityDraftPayload(form), start_date: form.startDate}, options);
    return html`<section class="discovery-card">
      ${!ready && html`<p class="discovery-message error">Event and people requests need migration 580 on this database.</p>`}
      ${message && html`<p class=${"discovery-message " + message.kind}>${message.text}</p>`}
      <div class="discovery-grid">
        <${Field} label="Request name" error=${shown.title} wide=${true}>
          <input value=${form.title} maxLength="160"
            placeholder=${isEvent ? "Water reuse conferences in the Great Lakes, spring 2027" : "Battery storage researchers in Texas"}
            onInput=${(e) => set({title: e.target.value})}/>
        <//>
        <${Field} label="Sector" error=${shown.sector}>
          <select value=${form.sector} onChange=${(e) => set({sector: e.target.value})}>
            <option value="">Choose a sector</option>
            <option value=${ANY_SECTOR}>Any sector</option>
            ${options.topics.map((t) => html`<option key=${t.code} value=${t.code}>${t.name}</option>`)}
          </select>
        <//>
        <${Field} label=${isEvent ? "Topic and sub-topics" : "Topic or expertise"} error=${shown.topic}>
          <div class="discovery-terms">
            ${form.focusTerms.map((term) => html`<span key=${term} class="discovery-term">${term}
              <button type="button" aria-label=${`Remove ${term}`} onClick=${() => set({focusTerms: form.focusTerms.filter((t) => t !== term)})}>×</button></span>`)}
            <input value=${form.focusInput} placeholder=${form.focusTerms.length ? "Add another" : (isEvent ? "e.g. water reuse" : "e.g. battery storage")}
              onInput=${(e) => set({focusInput: e.target.value})}
              onKeyDown=${(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addTerm(); } }}
              onBlur=${addTerm}/>
          </div>
        <//>
        ${!isEvent && html`<${Field} label="Institution or organization (optional)">
          <input value=${form.institution} maxLength="120" placeholder="e.g. University of Texas at Austin"
            onInput=${(e) => set({institution: e.target.value})}/>
        <//>
        <${Field} label="Professional role or specialization (optional)">
          <input value=${form.role} maxLength="120" placeholder="e.g. professor, program director"
            onInput=${(e) => set({role: e.target.value})}/>
        <//>`}
        <${Field} label="Geographic scope" error=${shown.area} wide=${true}>
          <div class="discovery-segment">
            ${[["region", "Region"], ["state", "State"], ["us", "All United States"]].map(([id, label]) => html`
              <button type="button" key=${id} class=${form.areaKind === id ? "active" : ""} onClick=${() => set({areaKind: id})}>${label}</button>`)}
          </div>
          ${form.areaKind === "region" && html`<select value=${form.region} onChange=${(e) => set({region: e.target.value})}>
            <option value="">Choose a region</option>
            ${options.regions.map((r) => html`<option key=${r.code} value=${r.code}>${r.name}</option>`)}
          </select>`}
          ${form.areaKind === "state" && html`<div class="discovery-inline">
            <select value=${form.state} onChange=${(e) => set({state: e.target.value})}>
              <option value="">Choose a state</option>
              ${options.states.map((x) => html`<option key=${x.code} value=${x.code}>${x.name}</option>`)}
            </select>
            <input value=${form.city} maxLength="120" placeholder="City (optional)" onInput=${(e) => set({city: e.target.value})}/>
          </div>`}
        <//>
        ${isEvent && html`<${Field} label="Event dates" error=${shown.dates}>
          <div class="discovery-inline">
            <input type="date" aria-label="From" value=${form.dateFrom} onInput=${(e) => set({dateFrom: e.target.value})}/>
            <input type="date" aria-label="To" value=${form.dateTo} min=${form.dateFrom} onInput=${(e) => set({dateTo: e.target.value})}/>
          </div>
          <small class="muted">Optional. Past events are kept as evidence; leave empty for any date.</small>
        <//>
        <${Field} label="Event type (optional)" error=${shown.types}>
          <div class="discovery-segment">
            ${(options.event_types || Object.keys(EVENT_TYPE_LABELS)).map((type) => html`
              <button type="button" key=${type} class=${form.eventTypes.includes(type) ? "active" : ""}
                onClick=${() => toggleType(type)}>${EVENT_TYPE_LABELS[type] || type}</button>`)}
          </div>
        <//>`}
        <${Field} label="Start">
          <input type="date" value=${form.startDate} min=${today} onInput=${(e) => set({startDate: e.target.value})}/>
        <//>
        <${Field} label="Frequency">
          <select value=${form.cadence} onChange=${(e) => set({cadence: e.target.value})}>
            ${options.cadences.map((c) => html`<option key=${c} value=${c}>${CADENCE_LABELS[c] || c}</option>`)}
          </select>
        <//>
        ${form.cadence !== "once" && html`<${Field} label="Duration" error=${shown.duration} wide=${true}>
          <div class="discovery-segment">
            ${DURATION_PRESETS.map((p) => html`<button type="button" key=${p.id} class=${form.duration === p.id ? "active" : ""} onClick=${() => setDuration(p.id)}>${p.label}</button>`)}
          </div>
          ${form.duration === "custom"
            ? html`<input type="date" value=${form.endDate} min=${form.startDate} max=${addMonths(form.startDate, 12)} onInput=${(e) => set({endDate: e.target.value})}/>`
            : html`<small class="muted">Ends ${formatDay(form.endDate)}</small>`}
        <//>`}
      </div>

      <p class="discovery-summary">${summary}</p>
      <p class="muted">Every ${isEvent ? "event" : "person"} found goes to Review; nothing is added to the map until a person verifies it.</p>

      ${preview && html`<div class="discovery-preview">
        <h4>${preview.queries.length} searches</h4>
        <ul>${preview.queries.map((q) => html`<li key=${q}>${q}</li>`)}</ul>
      </div>`}

      <div class="discovery-actions">
        <button class="btn ghost" disabled=${!!working || !ready} onClick=${() => send("preview")}>${working === "preview" ? "Preparing preview…" : "Preview searches"}</button>
        <button class="btn ghost" disabled=${!!working || !ready} onClick=${() => send("save")}>${working === "save" ? "Saving…" : "Save request"}</button>
        <button class="btn" disabled=${!!working || !ready} onClick=${() => send("run")}>${working === "run" ? "Starting…" : "Run now"}</button>
      </div>
    </section>`;
  }

  function RequestCard({request, options, busy, onAction, onRun}) {
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
    return html`<article class="discovery-request">
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
        <div><dt>Added to the map</dt><dd>${results.filter((r) => r.score_band === "auto_high").length}</dd></div>
        <div><dt>Sent to Review</dt><dd>${results.filter((r) => r.score_band === "review").length}</dd></div>` : html`
        <div><dt>Sent to Review</dt><dd>${results.length}</dd></div>
        <div><dt>Excluded</dt><dd>${excluded.length}</dd></div>`}
      </dl>
      ${last && last.status === "failed" && html`<p class="discovery-message error">Last run failed: ${last.status_reason || "no reason recorded"}</p>`}
      ${current && html`<p class="discovery-message running" role="status"><strong>Running</strong> ·
        ${runningLine(current)}. Searching, reading pages and scoring; results appear in Review when it finishes.</p>`}
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
                ? RESULT_LABELS[r.score_band] || r.score_band : "Sent to Review"}</span>
              ${r.fit_score != null && html`<span class="discovery-scores">${scoreLine(r)}</span>`}
              <dl class="discovery-detail">
                ${(entity === "actor" ? resultFacts(r) : entityResultFacts(r)).map(([label, value]) => html`<div key=${label}><dt>${label}</dt><dd>${value}</dd></div>`)}
              </dl>
              ${r.score_band === "review" && r.triage_reason && html`<p class="discovery-held"><strong>Why a person should look:</strong> ${r.triage_reason}</p>`}
              <a class="discovery-source" href=${r.url} target="_blank" rel="noopener noreferrer">Page read</a>
            </li>`)}</ul>`}
        ${excluded.length > 0 && html`<details class="discovery-excluded">
          <summary>Not added (${excluded.length}): ${exclusionSummary(excluded)}</summary>
          <ul>${excluded.map((x) => html`<li key=${x.url}>
            <strong>${x.name || x.url}</strong> <span class="muted">${EXCLUSION_LABELS[exclusionKind(x)]}</span>
            <p>${x.triage_reason || "No reason was recorded."}</p>
          </li>`)}</ul>
        </details>`}
        <h4>Runs</h4>
        ${runs.length === 0 ? html`<p class="muted">Not run yet.</p>` : html`<table class="discovery-runs">
          <thead><tr><th>Date</th><th>Result</th><th>Time</th><th>Pages found</th><th>Added</th><th>To Review</th><th>Spent</th><th>Per Relevant Actor</th><th></th></tr></thead>
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

  return function Discovery() {
    const today = isoDate(new Date());
    const [status, setStatus] = useState({loaded: false, configured: false});
    const [options, setOptions] = useState(null);
    const [requests, setRequests] = useState([]);
    const [view, setView] = useState("new");
    // What the new request finds. Organizations keep their form exactly.
    const [kind, setKind] = useState("actor");
    const [form, setForm] = useState(() => blankForm(today));
    // The fields are folded away: the brief is what a person writes, and the
    // panel below shows what it resolved to for anyone who wants to change it.
    const [showDetails, setShowDetails] = useState(false);
    const [touched, setTouched] = useState(false);
    const [preview, setPreview] = useState(null);
    const [busy, setBusy] = useState(false);
    const [working, setWorking] = useState("");
    const [message, setMessage] = useState(null);

    const set = (patch) => { setForm((f) => ({...f, ...patch})); setPreview(null); };

    async function load() {
      try {
        const s = await api("/api/discovery/status");
        setStatus({loaded: true, configured: !!s.configured});
        if (!s.configured) return;
        const [o, r] = await Promise.all([api("/api/discovery/options"), api("/api/discovery/requests")]);
        setOptions(o);
        setRequests(r.requests || []);
      } catch (err) {
        setStatus({loaded: true, configured: false});
        setMessage({kind: "error", text: err.message});
      }
    }
    useEffect(() => { load(); }, []);

    function setDuration(id) {
      const preset = DURATION_PRESETS.find((p) => p.id === id);
      set({duration: id, endDate: preset?.months ? addMonths(form.startDate, preset.months) : form.endDate});
    }
    function setStart(value) {
      const preset = DURATION_PRESETS.find((p) => p.id === form.duration);
      set({startDate: value, endDate: preset?.months ? addMonths(value, preset.months) : form.endDate});
    }
    function addFocus() {
      const term = form.focusInput.trim();
      if (!term) return;
      const max = options?.max_focus_terms || 8;
      if (form.focusTerms.length >= max || form.focusTerms.some((t) => t.toLowerCase() === term.toLowerCase())) {
        set({focusInput: ""});
        return;
      }
      set({focusTerms: [...form.focusTerms, term], focusInput: ""});
    }

    // Everything that is sent, summarised or validated runs on the RESOLVED
    // draft, so the brief and the panel can never disagree about what will run.
    const draft = resolveDraft(form, options || {});
    const problems = draftProblems(form, options);
    const valid = Object.keys(problems).length === 0;
    const shown = touched ? problems : {};

    async function runPreview() {
      setTouched(true);
      if (!valid) return;
      setBusy(true); setWorking("preview"); setMessage(null);
      try {
        setPreview(await api("/api/discovery/preview", {method: "POST", body: JSON.stringify(draftPayload(draft))}));
      } catch (err) { setMessage({kind: "error", text: err.message}); }
      setBusy(false); setWorking("");
    }

    async function create() {
      setTouched(true);
      if (!valid) return;
      setBusy(true); setWorking("create"); setMessage(null);
      try {
        await api("/api/discovery/requests", {method: "POST", body: JSON.stringify(draftPayload(draft))});
        setMessage({kind: "success", text: `Request “${draft.title.trim()}” created.`});
        setForm(blankForm(today)); setTouched(false); setPreview(null); setShowDetails(false);
        await load();
        setView("requests");
      } catch (err) { setMessage({kind: "error", text: err.message}); }
      setBusy(false); setWorking("");
    }

    // While anything is running (or was just started), refresh every 15 s.
    const [watchUntil, setWatchUntil] = useState(0);
    useEffect(() => {
      const active = requests.some(isRunning) || Date.now() < watchUntil;
      if (!active) return undefined;
      const timer = setInterval(() => { load(); }, 15000);
      return () => clearInterval(timer);
    }, [requests, watchUntil]);

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

    const summaryDraft = {
      ...draftPayload(draft),
      start_date: draft.startDate,
      region_code: draft.areaKind === "region" ? draft.region : null,
      state_code: draft.areaKind === "state" ? draft.state : null,
      city: draft.areaKind === "state" ? draft.city.trim() : null,
    };
    const activeCount = requests.filter((r) => r.status === "active" || r.status === "paused").length;

    return html`<div class="discovery-page">
      <div class="eyebrow">Discovery</div>
      <h1 class="hero-h">Ask the agent to find organizations, events or people.</h1>
      <p class="lead">Say what you are looking for. The agent searches only for that, and
        only where you ask; what it finds goes to Review.</p>

      ${message && html`<p class=${"discovery-message " + message.kind}>${message.text}</p>`}
      ${status.loaded && !status.configured && html`<p class="discovery-message error">Discovery requests are not available on this instance.</p>`}

      ${status.configured && options && html`
      <div class="subnav">
        <button class=${view === "new" ? "active" : ""} onClick=${() => setView("new")}>New request</button>
        <button class=${view === "requests" ? "active" : ""} onClick=${() => setView("requests")}>Requests (${activeCount})</button>
        <button class=${view === "actors" ? "active" : ""} onClick=${() => setView("actors")}>Actor updates</button>
      </div>

      ${view === "new" && html`<div class="discovery-segment discovery-kinds" role="group" aria-label="What to discover">
        ${DISCOVERY_KINDS.map((k) => html`<button type="button" key=${k.id}
          class=${kind === k.id ? "active" : ""} aria-pressed=${kind === k.id}
          onClick=${() => setKind(k.id)}>${k.label}</button>`)}
      </div>`}

      ${view === "new" && kind !== "actor" && html`<${EntityRequestForm} kind=${kind} options=${options}
        today=${today} onSaved=${async (action) => { await load(); if (action === "run") setWatchUntil(Date.now() + 20 * 60 * 1000); }}/>`}

      ${view === "new" && kind === "actor" && html`<section class="discovery-card">
        <${Field} label="What should the agent look for?" error=${shown.brief} wide=${true}>
          <textarea class="discovery-brief" rows="4" value=${form.brief}
            placeholder=${"Water utilities and water-technology organizations in Wisconsin.\nwastewater reuse\nphosphorus removal"}
            onInput=${(e) => set({brief: e.target.value})}></textarea>
          <small class="muted">
            <strong>First line:</strong> what you want, naming a sector.
            <strong>Each line after:</strong> one thing to search for, a few words.
          </small>
        <//>

        ${form.brief.trim() && html`<div class="discovery-resolved">
          <p>
            <strong>Sector:</strong> ${draft.sector === ANY_SECTOR ? "Any sector" : draft.sector
              ? (options.topics.find((t) => t.code === draft.sector) || {}).name || draft.sector
              : "none named yet"}
            · <strong>Searches:</strong> ${draft.focusTerms.length || "the sector name"}
          </p>
          ${draft.focusTerms.length > 0 && html`<div class="discovery-terms">
            ${draft.focusTerms.map((term) => html`<span key=${term}
              class=${"discovery-term" + (termIsTooLong(term) ? " long" : "")}>${term}</span>`)}
          </div>`}
          ${draft.focusTerms.some(termIsTooLong) && html`<small class="muted">
            A line marked in amber is long. Every word in it has to appear on the
            organization's own page for it to count, so short lines find more.
          </small>`}
        </div>`}

        <button type="button" class="discovery-disclose" aria-expanded=${showDetails}
          onClick=${() => setShowDetails(!showDetails)}>
          ${showDetails ? "Hide name, sector and sub-topics" : "Name, sector and sub-topics"}
        </button>

        ${showDetails && html`<div class="discovery-grid">
          <${Field} label="Request name" error=${shown.title} wide=${true}>
            <input value=${draft.title} maxLength="160" placeholder="Energy organizations in the Northeast"
              onInput=${(e) => set({title: e.target.value})}/>
          <//>
          <${Field} label="Sector" error=${shown.sector}>
            <select value=${draft.sector} onChange=${(e) => set({sector: e.target.value})}>
              <option value="">Choose a sector</option>
              <option value=${ANY_SECTOR}>Any sector</option>
              ${options.topics.map((t) => html`<option key=${t.code} value=${t.code}>${t.name}</option>`)}
            </select>
          <//>
          <${Field} label=${`Sub-topics (up to ${options.max_focus_terms})`}>
            <div class="discovery-terms">
              ${draft.focusTerms.map((term) => html`<span key=${term} class=${"discovery-term" + (termIsTooLong(term) ? " long" : "")}>${term}
                <button type="button" aria-label=${`Remove ${term}`} onClick=${() => set({focusTerms: draft.focusTerms.filter((t) => t !== term)})}>×</button></span>`)}
              <input value=${form.focusInput} placeholder=${form.focusTerms.length ? "Add another" : "e.g. battery storage"}
                onInput=${(e) => set({focusInput: e.target.value})}
                onKeyDown=${(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addFocus(); } }}
                onBlur=${addFocus}/>
            </div>
          <//>
        </div>`}

        <div class="discovery-grid">
          <${Field} label="Area" error=${shown.area} wide=${true}>
            <div class="discovery-segment">
              ${[["region", "Region"], ["state", "State"], ["us", "All United States"]].map(([id, label]) => html`
                <button type="button" key=${id} class=${draft.areaKind === id ? "active" : ""} onClick=${() => set({areaKind: id, areaTouched: true})}>${label}</button>`)}
            </div>
            ${draft.areaKind === "region" && html`<select value=${draft.region} onChange=${(e) => set({region: e.target.value, areaTouched: true})}>
              <option value="">Choose a region</option>
              ${options.regions.map((r) => html`<option key=${r.code} value=${r.code}>${r.name}</option>`)}
            </select>`}
            ${draft.areaKind === "state" && html`<div class="discovery-inline">
              <select value=${draft.state} onChange=${(e) => set({state: e.target.value, areaTouched: true})}>
                <option value="">Choose a state</option>
                ${options.states.map((s) => html`<option key=${s.code} value=${s.code}>${s.name}</option>`)}
              </select>
              <input value=${form.city} maxLength="120" placeholder="City (optional)" onInput=${(e) => set({city: e.target.value})}/>
            </div>`}
          <//>
          <${Field} label="Frequency">
            <select value=${form.cadence} onChange=${(e) => set({cadence: e.target.value})}>
              ${options.cadences.map((c) => html`<option key=${c} value=${c}>${CADENCE_LABELS[c] || c}</option>`)}
            </select>
          <//>
          <${Field} label="Start">
            <input type="date" value=${form.startDate} min=${today} onInput=${(e) => setStart(e.target.value)}/>
          <//>
          ${form.cadence !== "once" && html`<${Field} label="Duration" error=${shown.duration} wide=${true}>
            <div class="discovery-segment">
              ${DURATION_PRESETS.map((p) => html`<button type="button" key=${p.id} class=${form.duration === p.id ? "active" : ""} onClick=${() => setDuration(p.id)}>${p.label}</button>`)}
            </div>
            ${form.duration === "custom"
              ? html`<input type="date" value=${form.endDate} min=${form.startDate} max=${addMonths(form.startDate, 12)} onInput=${(e) => set({endDate: e.target.value})}/>`
              : html`<small class="muted">Ends ${formatDay(form.endDate)}</small>`}
          <//>`}
          <${Field} label="New organizations per run" error=${shown.cap}>
            <input type="number" min="1" max=${options.max_new_actors_per_run} value=${form.cap} onInput=${(e) => set({cap: e.target.value})}/>
          <//>
          <${Field} label="For each organization found" wide=${true}>
            <select value=${form.pullDepth || "light"} onChange=${(e) => set({pullDepth: e.target.value})}>
              ${(options.pull_depths || ["light", "none"]).map((d) => html`<option key=${d} value=${d}>${PULL_DEPTH_LABELS[d] || d}</option>`)}
            </select>
            <small class="muted">Deep Pull runs only after GHUS verifies an organization for a
              sector, from Review.</small>
          <//>
        </div>

        <p class="discovery-summary">${requestSummary(summaryDraft, options)}</p>

        ${preview && html`<div class="discovery-preview">
          <h4>First run ${formatDay(preview.first_run)} · ${preview.queries.length} searches</h4>
          <ul>${preview.queries.map((q) => html`<li key=${q}>${q}</li>`)}</ul>
        </div>`}

        <div class="discovery-actions">
          <button class="btn ghost" disabled=${busy} onClick=${runPreview}>${working === "preview" ? "Preparing preview…" : "Preview searches"}</button>
          <button class="btn" disabled=${busy} onClick=${create}>${working === "create" ? "Creating…" : "Create request"}</button>
        </div>
      </section>`}

      ${view === "actors" && html`<${ActorUpdates} sectors=${options.topics} states=${options.states}
        onFindNew=${(name) => { set({brief: name}); setView("new"); }}/>`}

      ${view === "requests" && html`<section class="discovery-list">
        ${requests.length === 0
          ? html`<p class="discovery-empty">No requests yet.</p>`
          : requests.map((r) => html`<${RequestCard} key=${r.subscription_id} request=${r} options=${options} busy=${busy} onAction=${onAction} onRun=${runNow}/>`)}
      </section>`}
      `}
    </div>`;
  };
}
