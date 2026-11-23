// Pending Deletion (Phase 6, GHUS policy of 17 Nov 2026).
//
// A record deleted from the Ecosystem Directory waits 30 days before the
// scheduled cleanup removes it permanently. Admins and Editors/Reviewers see
// those records in a compact Dashboard card and on the Pending Deletion page,
// where they can restore one before its deadline. This is separate from Review
// Results: a deletion is not a rejection, and the record's verification history
// is untouched. Data and actions: GET /api/review/deleted and
// POST /api/review/deleted/{id}/restore (the backend's approved writer).

export const RETENTION_DAYS = 30;
export const PAGE_TITLE = "Pending Deletion";
export const PAGE_TAB = "deletions";
export const PERMISSION = "records.delete_permanent";
const KIND = {actor: "Organization", person: "Person", event: "Event", hub: "Hub"};
const URGENT_DAYS = 3;

const day = value => {
  const d = new Date(value);
  return isNaN(d) ? "" : d.toLocaleDateString("en-US", {month: "short", day: "numeric", year: "numeric"});
};

export function kindLabel(type) { return KIND[type] || "Record"; }

export function daysLeftLabel(days) {
  const n = Number(days);
  if (!Number.isFinite(n) || n <= 0) return "Removal due now";
  return n === 1 ? "1 day left" : `${n} days left`;
}

export const isUrgent = days => Number(days) <= URGENT_DAYS;
export const canRestore = row => Number(row?.days_remaining) > 0;

// Soonest deadline first; ties by name.
export function byDeadline(rows = []) {
  return [...rows].sort((a, b) => (Number(a.days_remaining) - Number(b.days_remaining))
    || String(a.purge_after || "").localeCompare(String(b.purge_after || ""))
    || String(a.name || "").localeCompare(String(b.name || "")));
}

// The Dashboard card: how many are pending, and the (up to) three nearest their deadline.
export function widgetSummary(rows = [], limit = 3) {
  const sorted = byDeadline(rows);
  return {count: rows.length, soonest: sorted.slice(0, limit)};
}

export function filterDeleted(rows = [], {entity_type = "all", search = ""} = {}) {
  const q = String(search || "").trim().toLowerCase();
  return rows.filter(r => (entity_type === "all" || r.entity_type === entity_type)
    && (!q || [r.name, r.reason, r.deleted_by].join(" ").toLowerCase().includes(q)));
}

export async function readDeleted() {
  const res = await fetch("/api/review/deleted");
  const d = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(d.detail || "Could not read the records pending deletion.");
  return d.deleted || [];
}

async function restoreDeleted(row) {
  const res = await fetch(`/api/review/deleted/${encodeURIComponent(row.deletion_id)}/restore`, {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({confirm: true})});
  const d = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((d.detail && d.detail.message) || d.detail || "Could not restore it.");
  return d;
}

