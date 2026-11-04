// Data Feed: GHUS adds Actors, People and Events - from the official template
// (Excel or CSV) or by hand - and sends them to Review.
//
// Choose type -> download the template or open the form -> check -> preview
// -> confirm -> Review. The page never writes a record: checking is read-only,
// and confirming hands the records to the GHUS backend, which stages them for
// Review. Nothing is added to the map, or verified, without a GHUS decision.

import {lightPullBoxes, formatFactValue} from "./review.js?v=20261104c";
import {createDateInput, usDate, usDateTime} from "./dates.js?v=20261102d";

export const RECORD_TYPES = [
  {id: "actor", label: "Organizations", short: "Organizations", noun: "organization"},
  {id: "person", label: "People", short: "People", noun: "person"},
  {id: "event", label: "Events", short: "Events", noun: "event"},
];

export const STATUS = {
  invalid: {label: "Needs correction", tone: "error"},
  new: {label: "New record", tone: "ok"},
  existing: {label: "Matches an existing record", tone: "info"},
  possible: {label: "Possible duplicate", tone: "warn"},
  waiting: {label: "Already waiting in Review Results", tone: "muted"},
};

export const FILTERS = [
  {id: "all", label: "All"},
  {id: "invalid", label: "Needs correction"},
  {id: "new", label: "New"},
  {id: "existing", label: "Existing matches"},
  {id: "possible", label: "Possible duplicates"},
  {id: "waiting", label: "Already in Review Results"},
];

export function typeInfo(recordType) {
  return RECORD_TYPES.find(t => t.id === recordType) || RECORD_TYPES[0];
}

/** The summary tiles above the preview, in reading order. */
export function summaryTiles(counts = {}) {
  return [
    {key: "total", label: "Records", value: counts.total ?? 0, tone: ""},
    {key: "valid", label: "Valid", value: counts.valid ?? 0, tone: "ok"},
    {key: "needs_correction", label: "Need correction", value: counts.needs_correction ?? 0,
      tone: counts.needs_correction ? "error" : ""},
    {key: "new", label: "New", value: counts.new ?? 0, tone: ""},
    {key: "existing_matches", label: "Existing matches", value: counts.existing_matches ?? 0,
      tone: counts.existing_matches ? "info" : ""},
    {key: "possible_duplicates", label: "Possible duplicates",
      value: counts.possible_duplicates ?? 0, tone: counts.possible_duplicates ? "warn" : ""},
    {key: "already_waiting", label: "Already in Review Results", value: counts.already_waiting ?? 0,
      tone: ""},
    {key: "missing_optional", label: "Missing optional info",
      value: counts.missing_optional ?? 0, tone: ""},
  ];
}

export function filterRows(rows = [], filter = "all") {
  return filter === "all" ? rows : rows.filter(row => row.status === filter);
}

export function filterCount(rows = [], filter = "all") {
  return filterRows(rows, filter).length;
}

/** What gets sent, said before the button is pressed. */
export function confirmLabel(counts = {}) {
  const send = Math.max(0, (counts.valid ?? 0) - (counts.already_waiting ?? 0));
  return send === 1 ? "Send 1 record to Review Results" : `Send ${send} records to Review Results`;
}

export function stageable(counts = {}) {
  return Math.max(0, (counts.valid ?? 0) - (counts.already_waiting ?? 0));
}

export const DATAFEED_LEAD = "Add organizations, people, and events to the COMPASS Ecosystem "
  + "Directory using a template or manual entry. Once successfully submitted, your entries will be "
  + "available in the Ecosystem Directory.";
export const IMPORT_NAME_HINT = "This name will be used to identify your import in Import History.";

/** A suggested import name: the file's name, or "Manual entry" with the date. */
export function defaultImportName(preview, today = new Date()) {
  const file = preview?.file?.name;
  if (file) return file.replace(/\.(xlsx|csv)$/i, "").replace(/[_-]+/g, " ").trim().slice(0, 120);
  return `Manual entry ${usDate(today)}`;
}

/** The label of a code in a vocabulary, or the code itself. */
export function vocabLabel(vocab, name, code, category) {
  if (code === null || code === undefined || code === "") return "";
  const list = name === "category_types" ? (vocab?.category_types?.[category] || [])
    : (vocab?.[name] || []);
  const item = list.find(i => i.code === code);
  return item ? item.label : String(code);
}

export function rowTitle(row) {
  const v = row?.values || {};
  const person = [v["First name *"], v["Last name *"]].filter(Boolean).join(" ");
  return row?.payload?.name || v["Official name *"] || person
    || v["Event name *"] || `Row ${row?.row_number ?? ""}`;
}

/** The second line of a preview row: what it is, in a few words. */
export function rowSubtitle(row, recordType, vocab) {
  const p = row?.payload || {};
  if (recordType === "actor") {
    const category = vocabLabel(vocab, "actor_categories", p.actor_category);
    const type = vocabLabel(vocab, "category_types", p.category_type, p.actor_category);
    const place = [p.city, p.state_code].filter(Boolean).join(", ");
    return [category, type, place].filter(Boolean).join(" · ");
  }
  if (recordType === "person") return [p.role, p.affiliation].filter(Boolean).join(" · ");
  const when = p.end_date && p.end_date !== p.start_date
    ? `${usDate(p.start_date)} - ${usDate(p.end_date)}` : p.start_date && usDate(p.start_date);
  return [vocabLabel(vocab, "event_types", p.event_type), when, p.location]
    .filter(Boolean).join(" · ");
}

/** A short line for the match column. */
export function matchLine(match) {
  if (!match || match.kind === "new" || !match.entity_id) return "";
  const score = typeof match.score === "number" ? ` (${Math.round(match.score * 100)}%)` : "";
  return `${match.kind === "existing" ? "Same as" : "Close to"} “${match.name}”${score}`
    + (match.reason ? ` - ${match.reason}` : "");
}

/** The fields the manual form shows: category-specific boxes only for the chosen category. */
export function visibleFields(fields = [], category = "") {
  return fields.filter(f => !(f.categories || []).length || (f.categories || []).includes(category));
}

/** The name a manual draft shows in its header: a person's is first + last. */
export function draftName(draft = {}) {
  return draft.name || [draft.first_name, draft.last_name].filter(Boolean).join(" ");
}

/** Required fields the draft leaves empty (the server checks everything else). */
export function missingRequired(fields = [], draft = {}) {
  return fields.filter(f => f.required && !String(draft[f.key] ?? "").trim()).map(f => f.header);
}

