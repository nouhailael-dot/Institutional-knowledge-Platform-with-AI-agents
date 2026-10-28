// Data Feed: GHUS adds Actors, People and Events - from the official template
// (Excel or CSV) or by hand - and sends them to Review.
//
// Choose type -> download the template or open the form -> check -> preview
// -> confirm -> Review. The page never writes a record: checking is read-only,
// and confirming hands the records to the GHUS backend, which stages them for
// Review. Nothing is added to the map, or verified, without a GHUS decision.

import {lightPullBoxes, formatFactValue} from "./review.js?v=20261028a";
import {createDateInput, usDate, usDateTime} from "./dates.js?v=20261028a";

export const RECORD_TYPES = [
  {id: "actor", label: "Actors / Organizations", short: "Actors", noun: "organization"},
  {id: "person", label: "People", short: "People", noun: "person"},
  {id: "event", label: "Events", short: "Events", noun: "event"},
];

export const STATUS = {
  invalid: {label: "Needs correction", tone: "error"},
  new: {label: "New record", tone: "ok"},
  existing: {label: "Matches an existing record", tone: "info"},
  possible: {label: "Possible duplicate", tone: "warn"},
  waiting: {label: "Already waiting in Review", tone: "muted"},
};

export const FILTERS = [
  {id: "all", label: "All"},
  {id: "invalid", label: "Needs correction"},
  {id: "new", label: "New"},
  {id: "existing", label: "Existing matches"},
  {id: "possible", label: "Possible duplicates"},
  {id: "waiting", label: "Already in Review"},
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
    {key: "already_waiting", label: "Already in Review", value: counts.already_waiting ?? 0,
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
  return send === 1 ? "Send 1 record to Review" : `Send ${send} records to Review`;
}

export function stageable(counts = {}) {
  return Math.max(0, (counts.valid ?? 0) - (counts.already_waiting ?? 0));
}

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
  return row?.payload?.name || row?.values?.["Official name *"] || row?.values?.["Full name *"]
    || row?.values?.["Event name *"] || `Row ${row?.row_number ?? ""}`;
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

/** One history row's counts, in words. */
export function historyLine(item) {
  const c = item?.counts || {};
  return [
    `${item?.staged ?? 0} staged`,
    c.pending ? `${c.pending} awaiting Review` : null,
    c.approved_new ? `${c.approved_new} approved and added` : null,
    c.matched_existing ? `${c.matched_existing} matched to existing` : null,
    c.rejected ? `${c.rejected} rejected` : null,
    c.deferred ? `${c.deferred} deferred` : null,
    item?.already_awaiting_review ? `${item.already_awaiting_review} already in Review` : null,
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
export const ATTEST_AUTHORIZED = "I am authorized GHUS staff and I verify the organizations in "
  + "this import.";

/** The confirm button may be pressed. */
export function canSend({preview, name, uploader, attestSource, admission, attestAuthorized,
  accept}) {
  const counts = preview?.counts || {};
  return Boolean(preview?.can_confirm && String(name || "").trim()
    && String(uploader || "").trim() && attestSource
    && (admission !== "verified" || attestAuthorized)
    && (!counts.needs_correction || accept));
}

/** What happened when the records were sent. */
export function doneLine(done = {}) {
  if (done.status === "already_imported") {
    return "This exact file was imported before; nothing was sent twice.";
  }
  if (done.admission === "verified") {
    const verified = done.verified || 0;
    const held = (done.held_for_review || []).length;
    const parts = [`${plural(verified, "organization was", "organizations were")} added to the map `
      + `as Verified, on ${done.uploaded_by || "the uploader"}'s attestation.`];
    if (held) parts.push(`${plural(held, "record waits", "records wait")} in Review.`);
    const left = done.left_out || 0;
    if (left) parts.push(`${left} needed correction and ${left === 1 ? "was" : "were"} left out.`);
    return parts.join(" ");
  }
  const parts = [`${plural(done.staged ?? 0, "record now waits", "records now wait")} in Review `
    + `as “Data Feed import · ${done.import_name}”.`];
  const waiting = done.already_awaiting_review || 0;
  if (waiting) {
    parts.push(`${waiting} ${waiting === 1 ? "was" : "were"} already waiting in Review and not `
      + "sent again.");
  }
  const left = done.left_out || 0;
  if (left) parts.push(`${left} needed correction and ${left === 1 ? "was" : "were"} left out.`);
  return parts.join(" ");
}

/** "Actors / Organizations · file.xlsx · Oct 26, 2026 · Uploaded by Not recorded (no sign-in yet)" */
export function historyMeta(item = {}) {
  return [typeInfo(item.record_type).label,
    item.method === "upload" ? item.file_name : "Manual entry",
    formatDateTime(item.uploaded_at),
    `Uploaded by ${item.uploaded_by ? `${item.uploaded_by} (as typed; no sign-in yet)`
      : "Not recorded"}`,
    item.admission === "verified" ? "Imported as Verified" : "Sent to Review",
  ].filter(Boolean).join(" · ");
}

export function formatDateTime(value) {
  return value ? usDateTime(value) : "";
}

const UPLOADER_KEY = "ghus.datafeed.uploader";

function rememberedUploader() {
  try { return window.localStorage.getItem(UPLOADER_KEY) || ""; } catch { return ""; }
}

function rememberUploader(value) {
  try { window.localStorage.setItem(UPLOADER_KEY, value); } catch { /* a private window */ }
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
export function createDataFeedPage({html, useState, useEffect}) {
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

  function ManualForm({recordType, catalog, onChecked, setMessage}) {
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
    return html`<section class="discovery-card df-form">
      ${drafts.map((draft, index) => html`<div key=${index} class=${"df-record" + (open === index ? " open" : "")}>
        <button type="button" class="df-record-head" aria-expanded=${open === index}
          onClick=${() => setOpen(open === index ? -1 : index)}>
          <span>Record ${index + 1}${draft.name ? ` · ${draft.name}` : ""}</span>
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
                  <label class="discovery-label" for=${`df-${field.key}`}>${field.header}${field.required ? " *" : ""}</label>
                  <${Control} field=${field} value=${draft[field.key]} vocab=${vocab}
                    category=${categoryCode(draft)} onChange=${(k, v) => update(index, k, v)}/>
                  <small class="df-hint">${field.description}</small>
                </div>`)}
              </div>
            </fieldset>`;
          })}
          ${drafts.length > 1 && html`<button type="button" class="btn ghost danger"
            onClick=${() => { setDrafts(list => list.filter((_, i) => i !== index)); setOpen(-1); }}>
            Remove this record</button>`}
        </div>`}
      </div>`)}
      <div class="discovery-actions">
        <button type="button" class="btn ghost" disabled=${drafts.length >= catalog.limits.max_manual_rows}
          onClick=${() => { setDrafts(list => [...list, {}]); setOpen(drafts.length); }}>Add another record</button>
        <button type="button" class="btn" disabled=${busy} onClick=${check}>
          ${busy ? "Checking…" : `Check ${drafts.length === 1 ? "record" : `${drafts.length} records`}`}</button>
      </div>
    </section>`;
  }

  function UploadCard({recordType, catalog, onChecked, setMessage}) {
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
    return html`<section class="discovery-card df-upload">
      <h3>Upload Excel or CSV</h3>
      <p class="df-muted">Download the official template, fill one record per row, and upload it.
        Required columns are marked *; the Field Guide sheet explains every column.</p>
      <div class="df-downloads">
        <a class="btn ghost" href=${`/api/datafeed/templates/${recordType}.xlsx`} download>Excel template (.xlsx)</a>
        <a class="btn ghost" href=${`/api/datafeed/templates/${recordType}.csv`} download>CSV template (.csv)</a>
      </div>
      <label class=${"df-drop" + (drag ? " drag" : "")}
        onDragOver=${e => { e.preventDefault(); setDrag(true); }}
        onDragLeave=${() => setDrag(false)}
        onDrop=${e => { e.preventDefault(); setDrag(false); choose(e.dataTransfer.files?.[0]); }}>
        <input type="file" accept=".xlsx,.csv" onChange=${e => choose(e.target.files?.[0])}/>
        <strong>${file ? file.name : "Choose a file or drop it here"}</strong>
        <span>${file ? `${(file.size / 1024).toFixed(0)} KB` : `.xlsx or .csv · up to ${catalog.limits.max_rows} rows · 5 MB`}</span>
      </label>
      <div class="discovery-actions">
        <button type="button" class="btn" disabled=${!file || busy} onClick=${check}>
          ${busy ? "Checking the file…" : "Check file"}</button>
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

  function Preview({preview, catalog, onBack, onDone, setMessage}) {
    const [filter, setFilter] = useState(preview.counts.needs_correction ? "invalid" : "all");
    const [openRow, setOpenRow] = useState(null);
    const [name, setName] = useState(defaultImportName(preview));
    const [accept, setAccept] = useState(false);
    const [uploader, setUploader] = useState(() => rememberedUploader());
    const [attestSource, setAttestSource] = useState(false);
    const [admission, setAdmission] = useState("review");
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
        rememberUploader(uploader.trim());
        const result = await api(`/api/datafeed/previews/${preview.preview_id}/confirm`, {
          method: "POST", body: JSON.stringify({import_name: name, accept_left_out: accept,
            uploaded_by: uploader, attest_source: attestSource, admission,
            attest_authorized: admission === "verified" && attestAuthorized})});
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
            <p class="df-muted">Nothing has been saved. Check the records, then send them to Review.</p>
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
              ${matchLine(row.match) && html`<p class="df-match">${matchLine(row.match)}. Review will offer “Same as existing”.</p>`}
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
        ${!preview.staging_configured && html`<p class="discovery-message error">Sending records to
          Review is not configured on this instance. You can still check files.</p>`}
        <div class="discovery-field">
          <label class="discovery-label" for="df-import-name">Import name</label>
          <input id="df-import-name" value=${name} maxlength="120" onInput=${e => setName(e.target.value)}/>
          <small class="df-hint">Shown in Review as “Data Feed import · ${name || "…"}” and in Import history.</small>
        </div>
        ${counts.needs_correction > 0 && html`<label class="df-check">
          <input type="checkbox" checked=${accept} onChange=${e => setAccept(e.target.checked)}/>
          ${leftOutLine(counts.needs_correction)}</label>`}
        <div class="discovery-field">
          <label class="discovery-label" for="df-uploader">Your name</label>
          <input id="df-uploader" value=${uploader} maxlength="120" autocomplete="name"
            onInput=${e => setUploader(e.target.value)}/>
          <small class="df-hint">Recorded as the uploader, separately from whoever reviews the records.
            There is no sign-in yet, so it is recorded as you type it.</small>
        </div>
        <label class="df-check"><input type="checkbox" checked=${attestSource}
          onChange=${e => setAttestSource(e.target.checked)}/> ${ATTEST_SOURCE}</label>
        <div class="discovery-segment df-admission" role="group" aria-label="What happens to the records">
          <button type="button" class=${admission === "review" ? "active" : ""} aria-pressed=${admission === "review"}
            onClick=${() => setAdmission("review")}>Send to Review</button>
          ${recordType === "actor" && html`<button type="button" class=${admission === "verified" ? "active" : ""}
            aria-pressed=${admission === "verified"} onClick=${() => setAdmission("verified")}>Add as Verified</button>`}
        </div>
        ${admission === "review" ? html`<p class="df-muted">The records wait in Review. A GHUS reviewer adds
          each one, matches it to an existing record, or rejects it. Nothing is verified because it was
          imported; your values are kept as entered and labelled Imported.</p>`
        : html`<div class="df-verified">
          <p>New organizations are added to the map as <strong>Verified</strong> at once, through the same
            admission checks as Review, and labelled as an import made on your attestation (your name, the
            file and the row). Records that may already be on the map, or have no Category Type, still go
            to Review. A reviewer can reject any of them later. Deep Pull still needs a reviewer's
            verification.</p>
          <label class="df-check"><input type="checkbox" checked=${attestAuthorized}
            onChange=${e => setAttestAuthorized(e.target.checked)}/> ${ATTEST_AUTHORIZED}</label>
        </div>`}
        <div class="discovery-actions">
          <button type="button" class="btn" disabled=${busy || !canSend({preview, name, uploader,
            attestSource, admission, attestAuthorized, accept})} onClick=${confirm}>
            ${busy ? (admission === "verified" ? "Adding… (this can take a few minutes)" : "Sending…")
              : admission === "verified" ? "Add to the map as Verified" : confirmLabel(counts)}</button>
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
        new findings show their sources in Review, where any conflict is decided.</p>
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
        (cap $${Number(state.started.max_usd).toFixed(2)}). The boxes appear in Review as each one is read.</p>
        <button class="btn ghost" onClick=${onClose}>Close</button>`}
    </div>`;
  }

  function History({onOpenReview}) {
    const [items, setItems] = useState(null);
    const [error, setError] = useState("");
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
      if (!records[item.run_id]) {
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
    if (!items.length) return html`<p class="discovery-empty">No imports yet. Records you send to
      Review appear here, with what Review decided.</p>`;
    return html`<ul class="df-history">
      ${items.map(item => html`<li key=${item.run_id} class="discovery-request">
        <div class="discovery-request-head">
          <div>
            <h3>${item.import_name}</h3>
            <p>${historyMeta(item)}</p>
          </div>
          <span class=${"discovery-status " + (item.status === "Reviewed" ? "active" : "paused")}>${item.status}</span>
        </div>
        <p class="df-muted">${historyLine(item)}${item.rows_total ? ` · ${item.rows_total} rows in the file` : ""}</p>
        <div class="discovery-actions">
          <button class="btn ghost" onClick=${() => toggle(item)}>${open === item.run_id ? "Hide records" : "Show records"}</button>
          ${item.counts.pending > 0 && html`<button class="btn ghost" onClick=${onOpenReview}>Open Review</button>`}
          ${item.record_type === "actor" && item.counts.pending > 0 && html`<button class="btn ghost"
            onClick=${() => setCompleting(completing === item.run_id ? null : item.run_id)}>Complete missing information with AI</button>`}
        </div>
        ${completing === item.run_id && html`<${Completion} item=${item} onClose=${() => setCompleting(null)}/>`}
        ${open === item.run_id && html`<div class="df-records">
          ${records[item.run_id]?.error ? html`<p class="discovery-message error">${records[item.run_id].error}</p>`
            : !records[item.run_id] ? html`<p class="df-muted">Loading…</p>`
            : html`<table class="discovery-runs"><thead><tr><th>Row</th><th>Record</th><th>Status</th></tr></thead>
              <tbody>${records[item.run_id].map(r => html`<tr key=${`${r.row_number}-${r.name}`}>
                <td>${r.row_number ?? ""}</td><td>${r.name}</td><td>${r.status}${r.light_pull_read ? " · Light Pull read" : ""}</td></tr>`)}</tbody></table>`}
        </div>`}
      </li>`)}
    </ul>`;
  }

  return function DataFeed() {
    const [catalog, setCatalog] = useState(null);
    const [view, setView] = useState("add");
    const [recordType, setRecordType] = useState("actor");
    const [method, setMethod] = useState("upload");
    const [preview, setPreview] = useState(null);
    const [done, setDone] = useState(null);
    const [message, setMessage] = useState(null);
    useEffect(() => {
      api("/api/datafeed/catalog").then(setCatalog)
        .catch(e => setMessage({kind: "error", text: e.message}));
    }, []);
    const openReview = () => window.dispatchEvent(new Event("ghus:open-review"));
    const reset = () => { setPreview(null); setDone(null); setMessage(null); };
    return html`<div class="discovery-page datafeed-page">
      <div class="eyebrow">Data Feed</div>
      <h1 class="hero-h">Add actors, people and events to the map.</h1>
      <p class="lead">Upload the GHUS template or enter records by hand. Every record is checked
        and previewed, then sent to Review - nothing is added or verified without a GHUS decision.</p>
      ${message && html`<p class=${"discovery-message " + message.kind} role="alert">${message.text}</p>`}
      ${catalog && html`
      <div class="subnav">
        <button class=${view === "add" ? "active" : ""} onClick=${() => setView("add")}>Add records</button>
        <button class=${view === "history" ? "active" : ""} onClick=${() => setView("history")}>Import history</button>
      </div>
      ${view === "history" && html`<${History} onOpenReview=${openReview}/>`}
      ${view === "add" && html`
        ${!catalog.staging_configured && html`<p class="discovery-message error">Sending records to
          Review is not configured on this instance; files and forms can still be checked.</p>`}
        ${done ? html`<section class="discovery-card df-done">
            <h3>${done.status === "already_imported" ? "Already imported" : "Sent to Review"}</h3>
            <p>${doneLine(done)}</p>
            ${(done.held_for_review || []).length > 0 && html`<ul class="df-notes">
              ${done.held_for_review.map(h => html`<li key=${h.row_number}>Row ${h.row_number}: ${h.reason}</li>`)}</ul>`}
            <div class="discovery-actions">
              <button class="btn" onClick=${openReview}>Open Review</button>
              <button class="btn ghost" onClick=${() => { reset(); setView("history"); }}>Import history</button>
              <button class="btn ghost" onClick=${reset}>Add more records</button>
            </div>
          </section>`
        : preview ? html`<${Preview} preview=${preview} catalog=${catalog}
            onBack=${() => { setPreview(null); setMessage(null); }}
            onDone=${result => { setDone(result); setPreview(null); }} setMessage=${setMessage}/>`
        : html`
          <div class="df-choices">
            <div class="discovery-field">
              <label class="discovery-label" for="df-record-type">Record type</label>
              <select id="df-record-type" value=${recordType}
                onChange=${e => { setRecordType(e.target.value); setMessage(null); }}>
                ${RECORD_TYPES.map(t => html`<option key=${t.id} value=${t.id}>${t.label}</option>`)}
              </select>
            </div>
            <div class="discovery-field">
              <label class="discovery-label" for="df-method">How to add them</label>
              <select id="df-method" value=${method} onChange=${e => setMethod(e.target.value)}>
                <option value="upload">Upload Excel / CSV</option>
                <option value="manual">Add manually</option>
              </select>
            </div>
          </div>
          ${method === "upload"
            ? html`<${UploadCard} recordType=${recordType} catalog=${catalog} onChecked=${setPreview} setMessage=${setMessage}/>`
            : html`<${ManualForm} recordType=${recordType} catalog=${catalog} onChecked=${setPreview} setMessage=${setMessage}/>`}
        `}
      `}`}
    </div>`;
  };
}
