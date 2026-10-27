// Dashboard: what is running now, what finished since you last looked, and
// what every recent run took and found - each with a way to its results.
//
// Read only. It is built from the lists the Discovery and Data Feed pages
// already read (/api/discovery/requests, /api/discovery/update-requests,
// /api/datafeed/history); nothing here starts or changes a run.

import {
  OPEN_IN_REVIEW, STATUS_LABELS, durationLabel, formatUsd, reviewRunKey, runningLine,
} from "./discovery.js?v=20261027a";
import {usDateTime} from "./dates.js?v=20261027a";

export const DASHBOARD_UNSEEN = "ghus:dashboard-unseen";
const SEEN_KEY = "ghus.dashboard.seenAt";
const RUN_LABELS = {succeeded: "Completed", attention: "Completed with limits", failed: "Failed",
  running: "Running", stalled: "Stopped responding"};
const KIND_LABELS = {actor: "Discovery · Organizations", event: "Discovery · Events",
  person: "Discovery · People"};
const RUN_TYPES = {actor: "discovery_actors", event: "discovery_events",
  person: "discovery_people"};

function finishedAt(run) {
  if (run.finished_at) return run.finished_at;
  if (run.started_at && run.elapsed_seconds != null) {
    return new Date(new Date(run.started_at).getTime() + run.elapsed_seconds * 1000).toISOString();
  }
  return run.started_at || null;
}

/** Every run of every request and import, as one list, newest first. */
export function dashboardItems({requests = [], updates = {}, imports = []} = {}) {
  const items = [];
  for (const r of requests) {
    const entity = r.discovery_entity || "actor";
    for (const run of r.runs || []) {
      const state = run.status === "running" && run.stalled ? "stalled" : run.status;
      items.push({
        key: `run:${run.collection_run_id}`, kind: KIND_LABELS[entity] || "Discovery",
        title: r.title || "Discovery request", status: state,
        started_at: run.started_at, finished_at: state === "running" ? null : finishedAt(run),
        elapsed_seconds: run.elapsed_seconds, spent_usd: run.spent_usd,
        result: state === "running" ? runningLine(run)
          : [entity === "actor" && run.staged_count != null ? `${run.staged_count} added` : null,
            run.review_item_count != null ? `${run.review_item_count} to Review` : null,
            run.found_count != null ? `${run.found_count} pages found` : null]
            .filter(Boolean).join(" · "),
        review: reviewRunKey(run) ? {run_key: reviewRunKey(run), run_type: RUN_TYPES[entity]} : null,
      });
    }
  }
  for (const r of updates.requests || []) {
    for (const run of r.runs || []) {
      const state = run.status === "running" && run.stalled ? "stalled" : run.status;
      items.push({
        key: `run:${run.collection_run_id}`, kind: "Actor updates", title: r.title || "Update request",
        status: state, started_at: run.started_at,
        finished_at: state === "running" ? null : finishedAt(run),
        elapsed_seconds: run.elapsed_seconds, spent_usd: run.spent_usd,
        result: state === "running" ? runningLine(run)
          : `${run.found_count ?? 0} new or updated · ${run.review_item_count ?? 0} to Review`,
        review: {run_type: "actor_updates"},
      });
    }
  }
  for (const u of updates.one_time || []) {
    items.push({
      key: `update:${u.run_id}`, kind: "Actor updates", title: u.name || "Actor update",
      status: u.status, started_at: u.started_at, finished_at: u.started_at,
      spent_usd: u.spent_usd, result: u.topic_name || "", review: {run_type: "actor_updates"},
    });
  }
  for (const i of imports) {
    items.push({
      key: `import:${i.run_id}`, kind: "Data Feed import", title: i.import_name || "Import",
      status: "succeeded", started_at: i.uploaded_at, finished_at: i.uploaded_at,
      spent_usd: null,
      result: [`${i.staged ?? 0} staged`, i.counts?.pending ? `${i.counts.pending} awaiting Review` : null]
        .filter(Boolean).join(" · "),
      review: {run_key: `datafeed:${i.run_id}`, run_type: "data_feed"},
    });
  }
  return items.sort((a, b) => String(b.started_at || "").localeCompare(String(a.started_at || "")));
}

/** Completed since the last visit: the notifications. */
export function unseenCompleted(items, seenAt) {
  const since = seenAt ? new Date(seenAt).getTime() : 0;
  return items.filter(item => item.status !== "running" && item.finished_at
    && new Date(item.finished_at).getTime() > since);
}

/** The four figures at the top, over the last seven days. */
export function weekFigures(items, now = new Date()) {
  const from = now.getTime() - 7 * 86400000;
  const week = items.filter(item => item.started_at && new Date(item.started_at).getTime() >= from);
  return {
    running: items.filter(item => item.status === "running").length,
    completed: week.filter(item => ["succeeded", "attention"].includes(item.status)).length,
    failed: week.filter(item => ["failed", "stalled"].includes(item.status)).length,
    spent: week.reduce((sum, item) => sum + Number(item.spent_usd || 0), 0),
  };
}

export function statusText(status) {
  return RUN_LABELS[status] || STATUS_LABELS[status] || status;
}

export function whenText(value) {
  return value ? usDateTime(value) : "";
}

