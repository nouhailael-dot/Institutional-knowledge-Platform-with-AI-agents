// Dashboard: your COMPASS workspace at a glance (GHUS Dashboard Design, 2026-11-02).
//
// Navigation only. Three counts, this month's spending, and your latest maps,
// requests and Directory contributions; every entry opens its own page at that
// item (Explore and Map, Monitor and Update > Requests, Ecosystem Directory).
// Nothing here starts, changes or expands anything.
//
// "Yours": there is no sign-in yet. Requests are yours by the email typed in
// Monitor and Update (requests with no email are everyone's, as on that page),
// Directory activity by the name typed in Review Results, and maps are the ones
// made on this computer.

import {NAVIGATE, formatUsd, requestStatus, visibleRequests} from "./discovery.js?v=20261102e";
import {usDate} from "./dates.js?v=20261102d";

export const DASHBOARD_UNSEEN = "ghus:dashboard-unseen";
export {NAVIGATE};
export const WINDOWS = [7, 30, 60, 90];
const SEEN_KEY = "ghus.dashboard.seenAt";
const REQUEST_SEEN_KEY = "ghus.dashboard.requestSeen";
const PANEL_SIZE = 5;
const DAY = 86400000;

export const STATE_LABELS = {
  completed: "Completed", pending_review: "Pending Review", in_progress: "In Progress",
  stopped: "Stopped", new_update: "New Update", scheduled: "Scheduled", paused: "Paused",
  attention: "Needs Attention", cancelled: "Cancelled",
};
const MAP_CATEGORIES = {organizations: "Organizations", people: "People", events: "Events"};
const RECORD_CATEGORIES = {actor: "Organization", person: "Person", event: "Event"};
const ACTIONS = {verified: "Verified", parked: "Parked", added: "Added", updated: "Updated"};
const MAP_RUNNING = ["running", "planning", "verifying", "queued"];

function time(value) {
  if (value == null || value === "") return 0;
  // Map times are epoch seconds; everything else is an ISO date.
  return typeof value === "number" ? value * 1000 : new Date(value).getTime() || 0;
}

export function withinDays(value, days, now = new Date()) {
  const t = time(value);
  return t > 0 && t >= now.getTime() - days * DAY;
}

/** "Oct 30": the short date the panels show. */
export function shortDate(value) {
  const t = time(value);
  return t ? new Date(t).toLocaleDateString("en-US", {month: "short", day: "numeric"}) : "";
}

/** "November 1–2, 2026": the 1st of this month to today. */
export function monthRangeLabel(now = new Date()) {
  const month = now.toLocaleDateString("en-US", {month: "long"});
  const day = now.getDate();
  return `${month} 1${day > 1 ? `–${day}` : ""}, ${now.getFullYear()}`;
}

function inMonth(value, now) {
  const t = time(value);
  if (!t) return false;
  const d = new Date(t);
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth();
}

/**
 * This month's spending: request runs, one-off organization updates and maps,
 * from the 1st. It starts again at $0 each month; earlier months stay in the
 * database (GET /api/dashboard/spending, for the admin).
 */
export function monthSpending({requests = [], updates = [], oneTime = [], maps = []} = {}, now = new Date()) {
  let total = 0;
  for (const r of [...requests, ...updates]) {
    for (const run of r.runs || []) if (inMonth(run.started_at, now)) total += Number(run.spent_usd || 0);
  }
  for (const u of oneTime) if (inMonth(u.started_at, now)) total += Number(u.spent_usd || 0);
  for (const m of maps) if (inMonth(m.created, now)) total += Number(m.spent_usd || 0);
  return Math.round(total * 10000) / 10000;
}

export function mapState(map) {
  if (Number(map.pending_review || 0) > 0) return "pending_review";
  if (map.status === "done") return "completed";
  if (MAP_RUNNING.includes(map.status)) return "in_progress";
  return "stopped";
}

export function mapName(map) {
  return String(map.description || "").split("\n")[0].trim() || "Untitled map";
}

