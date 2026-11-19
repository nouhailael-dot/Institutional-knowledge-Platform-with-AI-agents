// My profile and Users (accounts Phase 2). Shown only with individual accounts on
// (GHUS_AUTH_MODE=supabase). The server checks every action; these pages only
// show what the signed-in person may do.

import {createPendingDeletion, PERMISSION as DELETE_PERMISSION} from "./deletions.js?v=20261118a";

const PERMISSION_WORDS = {
  "records.view": "Browse organizations, people, events and hubs",
  "ask.use": "Ask Compass",
  "maps.view": "Open maps",
  "dashboard.view": "Personal dashboard",
  "usage.view_own": "Own usage and costs",
  "maps.create": "Create maps (paid research)",
  "requests.view": "Open Monitor and Update",
  "requests.create": "Create and run requests (paid agents)",
  "datafeed.import": "Import with Data Feed",
  "review.view": "Open Review Results",
  "review.decide": "Verify, reject and park",
  "records.edit": "Edit records",
  "notes.write": "Write GHUS Notes",
  "records.remove": "Remove and restore records",
  "records.delete_permanent": "Permanently delete records",
  "usage.view_all": "Everyone's usage and costs",
  "audit.view_all": "Full audit history",
  "users.manage": "Manage users and roles",
  "settings.admin": "Administrative settings",
};

// In the role, but switched off until its own approval (permanent deletion: Phase 6).
const NOT_YET = new Set(["records.delete_permanent"]);

const day = (v) => v ? new Date(v).toLocaleDateString("en-US", {month: "short", day: "numeric", year: "numeric"}) : "—";
const moment = (v) => v ? new Date(v).toLocaleString("en-US", {month: "short", day: "numeric", year: "numeric",
  hour: "numeric", minute: "2-digit"}) : "Never";