/** The form's drafts as the records the server checks: {field key: text}. */
export function manualRecords(drafts = [], fields = []) {
  const keys = new Set(fields.map(f => f.key));
  return drafts.map(draft => Object.fromEntries(Object.entries(draft)
    .filter(([key, value]) => keys.has(key) && String(value ?? "").trim() !== "")
    .map(([key, value]) => [key, Array.isArray(value) ? value.join("; ") : String(value)])));
}

/**
 * A preview row in the shape Review reads, so the Light Pull boxes are the
 * same boxes, with the same labels, as in Review.
 */
export function previewCandidate(row) {
  const p = row?.payload || {};
  const facts = Object.entries(p.light_pull_values || {}).map(([key, value]) => ({
    fact_key: key, fact_type: "light_pull", layer: 1, collection_state: "found", value,
    source_url: p.source_url || p.website || null, source_origin: "uploaded_document",
  }));
  return {reviewed_payload: {actor_category: p.actor_category, website: p.website},
    agent_metadata: {facts}};
}

/** The information boxes of a preview record, grouped as Review groups them. */
export function infoBoxes(row, recordType, vocab, fields = []) {
  const p = row?.payload || {};
  const label = key => fields.find(f => f.key === key)?.header || key;
  const item = (key, value) => ({label: label(key), value});
  const sectors = list => (list || []).map(code => vocabLabel(vocab, "sectors", code)).join(", ");
  if (recordType === "actor") {
    return [
      {title: "Identity", items: [item("name", p.name),
        item("alternate_names", (p.alternate_names || []).join(", ")),
        item("website", p.website), item("description", p.description)]},
      {title: "Classification", items: [
        item("actor_category", vocabLabel(vocab, "actor_categories", p.actor_category)),
        item("category_type", p.category_type
          ? vocabLabel(vocab, "category_types", p.category_type, p.actor_category)
          : "Pending Classification"),
        item("category_note", p.category_note)]},
      {title: "Location", items: [item("city", p.city), item("state_code", p.state_code),
        item("region", p.state_code ? vocabLabel(vocab, "regions", regionOf(vocab, p.state_code))
          : ""), item("country", p.country)]},
      {title: "Sector and topic", items: [item("primary_sector", sectors(p.sector_codes)),
        item("topic", vocabLabel(vocab, "topics", p.topic_code))]},
      {title: "Parent", items: [item("parent_name", p.parent_name),
        item("parent_relationship", vocabLabel(vocab, "parent_links", p.parent_relationship))]},
      {title: "Source", items: [item("source_url", p.source_url)]},
    ];
  }
  if (recordType === "person") {
    return [
      {title: "Identity", items: [item("name", p.name), item("role", p.role),
        item("affiliation", p.affiliation), item("department", p.department)]},
      {title: "Profile", items: [item("bio", p.bio), item("bio_url", p.bio_url),
        item("linkedin_url", p.linkedin_url), item("expertise", (p.expertise || []).join(", "))]},
      {title: "Location and sector", items: [item("city", p.work_location),
        item("sectors", sectors(p.sector_codes)),
        item("topic", vocabLabel(vocab, "topics", p.topic_code))]},
      {title: "Source", items: [item("source_url", p.source_url)]},
    ];
  }
  return [
    {title: "Event", items: [item("name", p.name),
      item("event_type", vocabLabel(vocab, "event_types", p.event_type)),
      item("organizer", p.sponsoring_orgs || "No confirmed host"),
      item("description", p.description)]},
    {title: "When and where", items: [item("start_date", p.start_date),
      item("end_date", p.end_date),
      item("event_format", vocabLabel(vocab, "event_formats", p.event_format)),
      item("venue", p.location)]},
    {title: "Sector and themes", items: [item("sectors", sectors(p.sector_codes)),
      item("topic", vocabLabel(vocab, "topics", p.topic_code)), item("themes", p.thematic_focus),
      item("recurring_pattern", vocabLabel(vocab, "recurrence", p.recurring_pattern))]},
    {title: "Links", items: [item("website", p.website),
      item("registration_url", p.registration_url), item("source_url", p.source_url)]},
  ];
}

function regionOf(vocab, state) {
  // The region follows the state (Architecture V2 section 2); the server
  // derives it the same way. Shown only, never sent.
  return (vocab?.regions || []).find(r => (r.states || []).includes(state))?.code || "";
}

/** "3 organizations · about $0.13 (average of 17 earlier reads)" */
export function costLine(estimate) {
  if (!estimate) return "";
  const n = (estimate.organisations || []).length;
  if (!n) return "Every record already has all its boxes; nothing to read.";
  const usd = Number(estimate.estimated_usd || 0).toFixed(2);
  return `${n} organization${n === 1 ? "" : "s"} to read · about $${usd} `
    + `($${Number(estimate.per_organisation_usd || 0).toFixed(3)} each: ${estimate.basis})`;
}

/**
 * An import's Status column: what Review has done with it, never more. "Stored in the
 * Directory" only once nothing waits and something was added or matched.
 */
export function importResult(item = {}) {
  const c = item.counts || {};
  // A directory import is stored after COMPASS completes it: waiting means completing.
  if (item.admission === "directory" && c.pending) return {label: "Completing Information", tone: "partly"};
  const decided = (c.approved_new || 0) + (c.matched_existing || 0) + (c.rejected || 0) + (c.deferred || 0);
  if (c.pending) return decided ? {label: "Partly Reviewed", tone: "partly"} : {label: "Awaiting Review", tone: "waiting"};
  if ((c.approved_new || 0) + (c.matched_existing || 0)) return {label: "Stored in the Directory", tone: "added"};
  return {label: "Reviewed", tone: "reviewed"};
}

/** Imports matching the history's search box and Record Type filter. */
export function filterImports(items = [], search = "", category = "all") {
  const q = String(search || "").trim().toLowerCase();
  return items.filter((item) => (category === "all" || item.record_type === category)
    && (!q || String(item.import_name || "").toLowerCase().includes(q)));
}

/** One history row's counts, in words. */
/** Imports stay with whoever made them; there is no sign-in yet, so by the name they typed. */
export function myImports(items = [], name = "") {
  const me = String(name || "").trim().toLowerCase();
  return items.filter((item) => {
    const by = String(item.uploaded_by || "").trim().toLowerCase();
    return !by || (me && by === me);
  });
}

/** How many records the import held. */
export function recordCount(item = {}) {
  const n = item.rows_total ?? item.staged ?? 0;
  return `${n} ${n === 1 ? "record" : "records"}`;
}