function readSeen() {
  try { return window.localStorage.getItem(SEEN_KEY); } catch { return null; }
}

function writeSeen(value) {
  try { window.localStorage.setItem(SEEN_KEY, value); } catch { /* a private window */ }
}

export function openResults(review) {
  if (!review) return;
  window.dispatchEvent(new CustomEvent(OPEN_IN_REVIEW, {detail: review}));
}

export function createDashboardPage({html, useState, useEffect}) {
  async function get(path) {
    const response = await fetch(path);
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    return response.json();
  }

  function Row({item, unseen}) {
    return html`<li class=${"dash-row " + item.status}>
      <div class="dash-main">
        <span class="dash-kind">${item.kind}${unseen ? html` <span class="dash-new">New</span>` : ""}</span>
        <strong>${item.title}</strong>
        <small>${[whenText(item.started_at), item.elapsed_seconds != null && item.status !== "running"
          ? durationLabel(item.elapsed_seconds) : null,
          item.spent_usd != null && item.status !== "running" ? formatUsd(item.spent_usd) : null,
          item.result].filter(Boolean).join(" · ")}</small>
      </div>
      <span class=${"discovery-status " + item.status}>${statusText(item.status)}</span>
      ${item.review && item.status !== "running" && html`<button class="btn ghost"
        onClick=${() => openResults(item.review)}>Show Results</button>`}
    </li>`;
  }

  return function Dashboard() {
    const [items, setItems] = useState(null);
    const [problems, setProblems] = useState([]);
    const [seenAt, setSeenAt] = useState(() => readSeen());

    async function load() {
      const failed = [];
      const [requests, updates, imports] = await Promise.all([
        get("/api/discovery/requests").then(r => r.requests || []).catch(() => { failed.push("Discovery"); return []; }),
        get("/api/discovery/update-requests").catch(() => { failed.push("Actor updates"); return {}; }),
        get("/api/datafeed/history").then(r => r.imports || []).catch(() => { failed.push("Data Feed"); return []; }),
      ]);
      const all = dashboardItems({requests, updates, imports});
      setItems(all);
      setProblems(failed);
      window.dispatchEvent(new CustomEvent(DASHBOARD_UNSEEN, {detail: {
        count: unseenCompleted(all, readSeen()).length}}));
    }
    useEffect(() => {
      load();
      // Every minute, and every 15 s while something runs.
      const timer = setInterval(load, (items || []).some(i => i.status === "running") ? 15000 : 60000);
      return () => clearInterval(timer);
    }, [(items || []).some(i => i.status === "running")]);

    function markSeen() {
      const now = new Date().toISOString();
      writeSeen(now);
      setSeenAt(now);
      window.dispatchEvent(new CustomEvent(DASHBOARD_UNSEEN, {detail: {count: 0}}));
    }

    if (!items) return html`<div class="discovery-page dashboard-page"><p class="muted">Loading the dashboard…</p></div>`;
    const running = items.filter(i => i.status === "running");
    const fresh = unseenCompleted(items, seenAt);
    const freshKeys = new Set(fresh.map(i => i.key));
    const figures = weekFigures(items);
    return html`<div class="discovery-page dashboard-page">
      <div class="eyebrow">Dashboard</div>
      <h1 class="hero-h">What is running, and what just finished.</h1>
      <p class="lead">Discovery requests, actor updates and Data Feed imports in one place. Every
        finished run opens in Review with Show Results.</p>
      ${problems.length > 0 && html`<p class="discovery-message error">Could not read: ${problems.join(", ")}.</p>`}
      <div class="dash-tiles">
        <div class="dash-tile"><strong>${figures.running}</strong><span>Running now</span></div>
        <div class="dash-tile"><strong>${figures.completed}</strong><span>Completed this week</span></div>
        <div class=${"dash-tile" + (figures.failed ? " warn" : "")}><strong>${figures.failed}</strong><span>Failed this week</span></div>
        <div class="dash-tile"><strong>${formatUsd(figures.spent) || "$0.00"}</strong><span>Spent this week</span></div>
      </div>

      <section class="discovery-card">
        <h3>Running now</h3>
        ${running.length === 0 ? html`<p class="muted">Nothing is running.</p>`
          : html`<ul class="dash-list">${running.map(item => html`<${Row} key=${item.key} item=${item}/>`)}</ul>`}
      </section>

      <section class="discovery-card">
        <div class="dash-head">
          <h3>Completed since your last visit (${fresh.length})</h3>
          ${fresh.length > 0 && html`<button class="btn ghost" onClick=${markSeen}>Mark all as seen</button>`}
        </div>
        ${fresh.length === 0 ? html`<p class="muted">No new completed runs.</p>`
          : html`<ul class="dash-list">${fresh.map(item => html`<${Row} key=${item.key} item=${item} unseen=${true}/>`)}</ul>`}
      </section>

      <section class="discovery-card">
        <h3>Recent runs</h3>
        ${items.length === 0 ? html`<p class="muted">No runs yet.</p>`
          : html`<ul class="dash-list">${items.slice(0, 25).map(item => html`<${Row} key=${item.key}
              item=${item} unseen=${freshKeys.has(item.key)}/>`)}</ul>`}
      </section>
    </div>`;
  };
}
