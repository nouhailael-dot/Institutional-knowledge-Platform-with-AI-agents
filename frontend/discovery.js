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

/** What a person can ask to refresh on one actor; ids are backend presets. */
export const ACTOR_UPDATE_SCOPES = [
  {id: "funding_activity", label: "Funding & recent activity"},
  {id: "connections", label: "International & UM6P/OCP links"},
  {id: "", label: "Every box"},
];

/** One word per outcome, the way the backend (actor_updates.compare) means it. */
export const OUTCOME_LABELS = {
  filled: "Filled",
  updated: "Updated",
  confirmed: "Confirmed",
  unchanged: "Kept",
  "not stated": "Not stated",
  refused: "Refused",
};

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
    return Object.values(v).filter((x) => x !== null && x !== "").join(" · ");
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

/** "1 updated · 1 kept", most consequential first. */
export function outcomeSummary(counts = {}) {
  return ["filled", "updated", "confirmed", "unchanged", "not stated", "refused"]
    .filter((key) => counts[key])
    .map((key) => `${counts[key]} ${OUTCOME_LABELS[key].toLowerCase()}`)
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
    const [scope, setScope] = useState("funding_activity");
    const [topic, setTopic] = useState("");
    const [busy, setBusy] = useState("");
    const [result, setResult] = useState(null);
    const [error, setError] = useState("");
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
      setSelected(actor); setResult(null); setError(""); setOpen(false);
      setQuery(actor.name);
      setTopic((actor.sectors || [])[0] || group.sector || "");
    }

    async function run(live) {
      if (!selected) return;
      if (live && !window.confirm(
        `Read ${selected.name}'s own pages now and write what changed to the map?`)) return;
      setBusy(live ? "live" : "preview"); setError(""); setResult(null);
      try {
        setResult(await api(`/api/discovery/actors/${selected.actor_id}/update`, {
          method: "POST", body: JSON.stringify({topic: topic || null, fields: scope, live}),
        }));
      } catch (err) { setError(err.message); }
      setBusy("");
    }

    const where = (a) => [a.city, a.state].filter(Boolean).join(", ");
    return html`<section class="discovery-card actor-updates">
      <p class="muted actor-updates-lead">Pick an organization already on the map. The agent
        re-reads its own website and tells you what changed — nothing is written until you say so.</p>

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

      <div class="actor-combo">
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
      </div>

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
          <div><dt>Funding on record</dt><dd>${factLine(selected.funding_signal) || "—"}</dd></div>
          <div><dt>Recent activity on record</dt><dd>${factLine(selected.recent_activity) || "—"}</dd></div>
        </dl>

        <div class="discovery-segment">
          ${ACTOR_UPDATE_SCOPES.map((s) => html`<button type="button" key=${s.id}
            class=${scope === s.id ? "active" : ""} onClick=${() => setScope(s.id)}>${s.label}</button>`)}
        </div>
        <label class="actor-topic">Update it for the sector
          <select value=${topic} onChange=${(e) => setTopic(e.target.value)}>
            ${!(selected.sectors || []).length && html`<option value="">Choose a sector</option>`}
            ${(selected.sectors || []).length > 0 && html`<optgroup label="Its sectors">
              ${selected.sectors.map((code) => html`<option key=${code} value=${code}>
                ${(allSectors.find((x) => x.code === code) || {}).name || code}</option>`)}
            </optgroup>`}
            <optgroup label=${(selected.sectors || []).length ? "Other sectors" : "Sectors"}>
              ${allSectors.filter((x) => !(selected.sectors || []).includes(x.code)).map((x) =>
                html`<option key=${x.code} value=${x.code}>${x.name}</option>`)}
            </optgroup>
          </select></label>
        ${!(selected.sectors || []).length && html`<small class="muted">Not linked to a sector
          on the map yet — choose the one this update is for.</small>`}

        <div class="discovery-actions">
          <button class="btn ghost" disabled=${!!busy || !selected.website || !topic} onClick=${() => run(false)}>
            ${busy === "preview" ? "Reading its pages…" : "Preview changes"}</button>
          <button class="btn" disabled=${!!busy || !selected.website || !topic} onClick=${() => run(true)}>
            ${busy === "live" ? "Updating…" : "Update the map"}</button>
        </div>
        ${busy && html`<p class="muted">Reading up to three of its own pages — about half a minute.</p>`}
      </div>`}

      ${error && html`<p class="discovery-message error">${error}</p>`}

      ${result && html`<div class="actor-result">
        <p class="actor-result-head">
          <strong>${result.mode === "live" ? "Updated" : "Preview"}</strong>
          · ${outcomeSummary(result.counts) || "nothing to report"}
          · ${result.topic?.name}
          ${result.mode === "live" && html` · ${result.written} written`}
          · $${Number(result.cost_usd || 0).toFixed(3)}
        </p>
        <table class="actor-boxes">
          <thead><tr><th>Box</th><th>Result</th><th>On record before</th><th>Its pages now say</th></tr></thead>
          <tbody>${result.boxes.map((b) => html`<tr key=${b.field}>
            <td>${boxLabel(b.field)}</td>
            <td><span class=${"outcome " + b.outcome.replace(" ", "-")}>${OUTCOME_LABELS[b.outcome] || b.outcome}</span></td>
            <td>${factLine(b.before) || "—"}${b.before_read && html`<small> (read ${b.before_read})</small>`}</td>
            <td>${factLine(b.after) || (b.reason ? html`<small class="muted">${b.reason}</small>` : "—")}
              ${b.source_url && html` <a href=${b.source_url} target="_blank" rel="noreferrer">source</a>`}</td>
          </tr>`)}</tbody>
        </table>
        <p class="muted">Pages read: ${(result.pages_read || []).map((url, i) => html`${i ? " · " : ""}<a href=${url} target="_blank" rel="noreferrer">${url.replace(/^https?:\/\//, "")}</a>`)}
          ${result.mode !== "live" && html`<br/>Nothing was written. “Update the map” writes the filled and updated boxes; a box its pages no longer mention keeps what is on record.`}</p>
      </div>`}
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

  return function Discovery() {
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
      <h1 class="hero-h">Ask the agent to find organizations, and keep them up to date.</h1>
      <p class="lead">Say what you are looking for in your own words. The agent searches
        only for that, and only where you ask.</p>

      ${message && html`<p class=${"discovery-message " + message.kind}>${message.text}</p>`}
      ${status.loaded && !status.configured && html`<p class="discovery-message error">Discovery requests are not available on this instance.</p>`}

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
