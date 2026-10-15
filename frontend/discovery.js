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

export function topicLabel(request, options) {
  const topics = options?.topics || [];
  const names = [
    ...(request.sector_codes || []).map((code) => topics.find((t) => t.code === code)?.name || code),
    ...(request.topic_ids || []).map((id) => topics.find((t) => t.topic_id === id)?.name || "Topic"),
  ];
  return names.join(", ") || "No topic";
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

export function draftProblems(form, options) {
  const problems = {};
  if (!form.title.trim()) problems.title = "Give the request a name.";
  if (!form.sector) problems.sector = "Choose a topic.";
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

    const problems = draftProblems(form, options);
    const valid = Object.keys(problems).length === 0;
    const shown = touched ? problems : {};

    async function runPreview() {
      setTouched(true);
      if (!valid) return;
      setBusy(true); setWorking("preview"); setMessage(null);
      try {
        setPreview(await api("/api/discovery/preview", {method: "POST", body: JSON.stringify(draftPayload(form))}));
      } catch (err) { setMessage({kind: "error", text: err.message}); }
      setBusy(false); setWorking("");
    }

    async function create() {
      setTouched(true);
      if (!valid) return;
      setBusy(true); setWorking("create"); setMessage(null);
      try {
        await api("/api/discovery/requests", {method: "POST", body: JSON.stringify(draftPayload(form))});
        setMessage({kind: "success", text: `Request “${form.title.trim()}” created.`});
        setForm(blankForm(today)); setTouched(false); setPreview(null);
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
      ...draftPayload(form),
      start_date: form.startDate,
      region_code: form.areaKind === "region" ? form.region : null,
      state_code: form.areaKind === "state" ? form.state : null,
      city: form.areaKind === "state" ? form.city.trim() : null,
    };
    const activeCount = requests.filter((r) => r.status === "active" || r.status === "paused").length;

    return html`<div class="discovery-page">
      <div class="eyebrow">Actor discovery</div>
      <h1 class="hero-h">Ask the agent to find organizations.</h1>
      <p class="lead">Choose a topic, an area, how long and how often. The agent searches only for what you ask.</p>

      ${message && html`<p class=${"discovery-message " + message.kind}>${message.text}</p>`}
      ${status.loaded && !status.configured && html`<p class="discovery-message error">Discovery requests are not available on this instance.</p>`}

      ${status.configured && options && html`
      <div class="subnav">
        <button class=${view === "new" ? "active" : ""} onClick=${() => setView("new")}>New request</button>
        <button class=${view === "requests" ? "active" : ""} onClick=${() => setView("requests")}>Requests (${activeCount})</button>
      </div>

      ${view === "new" && html`<section class="discovery-card">
        <div class="discovery-grid">
          <${Field} label="Request name" error=${shown.title} wide=${true}>
            <input value=${form.title} maxLength="160" placeholder="Energy organizations in the Northeast"
              onInput=${(e) => set({title: e.target.value})}/>
          <//>
          <${Field} label="Topic" error=${shown.sector}>
            <select value=${form.sector} onChange=${(e) => set({sector: e.target.value})}>
              <option value="">Choose a topic</option>
              ${options.topics.map((t) => html`<option key=${t.code} value=${t.code}>${t.name}</option>`)}
            </select>
          <//>
          <${Field} label=${`Sub-topics (up to ${options.max_focus_terms})`}>
            <div class="discovery-terms">
              ${form.focusTerms.map((term) => html`<span key=${term} class="discovery-term">${term}
                <button type="button" aria-label=${`Remove ${term}`} onClick=${() => set({focusTerms: form.focusTerms.filter((t) => t !== term)})}>×</button></span>`)}
              <input value=${form.focusInput} placeholder=${form.focusTerms.length ? "Add another" : "e.g. battery storage"}
                onInput=${(e) => set({focusInput: e.target.value})}
                onKeyDown=${(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addFocus(); } }}
                onBlur=${addFocus}/>
            </div>
          <//>
          <${Field} label="Area" error=${shown.area} wide=${true}>
            <div class="discovery-segment">
              ${[["region", "Region"], ["state", "State"], ["us", "Whole United States"]].map(([id, label]) => html`
                <button type="button" key=${id} class=${form.areaKind === id ? "active" : ""} onClick=${() => set({areaKind: id})}>${label}</button>`)}
            </div>
            ${form.areaKind === "region" && html`<select value=${form.region} onChange=${(e) => set({region: e.target.value})}>
              <option value="">Choose a region</option>
              ${options.regions.map((r) => html`<option key=${r.code} value=${r.code}>${r.name}</option>`)}
            </select>`}
            ${form.areaKind === "state" && html`<div class="discovery-inline">
              <select value=${form.state} onChange=${(e) => set({state: e.target.value})}>
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

      ${view === "requests" && html`<section class="discovery-list">
        ${requests.length === 0
          ? html`<p class="discovery-empty">No requests yet.</p>`
          : requests.map((r) => html`<${RequestCard} key=${r.subscription_id} request=${r} options=${options} busy=${busy} onAction=${onAction} onRun=${runNow}/>`)}
      </section>`}
      `}
    </div>`;
  };
}