/** Your latest maps in the window, newest first, at most five. */
export function recentMaps(maps = [], days = 30, now = new Date()) {
  return maps.filter(m => withinDays(m.created, days, now))
    .sort((a, b) => time(b.created) - time(a.created)).slice(0, PANEL_SIZE)
    .map(m => ({id: m.id, name: mapName(m), category: MAP_CATEGORIES[m.map_type] || "Organizations",
      date: m.created, state: mapState(m)}));
}

function lastActivity(request) {
  return (request.runs || [])[0]?.started_at || request.created_at;
}

function findings(run, kind) {
  return Number(run.review_item_count || 0) + Number(run.staged_count || 0)
    + (kind === "update" ? Number(run.found_count || 0) : 0);
}

/** Whether the latest finished run found something you have not opened yet. */
export function hasNewUpdate(request, kind, since = 0) {
  const done = (request.runs || []).find(run => run.status !== "running");
  if (!done || findings(done, kind) <= 0) return false;
  return time(done.finished_at || done.started_at) > since;
}

/**
 * Failed or stuck: the latest run needs a person. "Completed with limits" (a
 * page that would not load, a cap reached) still completed, so it is not here.
 */
export function needsAttention(request) {
  const latest = (request.runs || [])[0];
  if (!latest) return false;
  return latest.status === "failed" || (latest.status === "running" && latest.stalled);
}

export function requestState(request, kind, since = 0) {
  const status = requestStatus(request);
  if (status === "running") return "in_progress";
  if (needsAttention(request)) return "attention";
  if (hasNewUpdate(request, kind, since)) return "new_update";
  if (status === "active" && request.next_run) return "scheduled";
  if (status === "paused") return "paused";
  if (status === "cancelled") return "cancelled";
  if ((request.runs || []).length) return "completed";
  return status === "active" ? "scheduled" : "completed";
}

/**
 * Requests (monitoring and organization updates) as one list with their state.
 * ``seen`` maps a request id to when you last opened it from here; ``seenAt``
 * is the older "Mark all as seen". A request never opened counts findings of
 * the last seven days as new, so a first visit is not every finding ever made.
 */
export function requestRows({requests = [], updates = []} = {}, seen = {}, seenAt = null, now = new Date()) {
  const firstVisit = now.getTime() - 7 * DAY;
  const since = (id) => Math.max(time(seen[id] || seenAt), seen[id] ? 0 : firstVisit);
  return [
    ...requests.map(r => ({r, kind: "monitor"})),
    ...updates.map(r => ({r, kind: "update"})),
  ].map(({r, kind}) => ({
    id: r.subscription_id, name: r.title || (kind === "update" ? "Organization update" : "Monitoring request"),
    type: kind === "update" ? "Organization update" : "Topic monitoring",
    date: lastActivity(r), state: requestState(r, kind, since(r.subscription_id)),
    newUpdate: hasNewUpdate(r, kind, since(r.subscription_id)), attention: needsAttention(r),
  })).sort((a, b) => time(b.date) - time(a.date));
}

export function recentRequests(rows = [], days = 30, now = new Date()) {
  return rows.filter(row => withinDays(row.date, days, now)).slice(0, PANEL_SIZE);
}

/** The three counts at the top. They ignore the activity window. */
export function summaryCounts({maps = [], rows = []} = {}) {
  return {
    mapsPending: maps.filter(m => Number(m.pending_review || 0) > 0).length,
    newUpdates: rows.filter(row => row.newUpdate).length,
    attention: rows.filter(row => row.attention).length,
  };
}

export function directoryRows(activity = []) {
  return activity.slice(0, PANEL_SIZE).map(a => ({
    id: a.entity_id, kind: a.entity_type, name: a.name,
    category: RECORD_CATEGORIES[a.entity_type] || "Organization",
    action: `${ACTIONS[a.action] || "Updated"} by me`, date: a.decided_at,
  }));
}

