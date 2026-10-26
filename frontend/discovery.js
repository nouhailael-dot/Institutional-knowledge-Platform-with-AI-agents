// Discovery: ask the agent to find organizations on a topic, in an area, for a
// period, at a frequency. Actor discovery runs only for requests made here.
//
// The page never writes anything itself. Every call goes through
// /api/discovery/*, which hands it to the GHUS backend's own command.

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
  active: "Active",
  paused: "Paused",
  expired: "Finished",
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

export function isRunning(request) {
  return (request.runs || []).some((run) => run.status === "running");
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

export function formatDay(value) {
  if (!value) return "";
  const text = String(value).slice(0, 10);
  const [y, m, d] = text.split("-").map(Number);
  if (!y || !m || !d) return "";
  return new Date(y, m - 1, d).toLocaleDateString("en-US", {month: "short", day: "numeric", year: "numeric"});
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
export function topicLabel(request, options) {
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
  return `${when}: find ${topicLabel(request, options)} organizations in ${areaLabel(request, options)}${focus}.${cap}`;
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

// ------------------------------------------------------ specific actor updates

/** What an update covers (backend actor_updates.SCOPES). */
export const ACTOR_UPDATE_SCOPES = [
  {id: "general", label: "General profile", hint: "Every box its category has."},
  {id: "topic", label: "Specific topic", hint: "Every box, read for one sector — add words to steer it."},
  {id: "missing", label: "Missing information", hint: "Only the boxes that are still empty."},
  {id: "outdated", label: "Outdated information", hint: "Only values older than the freshness window."},
  {id: "specific", label: "Specific changes", hint: "Only the boxes you tick."},
];

export const UPDATE_DEPTHS = [
  {id: "light", label: "Light refresh", hint: "Its own home, About and one topic page."},
  {id: "deep", label: "Deep enrichment", hint: "Only for an actor GHUS verified for this exact sector."},
];

/** Change categories only reorder the boxes and steer which page is read. */
export const CHANGE_CATEGORY_OPTIONS = [
  {id: "research", label: "Research & programmes"},
  {id: "funding", label: "Funding & grants"},
  {id: "partnerships", label: "Partnerships"},
  {id: "products", label: "Products & technology"},
  {id: "organization", label: "Organisation"},
  {id: "geography", label: "Geography"},
  {id: "category", label: "Its category's own boxes"},
];

/** "Once" checks now; any other frequency saves a request the runner keeps. */
export const UPDATE_FREQUENCIES = [
  {id: "once", label: "Once"},
  {id: "weekly", label: "Weekly"},
  {id: "biweekly", label: "Every 2 weeks"},
  {id: "monthly", label: "Monthly"},
  {id: "quarterly", label: "Quarterly"},
];

export const UPDATE_DURATIONS = [
  {months: 1, label: "1 month"},
  {months: 3, label: "3 months"},
  {months: 6, label: "6 months"},
  {months: 12, label: "1 year"},
];

/** The boxes every category has: what a group's "Specific changes" may ask for. */
export const UPDATE_COMMON_BOXES = ["location", "why_matched", "recent_activity", "funding_signal",
  "international_connection", "um6p_ocp_connection"];

/**
 * What the page sends to plan or save an update request. One actor sends its
 * id; several send the picked ids, or the group (a sector is required: a
 * request never sweeps the whole map). Empty choices are left out.
 */
export function updateRequestDraft({mode, form, selected, picked = [], group = {}, useGroup,
  schedule}) {
  const draft = {...updateRequestBody(form), cadence: form.cadence};
  if (mode === "one") {
    draft.actor_ids = selected ? [selected.actor_id] : [];
    draft.max_actors_per_run = 1;
  } else if (useGroup) {
    draft.group = Object.fromEntries(Object.entries({
      sector: group.sector, category: group.category, state: group.state,
    }).filter(([, v]) => v));
    draft.max_actors_per_run = Number(schedule.maxActors);
  } else {
    draft.actor_ids = picked.map((a) => a.actor_id);
    draft.max_actors_per_run = Math.min(Number(schedule.maxActors), picked.length || 1);
  }
  draft.start_date = schedule.startDate;
  if (form.cadence !== "once") draft.end_date = addMonths(schedule.startDate, Number(schedule.months));
  draft.max_usd_per_run = Number(schedule.maxUsd);
  const title = String(schedule.title || "").trim();
  if (title) draft.title = title.slice(0, 160);
  return draft;
}

/** "Missing information · Water · Company · up to 5 actors a run · at most $1.50 a run". */
export function updateRequestScope(request, sectors = []) {
  const options = request.update_options || {};
  const scope = (ACTOR_UPDATE_SCOPES.find((s) => s.id === options.scope) || {}).label;
  const sectorName = (code) => (sectors.find((x) => x.code === code) || {}).name || code;
  const names = request.actor_names || [];
  const who = names.length
    ? (names.length <= 3 ? names.join(", ") : `${names.slice(0, 2).join(", ")} and ${names.length - 2} more`)
    : [(request.sector_codes || [])[0] && sectorName(request.sector_codes[0]),
      options.category && (CATEGORY_LABELS[options.category] || options.category), request.state_code]
      .filter(Boolean).join(" · ");
  return [scope, who, options.max_actors_per_run && `up to ${options.max_actors_per_run} `
    + `${options.max_actors_per_run === 1 ? "actor" : "actors"} a run`,
  request.max_usd_per_run != null && `at most ${formatUsd(request.max_usd_per_run)} a run`]
    .filter(Boolean).join(" · ");
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
  const parts = [["new", "new"], ["changed", "changed"], ["corroborated", "confirmed"],
    ["not_found", "not found"]].filter(([k]) => counts[k]).map(([k, w]) => `${counts[k]} ${w}`);
  if (result.review_items) parts.push(`${result.review_items} to Review`);
  if (!parts.length) parts.push("nothing new");
  return `${result.name}: ${parts.join(" · ")} · ${formatUsd(result.spent_usd)}`;
}

/** One word per finding, the way the backend (actor_updates.classify) means it. */
export const OUTCOME_LABELS = {
  new: "New",
  changed: "Changed",
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
  {id: "conflicts", label: "Conflicts requiring review"},
  {id: "confirmed", label: "Confirmed"},
  {id: "missing", label: "Missing"},
  {id: "no_change", label: "No change"},
];

/** What the page sends to plan or check one update. Empty choices are left out. */
export function updateRequestBody(form) {
  const body = {scope: form.scope, depth: form.depth};
  if (form.topic) body.topic = form.topic;
  if (form.scope === "specific" && form.fields?.length) body.fields = [...form.fields];
  if (form.categories?.length) body.categories = [...form.categories];
  const focus = String(form.focus || "").trim();
  if (focus && (form.scope === "topic" || form.scope === "specific")) body.focus = focus.slice(0, 200);
  return body;
}

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
export function draftPayload(form) {
  const payload = {
    title: form.title.trim(),
    sector_codes: form.sector ? [form.sector] : [],
    focus_terms: form.focusTerms,
    start_date: form.startDate,
    end_date: form.cadence === "once" ? form.startDate : form.endDate,
    cadence: form.cadence,
    max_new_actors_per_run: Number(form.cap),
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

function blankForm(today) {
  return {
    brief: "", areaTouched: false,
    title: "", sector: "", focusTerms: [], focusInput: "",
    areaKind: "region", region: "", state: "", city: "",
    startDate: today, duration: "3m", endDate: addMonths(today, 3),
    cadence: "weekly", cap: 10,
  };
}

/**
 * The form a Build the Map hand-off opens with: the proposed brief, monthly.
 * Unless the brief was edited, the sector and area the map resolved are set
 * explicitly, so a sub-topic that happens to name another sector or a place
 * cannot change them.
 */
export function handoffForm(handoff, today) {
  const form = {...blankForm(today), brief: handoff.brief || "", cadence: "monthly"};
  if (handoff.edited) return form;
  form.sector = handoff.sector_code || "";
  form.areaTouched = true;
  form.areaKind = handoff.state_code ? "state" : handoff.region_code ? "region" : "us";
  form.state = handoff.state_code || "";
  form.region = handoff.region_code || "";
  return form;
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
    const [form, setForm] = useState({scope: "general", topic: "", depth: "light",
      categories: [], fields: [], focus: "", cadence: "once"});
    const [plan, setPlan] = useState(null);
    const [planning, setPlanning] = useState(false);
    const [busy, setBusy] = useState("");
    const [result, setResult] = useState(null);
    const [applied, setApplied] = useState(null);
    const [show, setShow] = useState("all");
    const [error, setError] = useState("");
    // Update requests: several actors, or any actor on a frequency.
    const [mode, setMode] = useState("one");
    const [picked, setPicked] = useState([]);
    const [useGroup, setUseGroup] = useState(false);
    const [schedule, setSchedule] = useState({startDate: isoDate(new Date()), months: 3,
      maxActors: 5, maxUsd: 1.5, title: ""});
    const [reqPlan, setReqPlan] = useState(null);
    const [reqPlanning, setReqPlanning] = useState(false);
    const [saved, setSaved] = useState({requests: [], ready: true, loaded: false});
    const [notice, setNotice] = useState("");
    const topic = form.topic;
    const asRequest = mode === "several" || form.cadence !== "once";
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
      setForm((f) => ({...f, topic: (actor.sectors || [])[0] || group.sector || "", fields: []}));
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
      if (!selected || !form.topic) { setPlan(null); return undefined; }
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
    }, [selected?.actor_id, form.topic, form.scope, form.depth, form.focus,
      form.categories.join(","), form.fields.join(",")]);

    function draft() {
      return updateRequestDraft({mode, form, selected, picked, group, useGroup, schedule});
    }

    const requestReady = mode === "one" ? Boolean(selected && form.topic)
      : useGroup ? Boolean(group.sector) : picked.length > 0;

    async function refreshRequests() {
      try {
        const body = await api("/api/discovery/update-requests");
        setSaved({requests: body.requests || [], ready: body.ready !== false, loaded: true});
      } catch (err) { setSaved((v) => ({...v, loaded: true})); setError(err.message); }
    }
    useEffect(() => { refreshRequests(); }, []);
    // While a run is going, look again every 15 s; it records its result itself.
    useEffect(() => {
      if (!saved.requests.some(isRunning)) return undefined;
      const timer = setInterval(refreshRequests, 15000);
      return () => clearInterval(timer);
    }, [saved.requests.map((r) => (r.runs || [])[0]?.status).join(",")]);

    // The request preview: which actors the first run reads, its cost and its
    // runs. Free, like the one-actor preview. Last answer wins.
    useEffect(() => {
      if (!asRequest || !requestReady) { setReqPlan(null); return undefined; }
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
    }, [asRequest, requestReady, JSON.stringify(asRequest && requestReady ? draft() : null)]);

    async function saveRequest(runNow) {
      if (!reqPlan?.can_save) return;
      const runWords = runNow ? " and run it now (it reads the actors' websites and writes what changed)"
        : "";
      if (!window.confirm(`Save “${reqPlan.title}”${runWords}?\n\n${reqPlan.summary}`)) return;
      setBusy("save"); setError(""); setNotice("");
      try {
        const made = await api("/api/discovery/update-requests", {
          method: "POST", body: JSON.stringify(draft())});
        if (runNow) {
          await api(`/api/discovery/update-requests/${made.subscription_id}/run`, {method: "POST"});
        }
        setNotice(runNow ? "Saved and started. The run appears below when it finishes."
          : "Saved. It runs on its start date, and you can run it now from the list below.");
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

    async function check() {
      if (!selected || !plan?.can_check) return;
      setBusy("check"); setError(""); setResult(null); setApplied(null); setShow("all");
      try {
        setResult(await api(`/api/discovery/actors/${selected.actor_id}/check`, {
          method: "POST", body: JSON.stringify(updateRequestBody(form))}));
      } catch (err) { setError(err.message); }
      setBusy("");
    }

    async function apply() {
      if (!result?.check_id) return;
      if (!window.confirm(`Write ${result.writes} finding(s) for ${selected.name} to the map?\n\n`
        + "New and changed values are recorded with their source; the old values stay in the "
        + "history. Conflicts and changes to GHUS values go to Review instead.")) return;
      setBusy("apply"); setError("");
      try {
        setApplied(await api(`/api/discovery/actor-checks/${result.check_id}/apply`, {method: "POST"}));
      } catch (err) { setError(err.message); }
      setBusy("");
    }

    const where = (a) => [a.city, a.state].filter(Boolean).join(", ");

    function updateBuilder({schema, sectorControl, lightOnly}) {
      return html`<div class="update-builder">
        ${Field({label: "What to update", wide: true, children: html`
          <div class="discovery-segment">
            ${ACTOR_UPDATE_SCOPES.map((x) => html`<button type="button" key=${x.id} title=${x.hint}
              class=${form.scope === x.id ? "active" : ""} onClick=${() => change({scope: x.id})}>${x.label}</button>`)}
          </div>
          <small class="muted">${ACTOR_UPDATE_SCOPES.find((x) => x.id === form.scope)?.hint}</small>`})}

        ${Field({label: "Sector", children: sectorControl})}

        ${Field({label: "Depth", children: html`
          <div class="discovery-segment">
            ${UPDATE_DEPTHS.map((x) => html`<button type="button" key=${x.id} title=${x.hint}
              disabled=${lightOnly && x.id === "deep"}
              class=${form.depth === x.id ? "active" : ""} onClick=${() => change({depth: x.id})}>${x.label}</button>`)}
          </div>
          ${(lightOnly || asRequest) && html`<small class="muted">Saved and group requests use the Light
            refresh; Deep enrichment is one actor at a time.</small>`}`})}

        ${Field({label: "Frequency", children: html`
          <div class="discovery-segment">
            ${UPDATE_FREQUENCIES.map((x) => html`<button type="button" key=${x.id}
              class=${form.cadence === x.id ? "active" : ""}
              onClick=${() => change({cadence: x.id, ...(x.id !== "once" ? {depth: "light"} : {})})}>${x.label}</button>`)}
          </div>`})}

        ${(form.scope === "topic" || form.scope === "specific") && Field({label: "Look for (optional)", wide: true, children: html`
          <input value=${form.focus} maxLength="200" placeholder="e.g. desalination pilots, new DOE grants"
            onInput=${(e) => change({focus: e.target.value})}/>`})}

        ${form.scope === "specific" && schema && Field({label: "Boxes", wide: true, children: html`
          <div class="chips">${schema.map((key) => html`<label key=${key} class=${"chip" + (form.fields.includes(key) ? " on" : "")}>
            <input type="checkbox" checked=${form.fields.includes(key)} onChange=${() => toggle("fields", key)}/>${boxLabel(key)}</label>`)}</div>`})}

        ${Field({label: "Changes to look for first", wide: true, children: html`
          <div class="chips">${CHANGE_CATEGORY_OPTIONS.map((x) => html`<label key=${x.id} class=${"chip" + (form.categories.includes(x.id) ? " on" : "")}>
            <input type="checkbox" checked=${form.categories.includes(x.id)} onChange=${() => toggle("categories", x.id)}/>${x.label}</label>`)}</div>
          <small class="muted">${form.categories.length ? "Read first, and they steer which page is read; nothing outside its category is filled." : "All changes."}</small>`})}
      </div>`;
    }

    function setScheduleField(patch) { setSchedule((v) => ({...v, ...patch})); }

    // Schedule, limits, the request preview and Save - for several actors or a frequency.
    function requestPanel() {
      return html`<div class="update-request">
        <div class="update-builder">
          ${Field({label: "Start", children: html`<input type="date" value=${schedule.startDate}
            min=${isoDate(new Date())} onInput=${(e) => setScheduleField({startDate: e.target.value})}/>`})}
          ${form.cadence !== "once" && Field({label: "For", children: html`
            <select value=${schedule.months} onChange=${(e) => setScheduleField({months: Number(e.target.value)})}>
              ${UPDATE_DURATIONS.map((d) => html`<option key=${d.months} value=${d.months}>${d.label}</option>`)}
            </select>`})}
          ${mode === "several" && Field({label: "Actors per run", children: html`
            <input type="number" min="1" max="10" value=${schedule.maxActors}
              onInput=${(e) => setScheduleField({maxActors: e.target.value})}/>`})}
          ${Field({label: "Spend ceiling per run ($)", children: html`
            <input type="number" min="0.05" max="1.5" step="0.05" value=${schedule.maxUsd}
              onInput=${(e) => setScheduleField({maxUsd: e.target.value})}/>`})}
          ${Field({label: "Name (optional)", wide: true, children: html`
            <input value=${schedule.title} maxLength="160" placeholder=${reqPlan?.title || "Named for you from the choices above"}
              onInput=${(e) => setScheduleField({title: e.target.value})}/>`})}
        </div>

        ${(reqPlan || reqPlanning) && html`<div class=${"update-preview" + (reqPlanning ? " loading" : "")}>
          <h4>Request preview ${reqPlanning && html`<span class="muted">· updating…</span>`}</h4>
          ${reqPlan && html`
            <p>${reqPlan.summary}</p>
            <dl class="actor-now">
              <div><dt>Actors</dt><dd>${reqPlan.matched} match · ${reqPlan.chosen.length} on the first run</dd></div>
              <div><dt>Runs</dt><dd>${reqPlan.runs === 1 ? `Once, on ${formatDay(reqPlan.start_date)}`
                : `${reqPlan.runs} runs, ${formatDay(reqPlan.start_date)} to ${formatDay(reqPlan.end_date)}`}</dd></div>
              <div><dt>Cost per run</dt><dd>${reqPlan.cost.expected_usd != null
                ? `About ${formatUsd(reqPlan.cost.expected_usd)} from past reads; `
                : "No history yet; "}never more than ${formatUsd(reqPlan.max_usd_per_run)} (${formatUsd(reqPlan.cost.per_actor_cap_usd)} per actor at most)</dd></div>
              <div><dt>Searches</dt><dd>Each actor's own website, up to 3 pages; no web search.</dd></div>
            </dl>
            ${reqPlan.chosen.length > 0 && html`<ol class="skipped">${reqPlan.chosen.map((a) =>
              html`<li key=${a.actor_id}><strong>${a.name}</strong> — ${a.boxes} box(es) to read</li>`)}</ol>`}
            ${reqPlan.waiting.length > 0 && html`<details><summary>${reqPlan.waiting.length} actor(s) not on the first run, and why</summary>
              <ul class="skipped">${reqPlan.waiting.map((x) => html`<li key=${x.actor_id}><strong>${x.name}</strong> — ${x.reason}</li>`)}</ul></details>`}
            ${reqPlan.needs_migration && html`<p class="discovery-message error">${reqPlan.needs_migration}</p>`}`}
        </div>`}

        <div class="discovery-actions">
          <button class="btn ghost" disabled=${!!busy || reqPlanning || !reqPlan?.can_save} onClick=${() => saveRequest(false)}>
            ${busy === "save" ? "Saving…" : "Save request"}</button>
          <button class="btn" disabled=${!!busy || reqPlanning || !reqPlan?.can_save || !reqPlan?.chosen.length}
            onClick=${() => saveRequest(true)}>Save and run now</button>
        </div>
      </div>`;
    }

    function updateRequestList() {
      const requests = saved.requests || [];
      if (!saved.loaded) return null;
      return html`<div class="update-requests">
        <div class="update-requests-head">
          <h3>Update requests</h3>
          <button type="button" class="btn ghost" onClick=${refreshRequests}>Refresh</button>
        </div>
        ${!saved.ready && html`<p class="muted">Saved update requests need migration 570 on this database.
          One-time updates of one actor work without it.</p>`}
        ${saved.ready && !requests.length && html`<p class="muted">None yet. Choose several actors, or a
          frequency other than Once, to make one.</p>`}
        ${requests.map((r) => {
          const live = r.status === "active" || r.status === "paused";
          const doing = (action) => busy === `${action}:${r.subscription_id}`;
          return html`<article key=${r.subscription_id} class="discovery-request">
            <div class="discovery-request-head">
              <div>
                <h3>${r.title || "Update request"}</h3>
                <p>${updateRequestScope(r, allSectors)}</p>
                <p class="muted">${CADENCE_LABELS[r.cadence] || r.cadence} · ${formatDay(r.start_date)}${r.cadence !== "once"
                  ? ` to ${formatDay(r.end_date)}` : ""} · next run: ${live ? nextRunLabel(r) : "none"}</p>
              </div>
              <span class=${"discovery-status " + r.status}>${STATUS_LABELS[r.status] || r.status}</span>
            </div>
            ${isRunning(r) && html`<p class="discovery-message running">Running now: reading the actors' websites.
              Results appear here when it finishes.</p>`}
            <div class="discovery-actions">
              ${r.status === "active" && html`<button class="btn" disabled=${!!busy || isRunning(r)}
                onClick=${() => requestAction(r, "run")}>${doing("run") ? "Starting…" : "Run now"}</button>`}
              ${r.status === "active" && html`<button class="btn ghost" disabled=${!!busy} onClick=${() => requestAction(r, "pause")}>Pause</button>`}
              ${r.status === "paused" && html`<button class="btn ghost" disabled=${!!busy} onClick=${() => requestAction(r, "resume")}>Resume</button>`}
              ${live && html`<button class="btn ghost danger" disabled=${!!busy} onClick=${() => requestAction(r, "cancel")}>Cancel request</button>`}
            </div>
            ${(r.runs || []).length > 0 && html`<details class="update-runs"><summary>${r.runs.length} run(s) — last: ${formatDay(r.runs[0].started_at)}, ${{succeeded: "completed", attention: "completed with limits", failed: "failed", running: "running"}[r.runs[0].status] || r.runs[0].status}, ${formatUsd(r.runs[0].spent_usd)}</summary>
              ${r.runs.map((run) => html`<div key=${run.collection_run_id} class="update-run">
                <p><strong>${formatDay(run.started_at)}</strong> · ${{succeeded: "Completed", attention: "Completed with limits", failed: "Failed", running: "Running"}[run.status] || run.status}
                  · ${run.found_count ?? 0} new or changed · ${run.review_item_count ?? 0} to Review · ${formatUsd(run.spent_usd)}</p>
                ${run.status_reason && html`<p class="muted">${run.status_reason}</p>`}
                ${(run.actor_results || []).length > 0 && html`<ul class="skipped">${run.actor_results.map((a) =>
                  html`<li key=${a.actor_id} class=${a.ok ? "" : "warn"}>${actorResultLine(a)}</li>`)}</ul>`}
              </div>`)}
            </details>`}
          </article>`;
        })}
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

        ${updateBuilder({schema: plan?.schema, sectorControl: html`
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

        ${!asRequest && (plan || planning) && html`<div class=${"update-preview" + (planning ? " loading" : "")}>
          <h4>Request preview ${planning && html`<span class="muted">· updating…</span>`}</h4>
          ${plan && html`
            <p>${plan.summary}</p>
            <dl class="actor-now">
              <div><dt>Boxes to read</dt><dd>${plan.fields.length} of ${plan.schema_size}</dd></div>
              <div><dt>Searches</dt><dd>${plan.pages}</dd></div>
              <div><dt>Cost</dt><dd>${costLine(plan.cost)}</dd></div>
              <div><dt>Deep Pull</dt><dd>${plan.deep.permitted ? "Permitted" : "Not permitted"} — ${plan.deep.reason}</dd></div>
              <div><dt>Hubs</dt><dd>${hubSummary(plan.hubs) || "—"}</dd></div>
              <div><dt>Runs</dt><dd>Once, when you press Check. Nothing is written until you confirm.</dd></div>
            </dl>
            ${plan.refusal && html`<p class="discovery-message error">${plan.refusal}
              ${form.depth === "deep" && html` <button type="button" class="link" onClick=${() => change({depth: "light"})}>Use a Light refresh</button>`}</p>`}
            ${plan.skipped.length > 0 && html`<details><summary>${plan.skipped.length} box(es) skipped, and why</summary>
              <ul class="skipped">${plan.skipped.map((x) => html`<li key=${x.field}><strong>${boxLabel(x.field)}</strong> — ${x.reason}</li>`)}</ul></details>`}`}
        </div>`}

        ${!asRequest && html`<div class="discovery-actions">
          <button class="btn" disabled=${!!busy || planning || !plan?.can_check} onClick=${check}>
            ${busy === "check" ? "Reading its pages…" : "Check its website"}</button>
        </div>`}
        ${busy === "check" && html`<p class="muted">Reading up to three of its own pages — about half a minute.</p>`}
        ${asRequest && requestPanel()}
      </div>`}

      ${mode === "several" && html`<div class="actor-selected">
        ${updateBuilder({schema: UPDATE_COMMON_BOXES, sectorControl: html`
          <select value=${topic} onChange=${(e) => change({topic: e.target.value})}>
            <option value="">${useGroup && group.sector ? "The group's sector" : "Each actor's own sector"}</option>
            ${allSectors.map((x) => html`<option key=${x.code} value=${x.code}>${x.name}</option>`)}
          </select>`, lightOnly: true})}
        ${requestPanel()}
      </div>`}

      ${error && html`<p class="discovery-message error">${error}</p>`}

      ${result && html`<div class="actor-result">
        <p class="actor-result-head">
          <strong>${applied ? "Written" : "Checked"}</strong>
          · ${outcomeSummary(result.counts) || result.note || "nothing to report"}
          · ${result.topic?.name} · ${formatUsd(result.cost_usd)}
        </p>
        ${result.findings?.length > 0 && html`<div class="result-filters" role="group" aria-label="Show">
          <button type="button" class=${show === "all" ? "active" : ""} onClick=${() => setShow("all")}>All ${result.findings.length}</button>
          ${RESULT_GROUPS.filter((g) => result.counts?.[g.id]).map((g) => html`<button type="button" key=${g.id}
            class=${show === g.id ? "active" : ""} onClick=${() => setShow(g.id)}>${g.label} ${result.counts[g.id]}</button>`)}
        </div>
        <table class="actor-boxes">
          <thead><tr><th>Box</th><th>Result</th><th>On the map now</th><th>Its pages say</th><th>What writing does</th></tr></thead>
          <tbody>${findingsIn(result.findings, show).map((f) => {
            const done = applied?.results?.find((r) => r.field === f.field);
            return html`<tr key=${f.field}>
            <td>${boxLabel(f.field)}<small class="muted"> · ${f.topic}</small></td>
            <td><span class=${"outcome " + f.outcome}>${OUTCOME_LABELS[f.outcome] || f.outcome}</span></td>
            <td>${f.previous?.value != null ? factLine(f.previous.value) : "—"}
              ${f.previous?.date_read && html`<small> (read ${f.previous.date_read}${f.previous.set_by === "GHUS" ? ", set by GHUS" : ""})</small>`}</td>
            <td>${f.proposed ? html`${factLine(f.proposed.value)}<small>
                · ${f.proposed.confidence} confidence · read ${f.proposed.date_read}
                · <a href=${f.proposed.source_url} target="_blank" rel="noreferrer">source</a></small>`
              : (f.reason ? html`<small class="muted">${f.reason}</small>` : "—")}
              <small class="muted what-changed">${f.what_changed}</small></td>
            <td>${done ? (done.written ? html`<strong>Done</strong> — ${OUTCOME_LABELS[done.actual] || done.actual}`
                : html`<span class="warn">Failed: ${done.error}</span>`) : f.resolution}</td>
          </tr>`; })}</tbody>
        </table>`}
        <p class="muted">Pages read: ${(result.pages_read || []).map((url, i) => html`${i ? " · " : ""}<a href=${url} target="_blank" rel="noreferrer">${url.replace(/^https?:\/\//, "")}</a>`)}</p>
        ${(result.related?.length > 0 || result.related_error) && html`<div class="related">
          <h4>Organisations its pages name</h4>
          ${result.related_error && html`<p class="muted">${result.related_error}</p>`}
          <ul class="skipped">${(result.related || []).map((r) => html`<li key=${r.name}>
            ${relatedLine(r)}
            ${r.status === "ambiguous" && html`<small class="muted"> (${r.matches.map((m) => m.name).join(", ")})</small>`}
            ${r.status === "not_on_map" && html` <button type="button" class="link" onClick=${() => onFindNew(r.name)}>Find it with Discovery</button>`}
            ${r.source_url && html` <a href=${r.source_url} target="_blank" rel="noreferrer">source</a>`}
          </li>`)}</ul>
        </div>`}
        ${result.hubs && html`<p class="muted"><strong>Hubs:</strong> ${hubSummary(result.hubs)}</p>`}
        ${!applied && result.check_id && html`<div class="discovery-actions">
          <button class="btn" disabled=${!!busy || !result.writes} onClick=${apply}>
            ${busy === "apply" ? "Writing…" : `Write ${result.writes} finding(s) to the map`}</button>
          <span class="muted">Checked, nothing written yet. The check stays valid for 24 hours.</span>
        </div>`}
        ${applied && html`<p class="discovery-message">${applied.failed
          ? `${applied.failed} box(es) failed — press Retry to write only those.`
          : "Written through the GHUS fact writer and recorded as a run."}
          ${applied.review_items > 0 ? ` ${applied.review_items} item(s) now wait in Review → Map checks.` : ""}
          ${(applied.proposals || []).filter((p) => p.action === "proposed").map((p) => html`<br/>Proposed to Review:
            ${p.kind === "hub" ? `add to ${p.name}` : `link with ${p.name}`}`)}</p>
          ${applied.failed > 0 && html`<button class="btn ghost" disabled=${!!busy} onClick=${() => { setApplied(null); apply(); }}>Retry the failed boxes</button>`}`}
      </div>`}

      ${notice && html`<p class="discovery-message">${notice}</p>`}
      ${updateRequestList()}
    </section>`;
  }

  function RequestCard({request, options, busy, onAction, onRun}) {
    const [open, setOpen] = useState(false);
    const runs = request.runs || [];
    const results = request.results || [];
    const excluded = request.excluded || [];
    const last = runs[0];
    const live = request.status === "active" || request.status === "paused";
    return html`<article class="discovery-request">
      <div class="discovery-request-head">
        <div>
          <h3>${request.title || "Untitled request"}</h3>
          <p>${requestSummary(request, options)}</p>
        </div>
        <span class=${"discovery-status " + request.status}>${STATUS_LABELS[request.status] || request.status}</span>
      </div>
      <dl class="discovery-facts">
        <div><dt>Next run</dt><dd>${live ? nextRunLabel(request) : "None"}</dd></div>
        <div><dt>Runs so far</dt><dd>${runs.length}</dd></div>
        <div><dt>Added to the map</dt><dd>${results.filter((r) => r.score_band === "auto_high").length}</dd></div>
        <div><dt>Sent to Review</dt><dd>${results.filter((r) => r.score_band === "review").length}</dd></div>
      </dl>
      ${last && last.status === "failed" && html`<p class="discovery-message error">Last run failed: ${last.status_reason || "no reason recorded"}</p>`}
      ${isRunning(request) && html`<p class="discovery-message running">Running now: searching, reading pages and scoring. Results appear here when it finishes.</p>`}
      <div class="discovery-actions">
        ${request.status === "active" && html`<button class="btn" disabled=${busy || isRunning(request)} onClick=${() => onRun(request)}>${isRunning(request) ? "Running…" : "Run now"}</button>`}
        ${request.status === "active" && html`<button class="btn ghost" disabled=${busy} onClick=${() => onAction(request, "pause")}>Pause</button>`}
        ${request.status === "paused" && html`<button class="btn ghost" disabled=${busy} onClick=${() => onAction(request, "resume")}>Resume</button>`}
        ${live && html`<button class="btn ghost danger" disabled=${busy} onClick=${() => onAction(request, "cancel")}>Cancel request</button>`}
        ${(runs.length > 0 || results.length > 0) && html`<button class="btn ghost" onClick=${() => setOpen(!open)}>${open ? "Hide results" : "Show results"}</button>`}
      </div>
      ${open && html`<div class="discovery-results">
        <h4>Organizations found</h4>
        ${results.length === 0 ? html`<p class="muted">No organization has passed the quality checks yet.</p>`
          : html`<ul>${results.map((r) => html`<li key=${r.candidate_id}>
              <div><strong>${r.name || r.url}</strong>
                ${r.website && html` · <a href=${r.website} target="_blank" rel="noopener noreferrer">${r.website.replace(/^https?:\/\//, "").replace(/\/$/, "")}</a>`}</div>
              ${r.description && html`<p>${r.description}</p>`}
              <span class=${"discovery-band " + r.score_band}>${RESULT_LABELS[r.score_band] || r.score_band}</span>
              ${r.fit_score != null && html`<span class="discovery-scores">${scoreLine(r)}</span>`}
              <dl class="discovery-detail">
                ${resultFacts(r).map(([label, value]) => html`<div key=${label}><dt>${label}</dt><dd>${value}</dd></div>`)}
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
          <thead><tr><th>Date</th><th>Result</th><th>Pages found</th><th>Added</th><th>To Review</th><th>Spent</th><th>Per Relevant Actor</th></tr></thead>
          <tbody>${runs.map((run) => html`<tr key=${run.collection_run_id}>
            <td>${formatDay(run.started_at)}</td>
            <td>${{succeeded: "Completed", attention: "Completed with limits", failed: "Failed", running: "Running"}[run.status] || run.status}</td>
            <td>${run.found_count ?? ""}</td><td>${run.staged_count ?? ""}</td><td>${run.review_item_count ?? ""}</td>
            <td>${formatUsd(run.spent_usd)}</td><td>${costPerRelevantActor(run)}</td>
          </tr>`)}</tbody></table>`}
      </div>`}
    </article>`;
  }

  return function Discovery({handoff = null, onHandoffUsed = () => {}} = {}) {
    const today = isoDate(new Date());
    const [status, setStatus] = useState({loaded: false, configured: false});
    const [options, setOptions] = useState(null);
    const [requests, setRequests] = useState([]);
    const [view, setView] = useState("new");
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

    // A request proposed from a Build the Map result: open it, unsaved, for editing.
    useEffect(() => {
      if (!handoff) return;
      setForm(handoffForm(handoff, today));
      setView("new"); setShowDetails(true); setTouched(false); setPreview(null);
      if (status.configured) setMessage({kind: "running", text: "Proposed from your map. Check the "
        + "sector, area and sub-topics, then preview the searches before creating the request. "
        + "Discovery doesn't know the map's results, so its first run may send some of the same "
        + "organizations to Review again."});
      onHandoffUsed();
    }, [handoff]);

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
    const problems = draftProblems(form, options || {});
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
      <h1 class="hero-h">Ask the agent to find organizations, and keep them up to date.</h1>
      <p class="lead">Say what you are looking for in your own words. The agent searches
        only for that, and only where you ask.</p>

      ${message && html`<p class=${"discovery-message " + message.kind}>${message.text}</p>`}
      ${status.loaded && !status.configured && html`<p class="discovery-message error">Discovery requests are not available on this instance.</p>`}
      ${status.loaded && !status.configured && form.brief && html`<section class="discovery-card">
        <p class="muted">The request proposed from your map, kept here until Discovery is set up:</p>
        <pre class="discovery-brief">${form.brief}</pre>
      </section>`}

      ${status.configured && options && html`
      <div class="subnav">
        <button class=${view === "new" ? "active" : ""} onClick=${() => setView("new")}>New request</button>
        <button class=${view === "requests" ? "active" : ""} onClick=${() => setView("requests")}>Requests (${activeCount})</button>
        <button class=${view === "actors" ? "active" : ""} onClick=${() => setView("actors")}>Actor updates</button>
      </div>

      ${view === "new" && html`<section class="discovery-card">
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
            <strong>Sector:</strong> ${draft.sector
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
              ${[["region", "Region"], ["state", "State"], ["us", "Whole United States"]].map(([id, label]) => html`
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