export function createPendingDeletion({html, useEffect, useState}) {
  function useDeleted() {
    const [state, setState] = useState({loaded: false, rows: [], error: null});
    const [version, setVersion] = useState(0);
    useEffect(() => {
      let live = true;
      readDeleted().then(rows => live && setState({loaded: true, rows, error: null}))
        .catch(e => live && setState({loaded: true, rows: [], error: String(e.message || e)}));
      return () => { live = false; };
    }, [version]);
    return [state, () => setVersion(v => v + 1)];
  }

  // Compact Dashboard card (Admins and Editors/Reviewers; the caller checks the permission).
  function PendingDeletionWidget({onNavigate}) {
    const [state] = useDeleted();
    const {count, soonest} = widgetSummary(state.rows);
    return html`<div class="card pad dash-card pending-deletion-card" aria-label=${PAGE_TITLE}>
      <div class="dash-card-head"><strong>${PAGE_TITLE}${state.loaded && !state.error ? html` <span
        class=${"pd-count" + (count ? " has" : "")}>${count}</span>` : ""}</strong>
        <button class="example" type="button" onClick=${() => onNavigate(PAGE_TAB)}>View all</button></div>
      ${!state.loaded ? html`<p class="hint pd-line">Loading…</p>`
        : state.error ? html`<p class="hint pd-line">${state.error}</p>`
        : !count ? html`<p class="hint pd-line">No records are waiting for permanent removal.</p>`
        : html`<ul class="dash-list pd-list">${soonest.map(r => html`<li key=${r.deletion_id}>
            <span class="pd-name">${r.name}</span>
            <span class="hint"> · ${kindLabel(r.entity_type)}</span>
            <span class=${"pd-days" + (isUrgent(r.days_remaining) ? " urgent" : "")}>${daysLeftLabel(r.days_remaining)}</span>
          </li>`)}</ul>
          ${count > soonest.length && html`<p class="hint pd-line">and ${count - soonest.length} more</p>`}`}
    </div>`;
  }

  // The dedicated view, opened from the card's View all.
  function PendingDeletionPage({onNavigate}) {
    const [state, reload] = useDeleted();
    const [filters, setFilters] = useState({entity_type: "all", search: ""});
    const [confirming, setConfirming] = useState(null);
    const [busy, setBusy] = useState(false);
    const [message, setMessage] = useState(null);

    async function restore(row) {
      if (busy) return;
      setBusy(true); setMessage(null);
      try {
        await restoreDeleted(row);
        setMessage({ok: true, text: `${row.name} was restored. It is back in the Ecosystem Directory as it was.`});
        setConfirming(null); reload();
      } catch (e) {
        setMessage({ok: false, text: String(e.message || e)});
      } finally { setBusy(false); }
    }

    const rows = byDeadline(filterDeleted(state.rows, filters));
    return html`<div class="accounts-page pending-deletion-page">
      <button class="backlink" type="button" onClick=${() => onNavigate("dashboard")}>← Dashboard</button>
      <h1 class="hero-h" style=${{marginBottom: "4px"}}>${PAGE_TITLE}</h1>
      <p class="hint" style=${{marginTop: 0}}>Records deleted from the Ecosystem Directory. They are hidden everywhere
        and are removed permanently ${RETENTION_DAYS} days after deletion unless restored. Restoring brings a record
        back with its status, owner, links and history.</p>
      ${message && html`<div class=${message.ok ? "selnote" : "whynot"} role=${message.ok ? "status" : "alert"}>${message.text}</div>`}
      ${state.loaded && !state.error && state.rows.length > 0 && html`<div class="pd-filters">
        <label><span class="hint">Type</span>
          <select value=${filters.entity_type} onChange=${e => setFilters({...filters, entity_type: e.target.value})}>
            <option value="all">All types</option>
            ${Object.entries(KIND).map(([k, v]) => html`<option key=${k} value=${k}>${v}</option>`)}
          </select></label>
        <label><span class="hint">Search</span>
          <input type="search" value=${filters.search} placeholder="Name, reason or who deleted"
            onInput=${e => setFilters({...filters, search: e.target.value})}/></label>
      </div>`}
      ${!state.loaded ? html`<p class="hint">Loading…</p>`
        : state.error ? html`<div class="whynot" role="alert">${state.error}</div>`
        : !state.rows.length ? html`<div class="card pad"><p class="hint" style=${{margin: 0}}>No records are waiting for permanent removal.</p></div>`
        : !rows.length ? html`<p class="hint">No records match these filters.</p>`
        : html`<div class="card pd-table-wrap"><table class="pd-table">
            <thead><tr><th>Record</th><th>Type</th><th>Deleted by</th><th>Deleted on</th><th>Reason</th>
              <th>Remaining</th><th><span class="sr-only">Action</span></th></tr></thead>
            <tbody>${rows.map(r => html`<tr key=${r.deletion_id}>
              <td data-label="Record"><strong>${r.name}</strong></td>
              <td data-label="Type">${kindLabel(r.entity_type)}</td>
              <td data-label="Deleted by">${r.deleted_by || "Not recorded"}</td>
              <td data-label="Deleted on">${day(r.deleted_at)}</td>
              <td data-label="Reason">${r.reason || html`<span class="hint">No reason given</span>`}</td>
              <td data-label="Remaining"><span class=${"pd-days" + (isUrgent(r.days_remaining) ? " urgent" : "")}
                title=${"Removed permanently on " + day(r.purge_after)}>${daysLeftLabel(r.days_remaining)}</span></td>
              <td class="pd-action">${confirming === r.deletion_id
                ? html`<span class="pd-confirm" role="alertdialog" aria-label=${`Restore ${r.name}`}>
                    <span>Restore “${r.name}”?</span>
                    <button class="btn" type="button" disabled=${busy} onClick=${() => restore(r)}>${busy ? "Restoring…" : "Yes, restore"}</button>
                    <button class="example" type="button" disabled=${busy} onClick=${() => setConfirming(null)}>Cancel</button></span>`
                : html`<button class="example" type="button" data-needs=${PERMISSION} disabled=${!canRestore(r)}
                    title=${canRestore(r) ? "" : "The 30 days are over; it is removed at the next cleanup."}
                    onClick=${() => { setMessage(null); setConfirming(r.deletion_id); }}>Restore</button>`}</td>
            </tr>`)}</tbody></table></div>`}
    </div>`;
  }

  return {PendingDeletionWidget, PendingDeletionPage};
}