export function navigate(detail) {
  window.dispatchEvent(new CustomEvent(NAVIGATE, {detail}));
}

function readJson(key, fallback) {
  try { return JSON.parse(window.localStorage.getItem(key) || "null") ?? fallback; } catch { return fallback; }
}

function readText(key) {
  try { return window.localStorage.getItem(key) || ""; } catch { return ""; }
}

function writeJson(key, value) {
  try { window.localStorage.setItem(key, JSON.stringify(value)); } catch { /* a private window */ }
}

export function whenText(value) {
  return value ? usDate(value) : "";
}

const icon = (html, d, size = 22) => html`<svg width=${size} height=${size} viewBox="0 0 24 24" fill="none"
  stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;

export function createDashboardPage({html, useState, useEffect}) {
  const ICONS = {
    clipboard: icon(html, html`<path d="M9 4.5h6v2.5H9z"/><path d="M15 5.5h2.5v15h-11v-15H9"/><path d="m9.5 13 2 2 3.5-4"/>`, 30),
    layers: icon(html, html`<path d="m12 4 8.5 4.5L12 13 3.5 8.5z"/><path d="m3.5 12.5 8.5 4.5 8.5-4.5M3.5 16.5 12 21l8.5-4.5"/>`, 30),
    alert: icon(html, html`<path d="M12 4 21 19.5H3z"/><path d="M12 10v4.5M12 17.2v.3"/>`, 30),
    coins: icon(html, html`<ellipse cx="12" cy="6.5" rx="7" ry="2.8"/><path d="M5 6.5v11c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8v-11M5 12c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8"/>`, 28),
    map: icon(html, html`<path d="M3.5 6.5 9 4l6 2.5L20.5 4v13.5L15 20l-6-2.5L3.5 20z"/><path d="M9 4v13.5M15 6.5V20"/>`),
    people: icon(html, html`<circle cx="9" cy="8.5" r="3"/><path d="M3.5 19c.6-3 2.8-4.5 5.5-4.5s4.9 1.5 5.5 4.5M15.5 6a3 3 0 0 1 0 5.6M17 14.8c1.8.5 3 1.9 3.5 4.2"/>`),
    calendar: icon(html, html`<rect x="4" y="5.5" width="16" height="14.5" rx="2"/><path d="M4 10h16M8.5 3.5v4M15.5 3.5v4"/>`),
    refresh: icon(html, html`<path d="M19.5 12a7.5 7.5 0 0 1-13.2 4.9M4.5 12a7.5 7.5 0 0 1 13.2-4.9"/><path d="M17.7 3.5v3.6h-3.6M6.3 20.5v-3.6h3.6"/>`),
    building: icon(html, html`<path d="M4.5 20.5h15M6.5 20.5V5.5h11v15M10 9h1M13 9h1M10 12.5h1M13 12.5h1M10.5 20.5V17h3v3.5"/>`),
    person: icon(html, html`<circle cx="12" cy="8.5" r="3.5"/><path d="M5 20c.8-3.7 3.6-5.5 7-5.5s6.2 1.8 7 5.5"/>`),
    arrow: icon(html, html`<path d="M7 17 17 7M9 7h8v8"/>`, 16),
    chevron: icon(html, html`<path d="m9.5 6 6 6-6 6"/>`, 18),
  };
  const MAP_ICONS = {Organizations: ICONS.map, People: ICONS.people, Events: ICONS.calendar};
  const RECORD_ICONS = {actor: ICONS.building, person: ICONS.person, event: ICONS.calendar};

  async function get(path) {
    const response = await fetch(path);
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    return response.json();
  }

  function Summary({icon: symbol, count, noun, label, tone}) {
    return html`<div class=${"dash-summary " + (tone || "")}>
      <span class="dash-summary-icon">${symbol}</span>
      <div><strong>${count == null ? "…" : `${count} ${noun}${count === 1 ? "" : "s"}`}</strong><span>${label}</span></div>
    </div>`;
  }

  function Entry({symbol, name, meta, state, onOpen}) {
    return html`<li><button class="dash-entry" type="button" onClick=${onOpen} disabled=${!onOpen}>
      <span class="dash-entry-icon">${symbol}</span>
      <span class="dash-entry-text"><strong>${name}</strong><small>${meta}</small></span>
      ${state && html`<span class=${"dash-pill " + state}>${STATE_LABELS[state]}</span>`}
      ${onOpen && html`<span class="dash-chevron">${ICONS.chevron}</span>`}
    </button></li>`;
  }

  function Panel({symbol, title, lead, empty, rows, footer, onFooter}) {
    return html`<section class="dash-panel">
      <header><span class="dash-panel-icon">${symbol}</span><div><h3>${title}</h3><p>${lead}</p></div></header>
      ${rows.length === 0 ? html`<p class="muted dash-empty">${empty}</p>`
        : html`<ul class="dash-entries">${rows}</ul>`}
      <button class="dash-footer" type="button" onClick=${onFooter}>${footer} ${ICONS.arrow}</button>
    </section>`;
  }

  return function Dashboard() {
    // Each list arrives on its own (requests take a while): null until then.
    const [data, setData] = useState({requests: null, updates: null, oneTime: null, maps: null});
    const [problems, setProblems] = useState({});
    const [days, setDays] = useState(30);
    const [activity, setActivity] = useState({loaded: false, rows: [], error: null});
    const [seen, setSeen] = useState(() => readJson(REQUEST_SEEN_KEY, {}));
    const [reviewer, setReviewer] = useState(() => readText("ghus.review.reviewer"));

    function load() {
      const email = readText("ghus.monitor.email");
      setReviewer(readText("ghus.review.reviewer"));
      const read = (name, path, apply) => get(path)
        .then(body => { setData(prev => ({...prev, ...apply(body)})); setProblems(prev => ({...prev, [name]: false})); })
        .catch(() => setProblems(prev => ({...prev, [name]: true})));
      read("maps", "/api/maps", body => ({maps: body.maps || []}));
      read("requests", "/api/discovery/requests", body => ({requests: visibleRequests(body.requests || [], email)}));
      read("organization updates", "/api/discovery/update-requests", body => ({
        updates: visibleRequests(body.requests || [], email), oneTime: body.one_time || []}));
    }
    const running = [...(data.requests || []), ...(data.updates || [])].some(r => requestStatus(r) === "running");
    useEffect(() => {
      load();
      // Every minute, and every 15 s while a request runs.
      const timer = setInterval(load, running ? 15000 : 60000);
      return () => clearInterval(timer);
    }, [running]);

    useEffect(() => {
      if (!reviewer.trim()) { setActivity({loaded: true, rows: [], error: null}); return; }
      const query = new URLSearchParams({reviewer: reviewer.trim(), days: String(days)});
      get(`/api/dashboard/directory-activity?${query}`)
        .then(r => setActivity({loaded: true, rows: r.activity || [], error: null}))
        .catch(() => setActivity({loaded: true, rows: [], error: "The Directory activity could not be read right now."}));
    }, [reviewer, days]);

    const requestsReady = data.requests !== null && data.updates !== null;
    const rows = requestRows({requests: data.requests || [], updates: data.updates || []},
      seen, readText(SEEN_KEY) || null);
    const counts = summaryCounts({maps: data.maps || [], rows});
    useEffect(() => {
      window.dispatchEvent(new CustomEvent(DASHBOARD_UNSEEN, {detail: {count: counts.newUpdates}}));
    }, [counts.newUpdates]);

    function openRequest(id) {
      const next = {...seen, [id]: new Date().toISOString()};
      setSeen(next);
      writeJson(REQUEST_SEEN_KEY, next);
      navigate({tab: "discovery", request_id: id});
    }

    const now = new Date();
    const allReady = requestsReady && data.maps !== null;
    const spent = monthSpending({requests: data.requests || [], updates: data.updates || [],
      oneTime: data.oneTime || [], maps: data.maps || []}, now);
    const failed = Object.keys(problems).filter(name => problems[name]);
    const maps = recentMaps(data.maps || [], days, now);
    const requests = recentRequests(rows, days, now);
    const records = directoryRows(activity.rows);
    return html`<div class="dashboard-page">
      <h1 class="hero-h">Dashboard</h1>
      <p class="lead dash-lead">Your COMPASS workspace at a glance.</p>
      ${failed.length > 0 && html`<p class="discovery-message error">Could not read: ${failed.join(", ")}.</p>`}

      <div class="dash-summaries">
        <${Summary} icon=${ICONS.clipboard} count=${data.maps === null ? null : counts.mapsPending} noun="map" label="Pending Review"/>
        <${Summary} icon=${ICONS.layers} count=${requestsReady ? counts.newUpdates : null} noun="request" label="New Updates"/>
        <${Summary} icon=${ICONS.alert} count=${requestsReady ? counts.attention : null} noun="request" label="Needing Attention"/>
      </div>

      <div class="dash-spending">
        <span class="dash-spending-icon">${ICONS.coins}</span>
        <div class="dash-spending-label"><strong>My Spending This Month</strong><span>${monthRangeLabel(now)}</span></div>
        <strong class="dash-spending-amount">${allReady ? formatUsd(spent) || "$0.00" : "…"}</strong>
      </div>

      <div class="dash-activity-head">
        <h2>My Recent Activity</h2>
        <div class="dash-windows" role="group" aria-label="Activity period">
          ${WINDOWS.map(n => html`<button key=${n} type="button" class=${days === n ? "active" : ""}
            aria-pressed=${days === n} onClick=${() => setDays(n)}>Last ${n} days</button>`)}
        </div>
      </div>

      <div class="dash-panels">
        <${Panel} symbol=${ICONS.map} title="Recent Maps" lead="My latest mapping requests (Explore and Map)"
          empty=${data.maps === null ? "Loading…" : `No maps in the last ${days} days on this computer.`}
          rows=${maps.map(m => html`<${Entry} key=${m.id} symbol=${MAP_ICONS[m.category]} name=${m.name}
            meta=${`${m.category} · ${shortDate(m.date)}`} state=${m.state}
            onOpen=${() => navigate({tab: "map", map_id: m.id})}/>`)}
          footer="View all maps" onFooter=${() => navigate({tab: "map"})}/>

        <${Panel} symbol=${ICONS.refresh} title="Recent Requests"
          lead="My latest update and monitoring requests (Monitor and Update)"
          empty=${requestsReady ? `No requests in the last ${days} days.` : "Loading requests…"}
          rows=${requests.map(r => html`<${Entry} key=${r.id} symbol=${ICONS.refresh} name=${r.name}
            meta=${`${r.type} · ${shortDate(r.date)}`} state=${r.state} onOpen=${() => openRequest(r.id)}/>`)}
          footer="View all requests" onFooter=${() => navigate({tab: "discovery", view: "requests"})}/>

        <${Panel} symbol=${ICONS.building} title="Recent Directory Activity"
          lead="My latest contributions to the Ecosystem Directory"
          empty=${!reviewer.trim() ? "Type your name in Review Results to see what you verified, parked, added or updated."
            : activity.error || (activity.loaded ? `Nothing in the last ${days} days.` : "Loading…")}
          rows=${records.map((r, i) => html`<${Entry} key=${`${r.id}:${i}`} symbol=${RECORD_ICONS[r.kind] || ICONS.building}
            name=${r.name} meta=${`${r.category} · ${r.action}`}
            onOpen=${r.id ? () => navigate({tab: "browse", record: {kind: r.kind, id: r.id}}) : null}/>`)}
          footer="Open Directory" onFooter=${() => navigate({tab: "browse"})}/>
      </div>
    </div>`;
  };
}