async function call(url, method = "POST", body) {
  const response = await fetch(url, {method, headers: {"Content-Type": "application/json"},
    body: body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : "Check the form and try again.";
    throw new Error(detail);
  }
  return data;
}

export function createAccountPages({html, useState, useEffect}) {
  // Records deleted from the Directory, waiting 30 days (Admins and Editors/Reviewers only).
  const {PendingDeletionWidget, PendingDeletionPage} = createPendingDeletion({html, useState, useEffect});
  function Notice({ok, error}) {
    return html`${ok && html`<div class="selnote" role="status">${ok}</div>`}
      ${error && html`<div class="whynot" role="alert">${error}</div>`}`;
  }

  function ProfilePage({onAccount}) {
    const [data, setData] = useState(null);
    const [name, setName] = useState("");
    const [pw, setPw] = useState({current: "", next: "", again: ""});
    const [busy, setBusy] = useState("");
    const [note, setNote] = useState({});
    async function load() {
      try {
        const d = await call("/api/account/profile", "GET");
        setData(d); setName(d.profile.full_name);
      } catch (e) { setNote({error: e.message}); }
    }
    useEffect(() => { load(); }, []);
    if (!data) return html`<p class="hint">${note.error || "Loading your profile…"}</p>`;
    const p = data.profile;
    async function saveName(e) {
      e.preventDefault(); setBusy("name"); setNote({});
      try {
        const d = await call("/api/account/profile", "PATCH", {full_name: name});
        setData(d); setNote({ok: "Your name is saved."}); onAccount && onAccount();
      } catch (err) { setNote({error: err.message}); }
      setBusy("");
    }
    async function savePassword(e) {
      e.preventDefault(); setNote({});
      if (pw.next !== pw.again) { setNote({error: "The two new passwords are different."}); return; }
      setBusy("pw");
      try {
        await call("/api/account/password", "POST", {current_password: pw.current, new_password: pw.next});
        setPw({current: "", next: "", again: ""});
        setNote({ok: "Your password is changed. Other devices were signed out."});
      } catch (err) { setNote({error: err.message}); }
      setBusy("");
    }
    return html`<div class="accounts-page">
      <h1 class="hero-h" style=${{marginBottom: "6px"}}>My profile</h1>
      <p class="hint" style=${{marginTop: 0}}>Your account in Compass. Everything you do is recorded under your name.</p>
      <${Notice} ...${note}/>
      <div class="card pad" style=${{marginTop: "14px"}}>
        <form onSubmit=${saveName}>
          <div class="edit-field"><label for="me-name">Name</label>
            <input id="me-name" class="field" value=${name} maxlength="120" disabled=${busy === "name"}
              onInput=${e => setName(e.target.value)}/></div>
          <div class="edit-field"><label>Email</label><div class="edit-ro">${p.email}
            <span class="hint" style=${{margin: "0 0 0 8px"}}>to change it, ask an administrator</span></div></div>
          <div class="edit-field"><label>Role</label><div class="edit-ro">${p.role_label || "No role"}</div></div>
          <div class="edit-field"><label>Member since</label><div class="edit-ro">${day(p.created_at)}</div></div>
          <div class="edit-field"><label>Last sign-in</label><div class="edit-ro">${moment(p.last_login_at)}</div></div>
          <button class="btn" type="submit" disabled=${busy === "name" || !name.trim() || name.trim() === p.full_name}>
            ${busy === "name" ? "Saving…" : "Save name"}</button>
        </form>
      </div>
      <div class="card pad" style=${{marginTop: "14px"}}>
        <strong>What your role allows</strong>
        <ul class="hint" style=${{display: "block", columns: "2 220px", margin: "10px 0 0", paddingLeft: "18px"}}>
          ${Object.keys(PERMISSION_WORDS).filter(code => data.permissions.includes(code)).map(code =>
            html`<li key=${code} style=${{marginBottom: "4px"}}>${PERMISSION_WORDS[code]}${NOT_YET.has(code)
              ? html` <span style=${{opacity: .7}}>(not available yet)</span>` : ""}</li>`)}</ul>
      </div>
      <div class="card pad" style=${{marginTop: "14px"}}>
        <form onSubmit=${savePassword}>
          <strong>Change your password</strong>
          <div class="edit-field"><label for="pw-current">Current password</label>
            <input id="pw-current" class="field" type="password" autocomplete="current-password" value=${pw.current}
              onInput=${e => setPw({...pw, current: e.target.value})}/></div>
          <div class="edit-field"><label for="pw-next">New password</label>
            <input id="pw-next" class="field" type="password" autocomplete="new-password" value=${pw.next}
              onInput=${e => setPw({...pw, next: e.target.value})}/></div>
          <div class="edit-field"><label for="pw-again">Repeat the new password</label>
            <input id="pw-again" class="field" type="password" autocomplete="new-password" value=${pw.again}
              onInput=${e => setPw({...pw, again: e.target.value})}/></div>
          <p class="hint">At least 12 characters, not your name or email. Your other devices will be signed out.</p>
          <button class="btn" type="submit" disabled=${busy === "pw" || !pw.current || pw.next.length < 12}>
            ${busy === "pw" ? "Changing…" : "Change password"}</button>
        </form>
      </div>
      <${PreferencesCard}/>
    </div>`;
  }

  function UsersPage({account}) {
    const [data, setData] = useState(null);
    const [form, setForm] = useState({email: "", full_name: "", role: "viewer"});
    const [busy, setBusy] = useState("");
    const [note, setNote] = useState({});
    const [confirming, setConfirming] = useState(null);
    async function load() {
      try { setData(await call("/api/admin/users", "GET")); }
      catch (e) { setNote({error: e.message}); }
    }
    useEffect(() => { load(); }, []);
    if (!data) return html`<p class="hint">${note.error || "Loading users…"}</p>`;
    const mine = new Set(account.permissions);
    const grantable = data.roles.filter(r => r.permissions.every(p => mine.has(p)));
    async function act(key, url, body, ok) {
      setBusy(key); setNote({}); setConfirming(null);
      try { await call(url, "POST", body); setNote({ok}); await load(); }
      catch (e) { setNote({error: e.message}); }
      setBusy("");
    }
    async function invite(e) {
      e.preventDefault();
      await act("invite", "/api/admin/invitations", form,
        `Invitation sent to ${form.email.trim()}. It expires in ${data.invitation_days} days.`);
      setForm(f => ({...f, email: "", full_name: ""}));
    }
    const statusChip = (u) => {
      const tone = u.status === "active" ? "green" : u.status === "deactivated" ? "slate" : "amber";
      return html`<span class=${"chip " + tone}>${u.status_label[0].toUpperCase() + u.status_label.slice(1)}</span>`;
    };
    return html`<div class="accounts-page">
      <h1 class="hero-h" style=${{marginBottom: "6px"}}>Users</h1>
      <p class="hint" style=${{marginTop: 0}}>Invite people, set their role, and turn accounts on or off.
        Compass always keeps at least one active administrator.</p>
      <${Notice} ...${note}/>
      <form class="card pad" style=${{marginTop: "14px"}} onSubmit=${invite}>
        <strong>Invite someone</strong>
        <div class="filters" style=${{marginTop: "10px"}}>
          <label>Email<input class="field" type="email" required value=${form.email}
            onInput=${e => setForm({...form, email: e.target.value})}/></label>
          <label>Name<input class="field" required maxlength="120" value=${form.full_name}
            onInput=${e => setForm({...form, full_name: e.target.value})}/></label>
          <label>Role<select class="field" value=${form.role} onChange=${e => setForm({...form, role: e.target.value})}>
            ${grantable.map(r => html`<option key=${r.code} value=${r.code}>${r.label}</option>`)}</select></label>
        </div>
        <p class="hint">They receive an email with a link to choose a password. The link works once;
          the invitation expires after ${data.invitation_days} days.</p>
        <button class="btn" type="submit" disabled=${busy === "invite" || !form.email.trim() || !form.full_name.trim()}>
          ${busy === "invite" ? "Sending…" : "Send invitation"}</button>
      </form>
      <div class="card pad" style=${{marginTop: "14px", overflowX: "auto"}}>
        <table class="grid"><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th>
          <th>Last sign-in</th><th></th></tr></thead>
        <tbody>${data.users.length === 0 && html`<tr><td colspan="6" class="hint">No users yet.</td></tr>`}
        ${data.users.map(u => {
          const self = u.user_id === data.me, inv = u.invitation, key = u.user_id;
          const roleChoice = u.status === "deactivated" ? null : html`<select class="field" aria-label=${"Role of " + u.full_name}
              value=${u.role || inv?.role || ""} disabled=${busy === key}
              onChange=${e => act(key, `/api/admin/users/${u.user_id}/role`, {role: e.target.value},
                `${u.full_name} is now ${data.roles.find(r => r.code === e.target.value)?.label}.`)}>
              ${!u.role && u.status !== "invited" && html`<option value="">No role</option>`}
              ${data.roles.map(r => html`<option key=${r.code} value=${r.code}
                disabled=${!r.permissions.every(p => mine.has(p))}>${r.label}</option>`)}</select>`;
          return html`<tr key=${key}>
            <td>${u.full_name}${self && html` <span class="hint">(you)</span>`}</td>
            <td>${u.email}</td>
            <td>${roleChoice || (u.role_label || "—")}</td>
            <td>${statusChip(u)}${inv && u.status === "invited" && html`<div class="hint" style=${{margin: "4px 0 0"}}>
              ${inv.state === "open" ? `Expires ${day(inv.expires_at)}` : `Invited by ${inv.invited_by}`}</div>`}</td>
            <td>${moment(u.last_login_at)}</td>
            <td style=${{whiteSpace: "nowrap"}}>
              ${u.status === "invited" && inv?.state === "open" && html`<button class="example" type="button"
                disabled=${busy === key} onClick=${() => act(key, `/api/admin/invitations/${inv.invitation_id}/revoke`, undefined,
                  `The invitation for ${u.email} is withdrawn.`)}>Revoke</button>`}
              ${u.status === "invited" && inv && inv.state !== "accepted" && html` <button class="example" type="button"
                disabled=${busy === key} onClick=${() => act(key, `/api/admin/invitations/${inv.invitation_id}/resend`, undefined,
                  `A new invitation is on its way to ${u.email}.`)}>Resend</button>`}
              ${u.status === "active" && !self && (confirming === key
                ? html`<span class="hint">Deactivate ${u.full_name}? </span>
                    <button class="example danger" type="button" disabled=${busy === key}
                      onClick=${() => act(key, `/api/admin/users/${u.user_id}/deactivate`, {reason: ""},
                        `${u.full_name} can no longer sign in.`)}>Yes, deactivate</button>
                    <button class="example" type="button" onClick=${() => setConfirming(null)}>No</button>`
                : html`<button class="example danger" type="button" onClick=${() => setConfirming(key)}>Deactivate</button>`)}
              ${u.status === "deactivated" && html`<button class="example" type="button" disabled=${busy === key}
                onClick=${() => act(key, `/api/admin/users/${u.user_id}/activate`, undefined,
                  `${u.full_name} can sign in again.`)}>Activate</button>`}
            </td></tr>`;
        })}</tbody></table>
      </div>
    </div>`;
  }

  function MyWorkPage() {
    const [mine, setMine] = useState(null);
    const [history, setHistory] = useState(null);
    const [error, setError] = useState("");
    useEffect(() => {
      call("/api/account/mine", "GET").then(setMine).catch(e => setError(e.message));
      call("/api/account/review-history", "GET").then(d => setHistory(d.history)).catch(e => setError(e.message));
    }, []);
    const list = (items, empty) => !items ? html`<p class="hint">Loading…</p>`
      : items.length === 0 ? html`<p class="hint">${empty}</p>`
      : html`<table class="grid"><thead><tr><th>Name</th><th>Type</th><th>How</th><th>Since</th></tr></thead>
          <tbody>${items.map(i => html`<tr key=${i.entity_type + i.entity_id}>
            <td>${i.name || html`<span class="hint">${i.entity_id}</span>`}
              ${i.note && html`<div class="hint" style=${{margin: "2px 0 0"}}>${i.note}</div>`}</td>
            <td>${TYPE_WORDS[i.entity_type] || i.entity_type}</td>
            <td>${ORIGIN_WORDS[i.origin] || i.origin}</td><td>${day(i.recorded_at)}</td></tr>`)}</tbody></table>`;
    const section = (title, help, body) => html`<div class="card pad" style=${{marginTop: "14px", overflowX: "auto"}}>
      <strong>${title}</strong><p class="hint" style=${{margin: "4px 0 10px"}}>${help}</p>${body}</div>`;
    return html`<div class="accounts-page">
      <h1 class="hero-h" style=${{marginBottom: "6px"}}>My work</h1>
      <p class="hint" style=${{marginTop: 0}}>What you brought into Compass and what you decided. Records stay
        shared with the whole team; this page only lists yours. Work from before accounts shows its
        owner as Not recorded.</p>
      ${error && html`<div class="whynot" role="alert">${error}</div>`}
      ${section("My Records", "Organizations, people and events you added to the shared database.",
        list(mine?.records, "None yet."))}
      ${section("My Requests", "Discovery and update requests you created in Monitor and Update.",
        list(mine?.requests, "None yet."))}
      ${section("My Maps", "Maps you started in Explore and Map.", list(mine?.maps, "None yet."))}
      ${section("My Imports", "Imports you sent through Data Feed (and maps you saved to the database).",
        list(mine?.imports, "None yet."))}
      ${section("My Review History", "Your decisions in Review Results and your changes in the Directory, newest first.",
        !history ? html`<p class="hint">Loading…</p>` : history.length === 0 ? html`<p class="hint">None yet.</p>`
        : html`<table class="grid"><thead><tr><th>When</th><th>What</th><th>Record</th></tr></thead>
          <tbody>${history.map(h => html`<tr key=${h.audit_id}><td>${moment(h.occurred_at)}</td>
            <td>${actionWords(h)}</td>
            <td>${h.detail?.record_name || (h.entity_type ? `${TYPE_WORDS[h.entity_type] || h.entity_type} ${h.entity_id || ""}` : "—")}</td>
            </tr>`)}</tbody></table>`)}
    </div>`;
  }

  // -- Notifications: the bell in the header (Phase 4) --------------------------------------
  function NotificationBell({onNavigate}) {
    const [data, setData] = useState({unread: 0, items: []});
    const [open, setOpen] = useState(false);
    async function load() {
      try { setData(await call("/api/account/notifications", "GET")); } catch (e) { /* quiet */ }
    }
    useEffect(() => { load(); const t = setInterval(load, 120000); return () => clearInterval(t); }, []);
    async function openItem(item) {
      if (!item.read_at) { try { await call(`/api/account/notifications/${item.id}/read`); } catch (e) {} }
      setOpen(false); await load();
      if (item.link && onNavigate) onNavigate(item.link);
    }
    async function readAll() { try { await call("/api/account/notifications/read-all"); } catch (e) {} load(); }
    return html`<div class="notify-wrap">
      <button class="notify-bell" type="button" aria-haspopup="true" aria-expanded=${open}
        aria-label=${data.unread ? `${data.unread} unread notification${data.unread === 1 ? "" : "s"}` : "Notifications"}
        onClick=${() => { setOpen(!open); if (!open) load(); }}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"
          stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M6 9.5a6 6 0 0 1 12 0c0 5 2 6.5 2 6.5H4s2-1.5 2-6.5"/><path d="M10 19.5a2 2 0 0 0 4 0"/></svg>
        ${data.unread > 0 && html`<span class="notify-count">${data.unread > 99 ? "99+" : data.unread}</span>`}
      </button>
      ${open && html`<div class="notify-panel card" role="dialog" aria-label="Notifications">
        <div class="notify-head"><strong>Notifications</strong>
          ${data.unread > 0 && html`<button class="example" type="button" onClick=${readAll}>Mark all read</button>`}</div>
        ${data.items.length === 0 ? html`<p class="hint" style=${{margin: "8px 0"}}>Nothing yet.</p>`
          : data.items.slice(0, 12).map(item => html`<button key=${item.id} type="button"
              class=${"notify-item" + (item.read_at ? "" : " unread")} onClick=${() => openItem(item)}>
              <span class="notify-title">${item.title}</span>
              ${item.body && html`<span class="notify-body">${item.body}</span>`}
              <span class="notify-when">${moment(item.created_at)}</span></button>`)}
      </div>`}
    </div>`;
  }

  // -- The personal Dashboard (Phase 4) ---------------------------------------------------------
  const STATUS_WORDS = {running: "Running", planning: "Planning", verifying: "Checking results",
    done: "Ready", succeeded: "Finished", attention: "Finished: needs attention", failed: "Failed",
    error: "Stopped with an error", interrupted: "Interrupted", budget_stopped: "Budget reached",
    cancelled: "Stopped"};

  function DashboardPage({onNavigate}) {
    const [d, setD] = useState(null);
    const [error, setError] = useState("");
    async function load() {
      try { setD(await call("/api/account/dashboard", "GET")); } catch (e) { setError(e.message); }
    }
    useEffect(() => { load(); }, []);
    if (!d) return html`<p class="hint">${error || "Loading your dashboard…"}</p>`;
    const can = (p) => d.permissions.includes(p);
    const show = (key) => !d.hidden.includes(key);
    const go = (tab, label) => html`<button class="example" type="button" onClick=${() => onNavigate(tab)}>${label}</button>`;
    const card = (key, title, body, action) => show(key) && html`<div class="card pad dash-card" key=${key}>
      <div class="dash-card-head"><strong>${title}</strong>${action}</div>${body}</div>`;
    const empty = (text) => html`<p class="hint" style=${{margin: "6px 0 0"}}>${text}</p>`;
    const names = (items) => items.length === 0 ? empty("None yet.") : html`<ul class="dash-list">
      ${items.map(i => html`<li key=${i.entity_type + i.entity_id}>${i.name || i.entity_id}
        <span class="hint"> · ${day(i.recorded_at)}</span></li>`)}</ul>`;
    const runRow = (r) => html`<li key=${r.kind + r.id}>${r.name}
      <span class=${"chip " + (["failed", "error", "interrupted"].includes(r.status) ? "red"
        : ["running", "planning", "verifying"].includes(r.status) ? "amber" : "green")}>${STATUS_WORDS[r.status] || r.status}</span>
      <span class="hint"> · ${r.kind === "map" ? "Map" : "Request"}${r.at ? " · " + moment(r.at) : ""}</span></li>`;
    async function markRead(id) { try { await call(`/api/account/notifications/${id}/read`); } catch (e) {} load(); }
    return html`<div class="accounts-page">
      <h1 class="hero-h" style=${{marginBottom: "4px"}}>Welcome, ${d.name.split(" ")[0]}</h1>
      <p class="hint" style=${{marginTop: 0}}>${d.role_label}. Your work and what needs you, at a glance.
        The shared Ecosystem Directory is the same for everyone.</p>
      <div class="dash-grid">
        ${card("notifications", `Notifications${d.notifications.unread ? ` (${d.notifications.unread} new)` : ""}`,
          d.notifications.items.length === 0 ? empty("Nothing new.") : html`<ul class="dash-list">
            ${d.notifications.items.map(n => html`<li key=${n.id} class=${n.read_at ? "" : "unread"}>
              <button class="link-like" type="button" onClick=${() => { markRead(n.id); if (n.link) onNavigate(n.link); }}>${n.title}</button>
              <span class="hint"> · ${moment(n.created_at)}</span></li>`)}</ul>`)}
        ${(can("maps.create") || can("requests.create")) && card("runs", "Running and recent runs",
          d.running.length + d.recent_runs.length === 0 ? empty("No runs yet.") : html`<ul class="dash-list">
            ${[...d.running, ...d.recent_runs].map(runRow)}</ul>`)}
        ${can(DELETE_PERMISSION) && html`<${PendingDeletionWidget} key="deletions" onNavigate=${onNavigate}/>`}
        ${card("activity", "My recent activity", d.activity.length === 0 ? empty("Nothing yet.")
          : html`<ul class="dash-list">${d.activity.map(a => html`<li key=${a.audit_id}>${activityWords(a)}
              <span class="hint"> · ${moment(a.occurred_at)}</span></li>`)}</ul>`)}
        ${card("records", `My Records (${d.counts.records})`, names(d.records), go("mywork", "See all"))}
        ${can("requests.view") && card("requests", `My Requests (${d.counts.requests})`, names(d.requests),
          go("discovery", "Monitor and Update"))}
        ${card("maps", `My Maps (${d.counts.maps})`, names(d.maps), go("map", "Explore and Map"))}
        ${can("datafeed.import") && card("imports", `My Imports (${d.counts.imports})`, names(d.imports),
          go("datafeed", "Data Feed"))}
        ${can("review.decide") && card("reviews", "My Review History", d.reviews.length === 0 ? empty("No decisions yet.")
          : html`<ul class="dash-list">${d.reviews.map(h => html`<li key=${h.audit_id}>${actionWords(h)}:
              ${h.detail?.record_name || h.entity_id}<span class="hint"> · ${moment(h.occurred_at)}</span></li>`)}</ul>`,
          go("review", "Review Results"))}
        ${d.sectors.length > 0 && card("sectors", "Your sectors", html`<ul class="dash-list">
          ${d.sectors.map(s => html`<li key=${s.sector}>${s.sector}<span class="hint"> · ${s.organizations} organizations</span></li>`)}</ul>`,
          go("browse", "Directory"))}
      </div>
      <p class="hint">Choose what this page shows, your sectors and your notifications in
        <button class="link-like" type="button" onClick=${() => onNavigate("profile")}>My profile</button>.</p>
    </div>`;
  }

  // -- Preferences (on My profile) -------------------------------------------------------------
  const SECTION_WORDS = {notifications: "Notifications", runs: "Running and recent runs", activity: "My recent activity",
    records: "My Records", requests: "My Requests", maps: "My Maps", imports: "My Imports",
    reviews: "My Review History", sectors: "Your sectors"};

  function PreferencesCard() {
    const [d, setD] = useState(null);
    const [sectors, setSectors] = useState([]);
    const [note, setNote] = useState({});
    useEffect(() => {
      call("/api/account/preferences", "GET").then(setD).catch(e => setNote({error: e.message}));
      call("/api/browse/actors", "GET").then(a => setSectors(a.options?.sectors || [])).catch(() => {});
    }, []);
    if (!d) return html`<div class="card pad" style=${{marginTop: "14px"}}><p class="hint">${note.error || "Loading preferences…"}</p></div>`;
    const p = d.preferences;
    async function save(change, ok) {
      setNote({});
      try { const r = await call("/api/account/preferences", "PUT", {preferences: change});
            setD({...d, preferences: r.preferences}); setNote({ok}); window.dispatchEvent(new CustomEvent("compass:preferences", {detail: r.preferences})); }
      catch (e) { setNote({error: e.message}); }
    }
    const toggleList = (list, value) => list.includes(value) ? list.filter(v => v !== value) : [...list, value];
    return html`<div class="card pad" style=${{marginTop: "14px"}}>
      <strong>Preferences</strong>
      <p class="hint" style=${{margin: "4px 0 10px"}}>Only what you see changes; the shared records stay the same for everyone.</p>
      <${Notice} ...${note}/>
      <div class="edit-field"><label>Preferred sectors</label><div class="pref-chips">
        ${(sectors.length ? sectors : p.sectors).map(s => html`<label key=${s} class="check">
          <input type="checkbox" checked=${p.sectors.includes(s)}
            onChange=${() => save({sectors: toggleList(p.sectors, s)}, "Sectors saved.")}/> ${s}</label>`)}
        ${sectors.length === 0 && p.sectors.length === 0 && html`<span class="hint">No sectors to choose from.</span>`}</div></div>
      <div class="edit-field"><label>The Directory opens on</label><div>
        ${[["all", "All Records"], ["mine", "My Records"]].map(([v, l]) => html`<label key=${v} class="check" style=${{marginRight: "14px"}}>
          <input type="radio" name="dir-view" checked=${p.directory.default_view === v}
            onChange=${() => save({directory: {default_view: v}}, `The Directory opens on ${l}.`)}/> ${l}</label>`)}</div></div>
      <div class="edit-field"><label>Saved Directory filters</label><div>
        ${p.directory.saved_filters.length === 0 ? html`<span class="hint">None. Save one from the Directory's filters.</span>`
          : p.directory.saved_filters.map(f => html`<div key=${f.tab + f.name}>${f.name}
              <span class="hint"> (${f.tab})</span>
              <button class="example" type="button" style=${{marginLeft: "8px"}}
                onClick=${() => save({directory: {saved_filters: p.directory.saved_filters.filter(x => x !== f)}},
                  `Removed '${f.name}'.`)}>Remove</button></div>`)}</div></div>
      <div class="edit-field"><label>Dashboard shows</label><div class="pref-chips">
        ${d.dashboard_sections.map(s => html`<label key=${s} class="check">
          <input type="checkbox" checked=${!p.dashboard.hidden.includes(s)}
            onChange=${() => save({dashboard: {hidden: toggleList(p.dashboard.hidden, s)}}, "Dashboard saved.")}/>
          ${SECTION_WORDS[s] || s}</label>`)}</div></div>
      <div class="edit-field"><label>Notify me when</label><div>
        ${Object.entries(d.notification_kinds).map(([k, words]) => html`<label key=${k} class="check" style=${{display: "block"}}>
          <input type="checkbox" checked=${p.notifications[k]}
            onChange=${() => save({notifications: {[k]: !p.notifications[k]}}, "Notifications saved.")}/> ${words}</label>`)}
        <label class="check" style=${{display: "block", marginTop: "6px"}}>
          <input type="checkbox" checked=${p.notifications.email}
            onChange=${() => save({notifications: {email: !p.notifications.email}}, "Saved.")}/>
          Also by email <span class="hint">(once email is switched on for Compass; nothing is sent yet)</span></label>
      </div></div>
    </div>`;
  }

  // -- Audit History (audit.view_all) -----------------------------------------------------------
  function AuditPage() {
    const [entries, setEntries] = useState(null);
    const [filter, setFilter] = useState("");
    const [error, setError] = useState("");
    async function load(action) {
      setError("");
      try { setEntries((await call(`/api/admin/audit${action ? `?action=${encodeURIComponent(action)}` : ""}`, "GET")).entries); }
      catch (e) { setError(e.message); }
    }
    useEffect(() => { load(""); }, []);
    return html`<div class="accounts-page">
      <h1 class="hero-h" style=${{marginBottom: "6px"}}>Audit History</h1>
      <p class="hint" style=${{marginTop: 0}}>Every change in Compass, who made it and when, newest first. It cannot be
        edited or deleted.</p>
      <div class="filters" style=${{marginTop: "10px"}}><label>Show
        <select class="field" value=${filter} onChange=${e => { setFilter(e.target.value); load(e.target.value); }}>
          <option value="">Everything</option><option value="review.">Review decisions</option>
          <option value="browse.">Directory changes</option><option value="map.">Maps</option>
          <option value="discovery.">Requests</option><option value="datafeed.">Imports</option>
          <option value="user.">User management</option><option value="invitation.">Invitations</option>
          <option value="auth.">Sign-ins</option><option value="access.">Refused attempts</option></select></label></div>
      ${error && html`<div class="whynot" role="alert">${error}</div>`}
      <div class="card pad" style=${{marginTop: "14px", overflowX: "auto"}}>
        ${!entries ? html`<p class="hint">Loading…</p>` : entries.length === 0 ? html`<p class="hint">Nothing recorded.</p>`
          : html`<table class="grid"><thead><tr><th>When</th><th>Who</th><th>What</th><th>Record</th></tr></thead>
            <tbody>${entries.map(e => html`<tr key=${e.audit_id}><td>${moment(e.occurred_at)}</td><td>${e.user_label}</td>
              <td>${activityWords(e)}</td><td>${e.detail?.record_name || (e.entity_type ? `${TYPE_WORDS[e.entity_type] || e.entity_type} ${(e.entity_id || "").slice(0, 8)}` : "—")}</td>
            </tr>`)}</tbody></table>`}
      </div>
    </div>`;
  }

  // -- Usage and costs (Phase 5) -----------------------------------------------------------------
  const usd = (v) => `$${Number(v || 0).toFixed(2)}`;
  const monthName = (m) => m && m !== "unknown"
    ? new Date(`${m}-01T00:00:00Z`).toLocaleDateString("en-US", {month: "long", year: "numeric", timeZone: "UTC"}) : "Unknown date";
  const opsTable = (ops) => ops.length === 0 ? html`<p class="hint">None yet.</p>` : html`<table class="grid">
    <thead><tr><th>When</th><th>What</th><th>Who</th><th>How</th><th>Status</th><th class="num">Cost</th></tr></thead>
    <tbody>${ops.map(o => html`<tr key=${o.source + o.reference}>
      <td>${o.started_at ? moment(o.started_at) : "—"}</td><td>${o.feature}</td><td>${o.user}</td>
      <td>${{manual: "Started by hand", run_now: "Run now", scheduled: "Scheduled"}[o.trigger] || o.trigger}</td>
      <td>${o.basis}</td><td class="num">${usd(o.cost_usd)}</td></tr>`)}</tbody></table>`;

  function UsagePage() {
    const [d, setD] = useState(null);
    const [error, setError] = useState("");
    useEffect(() => { call("/api/account/usage", "GET").then(setD).catch(e => setError(e.message)); }, []);
    if (!d) return html`<p class="hint">${error || "Loading your usage…"}</p>`;
    const m = d.this_month;
    const stat = (label, value, note) => html`<div class="card pad usage-stat"><span class="hint">${label}</span>
      <strong>${value}</strong>${note && html`<span class="hint">${note}</span>`}</div>`;
    return html`<div class="accounts-page">
      <h1 class="hero-h" style=${{marginBottom: "6px"}}>My usage</h1>
      <p class="hint" style=${{marginTop: 0}}>What your searches, runs and questions cost, from the amounts Compass
        recorded when they ran. A cost marked "in progress", "partial run" or "estimate" is not final yet.</p>
      <div class="usage-stats">
        ${stat(`Spent in ${monthName(d.month)}`, usd(m.cost_usd), m.not_final_usd ? `${usd(m.not_final_usd)} not final yet` : "")}
        ${stat("Searches and agent runs", m.operations || 0)}
        ${stat("Maps started", m.maps_created || 0)}
        ${stat("Records added", m.records_created || 0)}
        ${stat("Review decisions", m.review_decisions || 0)}
      </div>
      ${Object.keys(m.by_feature || {}).length > 0 && html`<div class="card pad" style=${{marginTop: "14px"}}>
        <strong>This month by feature</strong><ul class="dash-list">
        ${Object.entries(m.by_feature).map(([f, v]) => html`<li key=${f}>${f}<span class="hint"> · ${v.operations} · ${usd(v.cost_usd)}</span></li>`)}</ul></div>`}
      <div class="card pad" style=${{marginTop: "14px", overflowX: "auto"}}><strong>Monthly history</strong>
        ${d.history.length === 0 ? html`<p class="hint">Nothing yet.</p>` : html`<table class="grid" style=${{marginTop: "8px"}}>
          <thead><tr><th>Month</th><th class="num">Spent</th><th class="num">Runs</th><th class="num">Maps</th>
            <th class="num">Records added</th><th class="num">Review decisions</th></tr></thead>
          <tbody>${d.history.map(h => html`<tr key=${h.month}><td>${monthName(h.month)}</td><td class="num">${usd(h.cost_usd)}</td>
            <td class="num">${h.operations || 0}</td><td class="num">${h.maps_created || 0}</td>
            <td class="num">${h.records_created || 0}</td><td class="num">${h.review_decisions || 0}</td></tr>`)}</tbody></table>`}</div>
      <div class="card pad" style=${{marginTop: "14px", overflowX: "auto"}}><strong>Recent paid operations</strong>
        <div style=${{marginTop: "8px"}}>${opsTable(d.recent)}</div></div>
    </div>`;
  }

  function CostsPage() {
    const [d, setD] = useState(null);
    const [f, setF] = useState({since: "", until: "", user_id: "", feature: "", unattributed: false});
    const [error, setError] = useState("");
    const query = (x) => new URLSearchParams(Object.entries(x).filter(([, v]) => v).map(([k, v]) => [k, String(v)])).toString();
    async function load(x) {
      setError("");
      try { setD(await call(`/api/admin/usage?${query(x)}`, "GET")); } catch (e) { setError(e.message); }
    }
    useEffect(() => { load(f); }, []);
    const change = (k, v) => { const x = {...f, [k]: v}; setF(x); load(x); };
    if (!d) return html`<p class="hint">${error || "Loading usage and costs…"}</p>`;
    const s = d.summary;
    const months = [...new Set(Object.values(s.by_user_month).flatMap(per => Object.keys(per)))].sort();
    return html`<div class="accounts-page">
      <h1 class="hero-h" style=${{marginBottom: "6px"}}>Usage and Costs</h1>
      <p class="hint" style=${{marginTop: 0}}>All recorded spending, read from the run ledgers. "Not recorded" is spending
        from before accounts, or with no recorded person; it is never assigned to anyone.</p>
      ${error && html`<div class="whynot" role="alert">${error}</div>`}
      <div class="filters" style=${{marginTop: "10px"}}>
        <label>From<input class="field" type="month" value=${f.since} onChange=${e => change("since", e.target.value)}/></label>
        <label>To<input class="field" type="month" value=${f.until} onChange=${e => change("until", e.target.value)}/></label>
        <label>Person<select class="field" value=${f.user_id} onChange=${e => change("user_id", e.target.value)}>
          <option value="">Everyone</option>${d.people.map(p => html`<option key=${p.user_id} value=${p.user_id}>${p.name}</option>`)}</select></label>
        <label>Feature<select class="field" value=${f.feature} onChange=${e => change("feature", e.target.value)}>
          <option value="">All features</option>${d.features.map(x => html`<option key=${x} value=${x}>${x}</option>`)}</select></label>
        <label class="check" style=${{alignSelf: "end"}}><input type="checkbox" checked=${f.unattributed}
          onChange=${e => change("unattributed", e.target.checked)}/> Only Not recorded</label>
      </div>
      <div class="usage-stats" style=${{marginTop: "14px"}}>
        <div class="card pad usage-stat"><span class="hint">Total (filtered)</span><strong>${usd(s.total.cost_usd)}</strong>
          ${s.total.not_final_usd > 0 && html`<span class="hint">${usd(s.total.not_final_usd)} not final yet</span>`}</div>
        <div class="card pad usage-stat"><span class="hint">Operations</span><strong>${s.total.operations}</strong></div>
        <div class="card pad usage-stat"><span class="hint">Not recorded (period)</span><strong>${usd(d.not_recorded.cost_usd)}</strong>
          <span class="hint">${d.not_recorded.operations} operations</span></div>
      </div>
      <div class="card pad" style=${{marginTop: "14px", overflowX: "auto"}}><strong>By person and month</strong>
        ${months.length === 0 ? html`<p class="hint">Nothing in this period.</p>` : html`<table class="grid" style=${{marginTop: "8px"}}>
          <thead><tr><th>Person</th>${months.map(m => html`<th key=${m} class="num">${m}</th>`)}<th class="num">Total</th></tr></thead>
          <tbody>${Object.entries(s.by_user_month).map(([person, per]) => html`<tr key=${person}><td>${person}</td>
            ${months.map(m => html`<td key=${m} class="num">${per[m] ? usd(per[m]) : "—"}</td>`)}
            <td class="num"><b>${usd(Object.values(per).reduce((a, b) => a + b, 0))}</b></td></tr>`)}</tbody></table>`}</div>
      <div class="card pad" style=${{marginTop: "14px", overflowX: "auto"}}><strong>By feature</strong>
        <table class="grid" style=${{marginTop: "8px"}}><thead><tr><th>Feature</th><th class="num">Operations</th>
          <th class="num">Cost</th><th class="num">Not final</th></tr></thead>
        <tbody>${Object.entries(s.by_feature).map(([x, v]) => html`<tr key=${x}><td>${x}</td><td class="num">${v.operations}</td>
          <td class="num">${usd(v.cost_usd)}</td><td class="num">${usd(v.not_final_usd)}</td></tr>`)}</tbody></table></div>
      <div class="card pad" style=${{marginTop: "14px", overflowX: "auto"}}><strong>Requests, maps, imports and decisions by month</strong>
        <table class="grid" style=${{marginTop: "8px"}}><thead><tr><th>Month</th><th class="num">Requests created</th>
          <th class="num">Maps started</th><th class="num">Imports</th><th class="num">Records added</th><th class="num">Review decisions</th></tr></thead>
        <tbody>${Object.entries(d.counts).map(([m, c]) => html`<tr key=${m}><td>${monthName(m)}</td><td class="num">${c.requests_created}</td>
          <td class="num">${c.maps_created}</td><td class="num">${c.imports}</td><td class="num">${c.records_created}</td>
          <td class="num">${c.review_decisions}</td></tr>`)}</tbody></table></div>
      <div class="card pad" style=${{marginTop: "14px", overflowX: "auto"}}><strong>Reconciliation with the ledgers</strong>
        <p class="hint" style=${{margin: "4px 0 8px"}}>Each ledger's own total, and how much of it is attributed or Not recorded. The difference is always zero.
          ${!d.map_costs_included && " The map store could not be read, so map costs are not included."}</p>
        <table class="grid"><thead><tr><th>Ledger</th><th class="num">Ledger total</th><th class="num">Attributed</th>
          <th class="num">Not recorded</th><th class="num">Difference</th></tr></thead>
        <tbody>${d.reconciliation.map(r => html`<tr key=${r.ledger}><td>${r.ledger}</td><td class="num">${usd(r.ledger_total_usd)}</td>
          <td class="num">${usd(r.attributed_usd)}</td><td class="num">${usd(r.not_recorded_usd)}</td>
          <td class="num">${usd(r.difference_usd)}</td></tr>`)}</tbody></table></div>
      <div class="card pad" style=${{marginTop: "14px", overflowX: "auto"}}>
        <div class="dash-card-head"><strong>Operations</strong><span>
          <a class="example" href=${`/api/admin/usage/export?format=csv&${query(f)}`} download>⤓ CSV</a>
          <a class="example" style=${{marginLeft: "6px"}} href=${`/api/admin/usage/export?format=xlsx&${query(f)}`} download>⤓ Excel</a></span></div>
        <div style=${{marginTop: "8px"}}>${opsTable(d.operations.slice(0, 100))}</div>
        ${d.operations.length > 100 && html`<p class="hint">The first 100 are shown; the export has all ${d.operations.length}.</p>`}</div>
    </div>`;
  }

  return {ProfilePage, UsersPage, MyWorkPage, DashboardPage, NotificationBell, PreferencesCard, AuditPage,
          UsagePage, CostsPage, PendingDeletionPage};
}

function activityWords(entry) {
  const a = entry.action;
  if (a.startsWith("review.") || a.startsWith("browse.") || a.startsWith("map.save") || a === "datafeed.previews_confirm")
    return actionWords(entry);
  return ({"map.session": "Started a map", "map.create": "Ran a map search", "map.chat": "Planned a map",
    "discovery.requests": "Created a request", "discovery.update_requests": "Created an update request",
    "discovery.requests_run": "Ran a request now", "auth.login": "Signed in", "auth.logout": "Signed out",
    "access.denied": "Was refused an action", "invitation.created": "Invited someone",
    "user.role_changed": "Changed a role", "user.deactivated": "Deactivated an account",
    "user.activated": "Activated an account", "profile.updated": "Updated their profile",
    "auth.password_changed": "Changed their password"})[a] || a;
}

const TYPE_WORDS = {actor: "Organization", person: "Person", event: "Event", hub: "Hub", request: "Request",
  map: "Map", import: "Import", review_candidate: "Review item"};
const ORIGIN_WORDS = {created: "Created", imported: "Imported", discovered: "Verified from discovery",
  mapped: "Saved from a map", requested: "Requested"};
const DECISION_WORDS = {new: "Verified as a new record", same_existing: "Verified as an existing record",
  reject: "Rejected", defer: "Parked", approve: "Approved", looks_right: "Confirmed an update"};

function actionWords(entry) {
  const d = entry.detail || {};
  if (entry.action.startsWith("review.")) return DECISION_WORDS[d.decision] || "Review decision";
  return ({"browse.edit": "Edited a record", "browse.actors_remove": "Removed from the Directory",
           "browse.actors_restore": "Restored to the Directory", "map.save": "Saved map records",
           "map.review": "Parked or rejected a map record", "datafeed.previews_confirm": "Imported records"})[entry.action]
    || entry.action;
}