/** The AI read's ceiling for an import: about $0.05 each, with room, at most the $5 limit. */
export function completionCap(count = 0) {
  return Math.min(5, Math.max(0.5, Math.round(count * 10) / 100));
}

/** Open this import's records in Review Results. */
export function openImportInReview(runId) {
  window.dispatchEvent(new CustomEvent("ghus:open-review", {detail: {
    run_key: `datafeed:${runId}`, run_type: "data_feed"}}));
}

export function historyLine(item) {
  const c = item?.counts || {};
  return [
    `${item?.staged ?? 0} staged`,
    c.pending ? `${c.pending} awaiting Review` : null,
    c.approved_new ? `${c.approved_new} approved and added` : null,
    c.matched_existing ? `${c.matched_existing} matched to existing` : null,
    c.rejected ? `${c.rejected} rejected` : null,
    c.deferred ? `${c.deferred} deferred` : null,
    item?.already_awaiting_review ? `${item.already_awaiting_review} already in Review Results` : null,
    item?.rows_invalid ? `${item.rows_invalid} failed validation` : null,
  ].filter(Boolean).join(" · ");
}

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

/** The confirmation of what is left out, before it happens. */
export function leftOutLine(n) {
  return `${plural(n, "record needs", "records need")} correction and will not be sent. `
    + "I understand; send the others.";
}

/** What the uploader confirms, before anything is sent. */
export const ATTEST_SOURCE = "I confirm these records come from a GHUS source (a GHUS file, a "
  + "Compass import or a Notion CRM export copied into this template).";
export const ATTEST_AUTHORIZED = "I am authorized GHUS staff and I verify the records in "
  + "this import.";

/** The confirm button may be pressed. */
export function canSend({preview, name, attestSource, admission = "directory", attestAuthorized,
  accept}) {
  const counts = preview?.counts || {};
  return Boolean(preview?.can_confirm && String(name || "").trim()
    && attestSource
    && (!["verified", "directory"].includes(admission) || attestAuthorized)
    && (!counts.needs_correction || accept));
}

/** What happened when the records were sent. */
export function doneLine(done = {}) {
  if (done.status === "already_imported") {
    return "This exact file was imported before; nothing was sent twice.";
  }
  if (done.admission === "directory") {
    const parts = [];
    if (done.enriching?.started) {
      parts.push(`${plural(done.staged ?? 0, "organization is", "organizations are")} being completed `
        + "by COMPASS from their own pages, then stored in the Ecosystem Directory (a few minutes; "
        + `at most $${Number(done.enriching.max_usd).toFixed(2)}). Import History shows when they are stored.`);
    } else if (done.enriching && !done.enriching.started) {
      parts.push(`The records were saved, but completing them did not start: ${done.enriching.error}`);
    } else {
      parts.push(`${plural(done.stored ?? 0, "record was", "records were")} stored in the Ecosystem Directory.`);
    }
    const refused = (done.not_stored || []).length;
    if (refused) parts.push(`${plural(refused, "record could", "records could")} not be stored (see below).`);
    const left = done.left_out || 0;
    if (left) parts.push(`${left} needed correction and ${left === 1 ? "was" : "were"} left out.`);
    return parts.join(" ");
  }
  if (done.admission === "verified") {
    const verified = done.verified || 0;
    const held = (done.held_for_review || []).length;
    const parts = [`${plural(verified, "organization was", "organizations were")} added to the directory `
      + `as Verified, on ${done.uploaded_by || "the uploader"}'s attestation.`];
    if (held) parts.push(`${plural(held, "record waits", "records wait")} in Review Results.`);
    const left = done.left_out || 0;
    if (left) parts.push(`${left} needed correction and ${left === 1 ? "was" : "were"} left out.`);
    return parts.join(" ");
  }
  const parts = [`${plural(done.staged ?? 0, "record now waits", "records now wait")} in Review Results `
    + `as “Data Feed import · ${done.import_name}”.`];
  const waiting = done.already_awaiting_review || 0;
  if (waiting) {
    parts.push(`${waiting} ${waiting === 1 ? "was" : "were"} already waiting in Review Results and not `
      + "sent again.");
  }
  const left = done.left_out || 0;
  if (left) parts.push(`${left} needed correction and ${left === 1 ? "was" : "were"} left out.`);
  return parts.join(" ");
}

/** "Organizations · file.xlsx · Oct 26, 2026 · Uploaded by Not recorded (no sign-in yet)" */
export function historyMeta(item = {}) {
  return [typeInfo(item.record_type).label,
    item.method === "upload" ? item.file_name : "Manual entry",
    formatDateTime(item.uploaded_at),
    `Uploaded by ${item.uploaded_by ? `${item.uploaded_by} (as typed; no sign-in yet)`
      : "Not recorded"}`,
    item.admission === "directory" ? "Stored in the Directory"
      : item.admission === "verified" ? "Imported as Verified" : "Sent to Review Results",
  ].filter(Boolean).join(" · ");
}

/** What an import looks like in the history, shown while there is none. Never real data. */
// A finished import, always listed and marked Example (3 Nov 2026). It lives only in
// this page - nothing of it is in the database - and tells the same story as its
// Excel sheet (/api/datafeed/example-import.xlsx, made on request, never stored):
// three organizations added, one matched to an existing record, one left out.
export const EXAMPLE_IMPORT = {
  example: true, import_name: "Kansas water organizations", record_type: "actor",
  method: "upload", file_name: "Kansas water organizations.xlsx",
  uploaded_at: "2026-11-02T10:30:00", uploaded_by: "", admission: "review",
  rows_total: 5, staged: 4, rows_invalid: 1,
  counts: {pending: 0, approved_new: 3, matched_existing: 1},
  records: [
    {row_number: 2, name: "Example Water Lab", status: "Stored in the Directory"},
    {row_number: 3, name: "Example Irrigation Co.", status: "Matched to an existing record"},
    {row_number: 4, name: "Example Aquifer Center", status: "Stored in the Directory"},
    {row_number: 5, name: "Example Rural Water District", status: "Stored in the Directory"},
    {row_number: 6, name: "Example Water Coalition", status: "Left out: no Sector"},
  ],
};

export function formatDateTime(value) {
  return value ? usDateTime(value) : "";
}

export function boxesLine(org = {}) {
  const n = (org.boxes || []).length;
  return `${org.name}: ${plural(n, "empty box", "empty boxes")}`;
}

export function approveLine(cap) {
  return `I approve spending up to $${Number(cap || 0).toFixed(2)} on this read.`;
}

export function formatDate(value) {
  return value ? usDate(value) : "";
}

// ---------------------------------------------------------------- the page
export function createDataFeedPage({html, useState, useEffect, Fragment = globalThis.React?.Fragment}) {
  const DateInput = createDateInput({html, useState, useEffect});
  async function api(path, options = {}) {
    const response = await fetch(path, options.body instanceof FormData ? options
      : {headers: {"Content-Type": "application/json"}, ...options});
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = Array.isArray(body.detail) ? body.detail.map(d => d.msg).join("; ")
        : body.detail;
      throw new Error(detail || `Request failed (${response.status})`);
    }
    return body;
  }

  function Control({field, value, onChange, vocab, category}) {
    const id = `df-${field.key}`;
    const set = event => onChange(field.key, event.target.value);
    if (field.kind === "enum") {
      const items = field.vocab === "category_types" ? (vocab.category_types?.[category] || [])
        : (vocab[field.vocab] || []);
      return html`<select id=${id} value=${value || ""} onChange=${set}
        disabled=${field.vocab === "category_types" && !category}>
        <option value="">${field.vocab === "category_types" && !category
          ? "Choose the category first" : "-"}</option>
        ${items.map(i => html`<option key=${i.code} value=${i.label}>${i.label}</option>`)}
      </select>`;
    }
    if (field.kind === "multi_enum") {
      const chosen = new Set(String(value || "").split(";").map(s => s.trim()).filter(Boolean));
      const toggle = label => {
        const next = new Set(chosen);
        next.has(label) ? next.delete(label) : next.add(label);
        onChange(field.key, [...next].join("; "));
      };
      return html`<div class="discovery-segment df-multi" role="group" aria-label=${field.header}>
        ${(vocab[field.vocab] || []).map(i => html`<button type="button" key=${i.code}
          class=${chosen.has(i.label) ? "active" : ""} aria-pressed=${chosen.has(i.label)}
          onClick=${() => toggle(i.label)}>${i.label}</button>`)}
      </div>`;
    }
    if (field.kind === "long_text") {
      return html`<textarea id=${id} rows="3" value=${value || ""} onInput=${set}
        maxlength=${field.max_length || undefined}></textarea>`;
    }
    if (field.kind === "date") {
      return html`<${DateInput} id=${id} value=${value || ""} onChange=${(v) => onChange(field.key, v)}/>`;
    }
    const type = field.kind === "url" ? "url" : "text";
    return html`<input id=${id} type=${type} value=${value || ""} onInput=${set}
      maxlength=${field.max_length || undefined}
      placeholder=${field.kind === "list" ? "Separate several with ;" : ""}/>`;
  }

  function ManualForm({recordType, catalog, importName, onChecked, setMessage}) {
    const fields = catalog.types[recordType].fields;
    const vocab = catalog.vocabularies;
    const [drafts, setDrafts] = useState([{}]);
    const [open, setOpen] = useState(0);
    const [busy, setBusy] = useState(false);
    useEffect(() => { setDrafts([{}]); setOpen(0); }, [recordType]);
    const update = (index, key, value) => setDrafts(list => list.map((d, i) => {
      if (i !== index) return d;
      const next = {...d, [key]: value};
      if (key === "actor_category") next.category_type = "";
      return next;
    }));
    const categoryCode = draft => (vocab.actor_categories || [])
      .find(c => c.label === draft.actor_category)?.code || "";
    async function check() {
      if (!importName.trim()) {
        setMessage({kind: "error", text: "Give the import a name first (Import Name, at the top)."});
        return;
      }
      const problems = drafts.map((d, i) => [i, missingRequired(fields, d)]).filter(([, m]) => m.length);
      if (problems.length) {
        setMessage({kind: "error", text: problems.map(([i, m]) =>
          `Record ${i + 1}: ${m.join(", ")} ${m.length === 1 ? "is" : "are"} required.`).join(" ")});
        setOpen(problems[0][0]);
        return;
      }
      setBusy(true);
      setMessage(null);
      try {
        onChecked(await api("/api/datafeed/validate-manual", {method: "POST",
          body: JSON.stringify({record_type: recordType, records: manualRecords(drafts, fields)})}));
      } catch (error) {
        setMessage({kind: "error", text: error.message});
      } finally {
        setBusy(false);
      }
    }
    const groups = [
      ["Required", f => f.required],
      ["Details", f => !f.required && !(f.categories || []).length],
      ["Category details", f => (f.categories || []).length],
    ];
    return html`<section class="df-panel df-form">
      <h3>Add Records Manually</h3>
      <p class="df-muted">Add one record at a time using the form below. Fields marked <span class="df-req">*</span> are
        required; fill in everything else you know.</p>
      ${drafts.map((draft, index) => html`<div key=${index} class=${"df-record" + (open === index ? " open" : "")}>
        <button type="button" class="df-record-head" aria-expanded=${open === index}
          onClick=${() => setOpen(open === index ? -1 : index)}>
          <span>Record ${index + 1}${draftName(draft) ? ` · ${draftName(draft)}` : ""}</span>
          <span aria-hidden="true">${open === index ? "−" : "+"}</span>
        </button>
        ${open === index && html`<div class="df-record-body">
          ${groups.map(([title, keep]) => {
            const shown = visibleFields(fields, categoryCode(draft)).filter(keep);
            if (!shown.length) return null;
            return html`<fieldset key=${title} class="df-group">
              <legend>${title}</legend>
              <div class="discovery-grid">
                ${shown.map(field => html`<div key=${field.key}
                  class=${"discovery-field" + (field.kind === "long_text" || field.kind === "multi_enum" ? " wide" : "")}>
                  <label class="discovery-label" for=${`df-${field.key}`}>${field.header}${field.required ? html` <span class="df-req" aria-hidden="true">*</span>` : ""}</label>
                  <${Control} field=${field} value=${draft[field.key]} vocab=${vocab}
                    category=${categoryCode(draft)} onChange=${(k, v) => update(index, k, v)}/>
                  ${field.hint && html`<small class="df-hint">${field.hint}</small>`}
                </div>`)}
              </div>
            </fieldset>`;
          })}
          ${drafts.length > 1 && html`<button type="button" class="btn ghost danger"
            onClick=${() => { setDrafts(list => list.filter((_, i) => i !== index)); setOpen(-1); }}>
            Remove this record</button>`}
        </div>`}
      </div>`)}
      <div class="df-panel-foot">
        <button type="button" class="df-add-another" disabled=${drafts.length >= catalog.limits.max_manual_rows}
          onClick=${() => { setDrafts(list => [...list, {}]); setOpen(drafts.length); }}>
          <span aria-hidden="true">+</span> Add Another Record</button>
        <button type="button" class="btn" disabled=${busy} onClick=${check}>
          ${busy ? "Checking…" : "Submit Import"}</button>
      </div>
    </section>`;
  }

  function UploadCard({recordType, catalog, importName, onChecked, setMessage}) {
    const [file, setFile] = useState(null);
    const [busy, setBusy] = useState(false);
    const [drag, setDrag] = useState(false);
    useEffect(() => setFile(null), [recordType]);
    const max = catalog.limits.max_bytes;
    function choose(chosen) {
      if (!chosen) return;
      if (!/\.(xlsx|csv)$/i.test(chosen.name)) {
        setMessage({kind: "error", text: "Choose a .xlsx or .csv file made from the GHUS template."});
        return;
      }
      if (chosen.size > max) {
        setMessage({kind: "error", text: "The file is larger than 5 MB. Split it into smaller files."});
        return;
      }
      setMessage(null);
      setFile(chosen);
    }
    async function check() {
      if (!importName.trim()) {
        setMessage({kind: "error", text: "Give the import a name first (Import Name, at the top)."});
        return;
      }
      setBusy(true);
      setMessage(null);
      const form = new FormData();
      form.append("record_type", recordType);
      form.append("file", file);
      try {
        onChecked(await api("/api/datafeed/validate", {method: "POST", body: form}));
      } catch (error) {
        setMessage({kind: "error", text: error.message});
      } finally {
        setBusy(false);
      }
    }
    return html`<section class="df-panel df-upload">
      <h3>Upload Excel or CSV</h3>
      <p class="df-muted">Use the official template, fill one record per row, and upload your file.
        Required columns are marked *; the Field Guide sheet explains every column.</p>
      <div class="df-templates"><div class="df-template on">
        <strong>${typeInfo(recordType).label} template</strong>
        <a class="btn ghost" href=${`/api/datafeed/templates/${recordType}.xlsx`} download>Excel (.xlsx)</a>
        <a class="btn ghost" href=${`/api/datafeed/templates/${recordType}.csv`} download>CSV (.csv)</a>
      </div></div>
      <label class=${"df-drop" + (drag ? " drag" : "")}
        onDragOver=${e => { e.preventDefault(); setDrag(true); }}
        onDragLeave=${() => setDrag(false)}
        onDrop=${e => { e.preventDefault(); setDrag(false); choose(e.dataTransfer.files?.[0]); }}>
        <input type="file" accept=".xlsx,.csv" onChange=${e => choose(e.target.files?.[0])}/>
        <strong>${file ? file.name : "Choose a file or drop it here"}</strong>
        <span>${file ? `${(file.size / 1024).toFixed(0)} KB` : `.xlsx or .csv · up to ${catalog.limits.max_rows} rows · 5 MB`}</span>
      </label>
      <div class="df-panel-foot end">
        <button type="button" class="btn" disabled=${!file || busy} onClick=${check}>
          ${busy ? "Checking the file…" : "Submit Import"}</button>
      </div>
    </section>`;
  }

  function InfoBoxes({row, recordType, catalog}) {
    const vocab = catalog.vocabularies;
    const fields = catalog.types[recordType].fields;
    const boxes = infoBoxes(row, recordType, vocab, fields);
    const light = recordType === "actor" ? lightPullBoxes(previewCandidate(row),
      row.payload?.actor_category) : {common: [], specific: []};
    const show = rows => rows.filter(r => r.value !== null && r.value !== undefined);
    return html`<div class="df-boxes">
      ${boxes.map(box => html`<section key=${box.title} class="df-box">
        <h4>${box.title}</h4>
        <dl>${box.items.map(i => html`<div key=${i.label}><dt>${i.label}</dt>
          <dd class=${i.value ? "" : "empty"}>${i.value || "Not provided"}</dd></div>`)}</dl>
      </section>`)}
      ${[...show(light.common), ...show(light.specific)].length > 0 && html`<section class="df-box wide">
        <h4>Light Pull information supplied</h4>
        <dl>${[...show(light.common), ...show(light.specific)].map(r => html`<div key=${r.key}>
          <dt>${r.label}</dt><dd>${formatFactValue(r.value)}</dd></div>`)}</dl>
        <p class="df-muted">Kept as GHUS-supplied (uploaded document). Empty boxes can be completed
          by the Light Pull after the records are sent.</p>
      </section>`}
    </div>`;
  }

  function Preview({preview, catalog, importName = "", onBack, onDone, setMessage}) {
    const [filter, setFilter] = useState(preview.counts.needs_correction ? "invalid" : "all");
    const [openRow, setOpenRow] = useState(null);
    const [name, setName] = useState(importName.trim() || defaultImportName(preview));
    const [accept, setAccept] = useState(false);
    const [attestSource, setAttestSource] = useState(false);
    // Every import is stored in the directory (GHUS decision, 3 Nov 2026).
    const admission = "directory";
    const [attestAuthorized, setAttestAuthorized] = useState(false);
    const [busy, setBusy] = useState(false);
    const recordType = preview.record_type;
    const vocab = catalog.vocabularies;
    const rows = filterRows(preview.rows, filter);
    const counts = preview.counts;
    const send = stageable(counts);
    async function confirm() {
      setBusy(true);
      setMessage(null);
      try {
        const result = await api(`/api/datafeed/previews/${preview.preview_id}/confirm`, {
          method: "POST", body: JSON.stringify({import_name: name, accept_left_out: accept,
            attest_source: attestSource, admission, attest_authorized: attestAuthorized})});
        onDone(result);
      } catch (error) {
        setMessage({kind: "error", text: error.message});
      } finally {
        setBusy(false);
      }
    }
    if (preview.header_problems.length) {
      return html`<section class="discovery-card">
        <h3>The file's columns do not match the template</h3>
        <ul class="df-problems">${preview.header_problems.map(p => html`<li key=${p}>${p}</li>`)}</ul>
        <p class="df-muted">Nothing was checked further. Download the current template, copy your
          rows into it, and upload it again.</p>
        <div class="discovery-actions"><button class="btn" onClick=${onBack}>Upload a corrected file</button></div>
      </section>`;
    }
    return html`<div class="df-preview">
      <section class="discovery-card">
        <div class="df-preview-head">
          <div>
            <h3>Preview${preview.file ? ` · ${preview.file.name}` : " · manual entry"}</h3>
            <p class="df-muted">Nothing has been saved. Check the records, then store them in the Ecosystem Directory.</p>
          </div>
          <button type="button" class="btn ghost" onClick=${onBack}>
            ${preview.file ? "Upload a corrected file" : "Edit the records"}</button>
        </div>
        <div class="df-tiles">${summaryTiles(counts).map(t => html`<div key=${t.key}
          class=${"df-tile " + t.tone}><strong>${t.value}</strong><span>${t.label}</span></div>`)}</div>
        ${preview.notes.length > 0 && html`<ul class="df-notes">${preview.notes.map(n => html`<li key=${n}>${n}</li>`)}</ul>`}
        ${preview.already_imported_run_id && html`<p class="discovery-message">This exact file was
          already imported; its records are in Import history. It is not sent twice.</p>`}
      </section>

      <section class="discovery-card">
        <div class="discovery-segment df-filters" role="group" aria-label="Show">
          ${FILTERS.map(f => html`<button type="button" key=${f.id} class=${filter === f.id ? "active" : ""}
            aria-pressed=${filter === f.id} onClick=${() => { setFilter(f.id); setOpenRow(null); }}>
            ${f.label} (${filterCount(preview.rows, f.id)})</button>`)}
        </div>
        ${rows.length === 0 && html`<p class="discovery-empty">No records here.</p>`}
        <ul class="df-rows">
          ${rows.map(row => html`<li key=${row.row_number} class=${"df-row " + row.status}>
            <button type="button" class="df-row-head" aria-expanded=${openRow === row.row_number}
              onClick=${() => setOpenRow(openRow === row.row_number ? null : row.row_number)}>
              <span class="df-rownum">${preview.method === "upload" ? `Row ${row.row_number}` : `#${row.row_number}`}</span>
              <span class="df-row-main"><strong>${rowTitle(row)}</strong>
                <small>${rowSubtitle(row, recordType, vocab)}</small></span>
              <span class=${"df-chip " + STATUS[row.status].tone}>${STATUS[row.status].label}</span>
            </button>
            ${(row.errors.length > 0 || row.warnings.length > 0 || matchLine(row.match)) && html`<div class="df-issues">
              ${row.errors.map(e => html`<p key=${e} class="df-error">${e}</p>`)}
              ${matchLine(row.match) && html`<p class="df-match">${matchLine(row.match)}.${row.match?.kind === "existing"
                ? " That record is updated instead of adding a new one." : ""}</p>`}
              ${openRow === row.row_number && row.warnings.map(w => html`<p key=${w} class="df-warning">${w}</p>`)}
            </div>`}
            ${openRow === row.row_number && html`<div class="df-row-body">
              ${row.status !== "invalid" ? html`<${InfoBoxes} row=${row} recordType=${recordType} catalog=${catalog}/>`
                : html`<p class="df-muted">Correct the errors above in the file and check it again.</p>`}
              ${row.missing.length > 0 && html`<p class="df-muted">Missing optional information: ${row.missing.join(", ")}.</p>`}
              <details class="df-original"><summary>Values as entered</summary>
                <dl>${Object.entries(row.values).filter(([, v]) => String(v).trim()).map(([k, v]) => html`<div key=${k}>
                  <dt>${k}</dt><dd>${v}</dd></div>`)}</dl></details>
            </div>`}
          </li>`)}
        </ul>
      </section>

      <section class="discovery-card df-confirm">
        <h3>Confirm</h3>
        ${!preview.staging_configured && html`<p class="discovery-message error">Storing records is not
          configured on this instance. You can still check files.</p>`}
        <div class="discovery-field">
          <label class="discovery-label" for="df-import-name">Import Name <span class="df-req">*</span></label>
          <input id="df-import-name" value=${name} maxlength="120" onInput=${e => setName(e.target.value)}/>
          <small class="df-hint">${IMPORT_NAME_HINT}</small>
        </div>
        ${counts.needs_correction > 0 && html`<label class="df-check">
          <input type="checkbox" checked=${accept} onChange=${e => setAccept(e.target.checked)}/>
          ${leftOutLine(counts.needs_correction)}</label>`}
        <label class="df-check"><input type="checkbox" checked=${attestSource}
          onChange=${e => setAttestSource(e.target.checked)}/> ${ATTEST_SOURCE}</label>
        <div class="df-verified">
          <p>The records are stored in the <strong>Ecosystem Directory</strong> through the same checks as
            every directory record, and labelled as an import made on your attestation (the file and the row).
            A record that matches one already in the directory updates it instead of adding a copy.
            ${recordType === "actor" && html` Missing information is completed by COMPASS from each organization's
              own pages first: only empty fields, your values are never replaced (about $0.05 per organization,
              at most $${completionCap(send).toFixed(2)} for this import).`}</p>
          <label class="df-check"><input type="checkbox" checked=${attestAuthorized}
            onChange=${e => setAttestAuthorized(e.target.checked)}/> ${ATTEST_AUTHORIZED}</label>
        </div>
        <div class="discovery-actions">
          <button type="button" class="btn" disabled=${busy || !canSend({preview, name,
            attestSource, admission, attestAuthorized, accept})} onClick=${confirm}>
            ${busy ? "Storing… (this can take a few minutes)" : "Store in the Directory"}</button>
        </div>
        ${send === 0 && html`<p class="df-muted">There is nothing new to send.</p>`}
      </section>
    </div>`;
  }

  function Completion({item, onClose}) {
    const [estimate, setEstimate] = useState(null);
    const [cap, setCap] = useState("1.00");
    const [agree, setAgree] = useState(false);
    const [state, setState] = useState({busy: true, error: "", started: null});
    useEffect(() => {
      let live = true;
      api(`/api/datafeed/imports/${item.run_id}/estimate`, {method: "POST"})
        .then(r => { if (live) { setEstimate(r); setCap(Math.min(5, Math.max(0.1, Number(r.estimated_usd || 0) * 1.5)).toFixed(2)); setState({busy: false, error: "", started: null}); } })
        .catch(e => live && setState({busy: false, error: e.message, started: null}));
      return () => { live = false; };
    }, [item.run_id]);
    async function start() {
      setState(s => ({...s, busy: true, error: ""}));
      try {
        const r = await api(`/api/datafeed/imports/${item.run_id}/complete`, {method: "POST",
          body: JSON.stringify({max_usd: Number(cap), confirmed: agree})});
        setState({busy: false, error: "", started: r});
      } catch (e) {
        setState({busy: false, error: e.message, started: null});
      }
    }
    return html`<div class="df-completion" role="dialog" aria-label="Complete missing information">
      <h4>Complete missing information with AI</h4>
      <p class="df-muted">The Light Pull reads each organization's own homepage, About page and one
        topic page, and fills only the boxes that are empty. Values you supplied are never replaced;
        new findings show their sources in Review Results, where any conflict is decided.</p>
      ${state.busy && !estimate && html`<p>Estimating…</p>`}
      ${state.error && html`<p class="discovery-message error">${state.error}</p>`}
      ${estimate && html`<p><strong>${costLine(estimate)}</strong></p>
        ${(estimate.organisations || []).length > 0 && html`<ul class="df-notes">
          ${estimate.organisations.slice(0, 8).map(o => html`<li key=${o.candidate_id}>${boxesLine(o)}</li>`)}</ul>`}`}
      ${estimate && (estimate.organisations || []).length > 0 && !state.started && html`
        <div class="df-cap"><label class="discovery-label" for="df-cap">Spending cap (USD)</label>
          <input id="df-cap" type="number" min="0.01" max="5" step="0.01" value=${cap}
            onInput=${e => setCap(e.target.value)}/></div>
        <label class="df-check"><input type="checkbox" checked=${agree}
          onChange=${e => setAgree(e.target.checked)}/> ${approveLine(cap)}</label>
        <div class="discovery-actions">
          <button class="btn" disabled=${!agree || state.busy || !(Number(cap) > 0)} onClick=${start}>Start the read</button>
          <button class="btn ghost" onClick=${onClose}>Cancel</button>
        </div>`}
      ${state.started && html`<p class="discovery-message success">Started for
        ${state.started.organisations} organization${state.started.organisations === 1 ? "" : "s"}
        (cap $${Number(state.started.max_usd).toFixed(2)}). The boxes appear in Review Results as each one is read.</p>
        <button class="btn ghost" onClick=${onClose}>Close</button>`}
    </div>`;
  }

  /** The example import's details: nothing is fetched, nothing is in the database. */
  function ExampleDetails({item}) {
    return html`<div class="df-import-details">
      <p class="df-example-tag">Example · not real data, and not stored in the database</p>
      <p class="df-import-facts"><strong>${recordCount(item)}</strong> · ${usDate(item.uploaded_at)} · <a
        href="/api/datafeed/example-import.xlsx" download>Excel sheet: ${item.file_name}</a></p>
      <p class="df-muted">${historyLine(item)}</p>
      <div class="df-records"><table class="discovery-runs"><thead><tr><th>Row</th><th>Record</th><th>Status</th></tr></thead>
        <tbody>${item.records.map(r => html`<tr key=${r.row_number}><td>${r.row_number}</td><td>${r.name}</td>
          <td>${r.status}</td></tr>`)}</tbody></table></div>
    </div>`;
  }

  /** One import's details, opened from its row: records, file, counts and actions. */
  function ImportDetails({item, records, completing, setCompleting}) {
    return html`<div class="df-import-details">
      <p class="df-muted">${historyMeta(item)}</p>
      <p class="df-import-facts"><strong>${recordCount(item)}</strong>
        ${item.has_file ? html` · <a href=${`/api/datafeed/imports/${item.run_id}/file`} download>${item.method === "upload"
          ? `Original file: ${item.file_name || "download"}` : `Excel sheet: ${item.import_name}.xlsx`}</a>`
          : item.method === "upload" ? " · Original file not kept" : " · Entered by hand"}</p>
      <p class="df-muted">${historyLine(item)}</p>
      <div class="discovery-actions">
        ${item.counts.pending > 0 && html`<button class="btn ghost" onClick=${() => openImportInReview(item.run_id)}>
          ${item.counts.pending} incomplete: open in Review Results</button>`}
        ${item.record_type === "actor" && item.counts.pending > 0 && html`<button class="btn ghost"
          onClick=${() => setCompleting(completing === item.run_id ? null : item.run_id)}>Complete missing information with AI</button>`}
      </div>
      ${completing === item.run_id && html`<${Completion} item=${item} onClose=${() => setCompleting(null)}/>`}
      <div class="df-records">
        ${records?.error ? html`<p class="discovery-message error">${records.error}</p>`
          : !records ? html`<p class="df-muted">Loading…</p>`
          : html`<table class="discovery-runs"><thead><tr><th>Row</th><th>Record</th><th>Status</th></tr></thead>
            <tbody>${records.map(r => html`<tr key=${`${r.row_number}-${r.name}`}>
              <td>${r.row_number ?? ""}</td><td>${r.name}</td><td>${r.status === "Awaiting Review"
                ? html`<button type="button" class="link" onClick=${() => openImportInReview(item.run_id)}>Awaiting Review</button>`
                : r.status}${r.light_pull_read ? " · Light Pull read" : ""}</td></tr>`)}</tbody></table>`}
      </div>
    </div>`;
  }

  function History() {
    const [items, setItems] = useState(null);
    const [error, setError] = useState("");
    const [search, setSearch] = useState("");
    const [category, setCategory] = useState("all");
    const [open, setOpen] = useState(null);
    const [records, setRecords] = useState({});
    const [completing, setCompleting] = useState(null);
    async function load() {
      try {
        setItems((await api("/api/datafeed/history")).imports || []);
      } catch (e) {
        setError(e.message);
      }
    }
    useEffect(() => { load(); }, []);
    async function toggle(item) {
      if (open === item.run_id) { setOpen(null); return; }
      setOpen(item.run_id);
      if (!item.example && !records[item.run_id]) {
        try {
          const r = await api(`/api/datafeed/imports/${item.run_id}`);
          setRecords(map => ({...map, [item.run_id]: r.records}));
        } catch (e) {
          setRecords(map => ({...map, [item.run_id]: {error: e.message}}));
        }
      }
    }
    if (error) return html`<p class="discovery-message error">${error}</p>`;
    if (!items) return html`<p class="df-muted">Loading the import history…</p>`;
    // The signed-in user's imports once accounts exist; every import until then.
    const mine = items;
    const shown = filterImports(mine, search, category);
    // The example finished import, listed after the real ones while it matches the filters.
    const exampleRow = {...EXAMPLE_IMPORT, run_id: "example"};
    const rows = [...shown, ...filterImports([exampleRow], search, category)];
    return html`<div class="df-history-tools">
      <label class="df-search"><span class="sr-only">Search imports by name</span>
        <input type="search" value=${search} placeholder="Search imports by name…"
          onInput=${e => setSearch(e.target.value)}/></label>
      <label class="df-category"><span>Record Type:</span>
        <select value=${category} onChange=${e => setCategory(e.target.value)}>
          <option value="all">All</option>
          ${RECORD_TYPES.map(t => html`<option key=${t.id} value=${t.id}>${t.label}</option>`)}
        </select></label>
    </div>
    <div class="df-history-table">
      <table>
        <thead><tr><th>Import Name</th><th>Record Type</th><th>Date</th><th class="num">Entries</th><th>Status</th></tr></thead>
        <tbody>
          ${rows.length === 0 && html`<tr><td colspan="5" class="df-muted">No import matches this search.</td></tr>`}
          ${rows.map(item => {
            const result = importResult(item);
            return html`<${Fragment} key=${item.run_id}>
              <tr class=${open === item.run_id ? "open" : ""}>
                <td><button type="button" class="df-import-link" aria-expanded=${open === item.run_id}
                    onClick=${() => toggle(item)}>${item.import_name}</button>
                  ${item.example && html` <span class="df-example-chip">Example</span>`}</td>
                <td>${typeInfo(item.record_type).label}</td>
                <td>${usDate(item.uploaded_at)}</td>
                <td class="num">${item.rows_total ?? item.staged ?? 0}</td>
                <td><span class=${"df-result " + result.tone}>${result.tone === "added" ? "✓ " : ""}${result.label}</span></td>
              </tr>
              ${open === item.run_id && html`<tr class="df-import-row"><td colspan="5">
                ${item.example ? html`<${ExampleDetails} item=${item}/>`
                  : html`<${ImportDetails} item=${item} records=${records[item.run_id]}
                    completing=${completing} setCompleting=${setCompleting}/>`}</td></tr>`}
            <//>`;
          })}
        </tbody>
      </table>
    </div>`;
  }

  return function DataFeed() {
    const [catalog, setCatalog] = useState(null);
    const [view, setView] = useState("add");
    // Nothing to fill until a record type is chosen (GHUS, 2026-11-02): each has its own template.
    const [recordType, setRecordType] = useState("");
    const [method, setMethod] = useState("upload");
    // One name for everything submitted together, by file or by hand.
    const [importName, setImportName] = useState("");
    const [preview, setPreview] = useState(null);
    const [done, setDone] = useState(null);
    const [message, setMessage] = useState(null);
    useEffect(() => {
      api("/api/datafeed/catalog").then(setCatalog)
        .catch(e => setMessage({kind: "error", text: e.message}));
    }, []);
    const openReview = () => window.dispatchEvent(new Event("ghus:open-review"));
    const reset = () => { setPreview(null); setDone(null); setMessage(null); setImportName(""); };
    return html`<div class="discovery-page datafeed-page">
      <h1 class="hero-h">Data Feed</h1>
      <p class="lead">${DATAFEED_LEAD}</p>
      ${message && html`<p class=${"discovery-message " + message.kind} role="alert">${message.text}</p>`}
      ${catalog && html`
      <div class="subnav">
        <button class=${view === "add" ? "active" : ""} onClick=${() => setView("add")}>Add Records</button>
        <button class=${view === "history" ? "active" : ""} onClick=${() => setView("history")}>Import History</button>
      </div>
      ${view === "history" && html`<${History}/>`}
      ${view === "add" && html`
        ${!catalog.staging_configured && html`<p class="discovery-message error">Sending records to
          Review is not configured on this instance; files and forms can still be checked.</p>`}
        ${done ? html`<section class="discovery-card df-done">
            <h3>${done.status === "already_imported" ? "Already imported"
              : done.admission === "directory" ? (done.enriching?.started ? "Completing, then storing"
                : "Stored in the Ecosystem Directory") : "Sent to Review Results"}</h3>
            <p>${doneLine(done)}</p>
            ${done.completion && html`<p>${done.completion}</p>`}
            ${[...(done.held_for_review || []), ...(done.not_stored || [])].length > 0 && html`<ul class="df-notes">
              ${[...(done.held_for_review || []), ...(done.not_stored || [])].map(h => html`<li key=${h.row_number}>
                Row ${h.row_number}: ${h.reason}</li>`)}</ul>`}
            <div class="discovery-actions">
              ${done.admission !== "directory" && html`<button class="btn"
                onClick=${() => done.run_id ? openImportInReview(done.run_id) : openReview()}>Open Review</button>`}
              <button class=${done.admission === "directory" ? "btn" : "btn ghost"}
                onClick=${() => { reset(); setView("history"); }}>Import History</button>
              <button class="btn ghost" onClick=${reset}>Add more records</button>
            </div>
          </section>`
        : preview ? html`<${Preview} preview=${preview} catalog=${catalog} importName=${importName}
            onBack=${() => { setPreview(null); setMessage(null); }}
            onDone=${result => { setDone(result); setPreview(null); }} setMessage=${setMessage}/>`
        : html`<section class="discovery-card df-start">
          <div class="discovery-field">
            <label class="discovery-label" for="df-import-name-top">Import Name <span class="df-req">*</span></label>
            <input id="df-import-name-top" value=${importName} maxlength="120"
              placeholder="e.g. San Francisco Diaspora Event Jan 2027" onInput=${e => setImportName(e.target.value)}/>
            <small class="df-hint">${IMPORT_NAME_HINT}</small>
          </div>
          <div class="df-choices">
            <div class="discovery-field">
              <label class="discovery-label" for="df-record-type">Record Type <span class="df-req">*</span></label>
              <select id="df-record-type" value=${recordType}
                onChange=${e => { setRecordType(e.target.value); setMessage(null); }}>
                <option value="" disabled>Choose a record type</option>
                ${RECORD_TYPES.map(t => html`<option key=${t.id} value=${t.id}>${t.label}</option>`)}
              </select>
            </div>
            <div class="discovery-field">
              <label class="discovery-label" for="df-method">How to Add Records <span class="df-req">*</span></label>
              <select id="df-method" value=${method} onChange=${e => setMethod(e.target.value)}>
                <option value="upload">Upload Excel / CSV</option>
                <option value="manual">Add Manually</option>
              </select>
            </div>
          </div>
          ${!recordType ? html`<p class="df-muted df-choose">Choose Organizations, People or Events to
              get its template.</p>`
            : method === "upload"
            ? html`<${UploadCard} key=${recordType} recordType=${recordType} catalog=${catalog}
                importName=${importName} onChecked=${setPreview} setMessage=${setMessage}/>`
            : html`<${ManualForm} key=${recordType} recordType=${recordType} catalog=${catalog}
                importName=${importName} onChecked=${setPreview} setMessage=${setMessage}/>`}
        </section>`}
      `}`}
    </div>`;
  };
}
