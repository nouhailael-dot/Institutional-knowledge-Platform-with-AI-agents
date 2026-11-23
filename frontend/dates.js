// Every date on the platform is shown and typed the US way - MM/DD/YYYY, and a
// time of day as 3:05 PM - from this one place, so no page drifts to another
// format. Dates still travel to and from the API as ISO (YYYY-MM-DD).

const pad = (n) => String(n).padStart(2, "0");
const ISO_DAY = /^(\d{4})-(\d{2})-(\d{2})$/;
const ISO_TIMESTAMP = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/;

/**
 * A Date from what the API sends: a calendar day ("2026-10-26"), a timestamp
 * ("2026-10-26T17:38:00+00:00", or PostgreSQL's "2026-10-26 17:38:00+00"),
 * epoch seconds, or a Date. Anything else - "March 2026", "Spring 2027" - is not
 * a day and is never turned into one. A calendar day is read by its parts:
 * through the Date constructor it would be UTC midnight and show the previous
 * day west of Greenwich.
 */
function parse(value) {
  if (value === null || value === undefined || value === "") return null;
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  if (typeof value === "number") return new Date(value * 1000);
  const text = String(value).trim();
  const day = text.match(ISO_DAY);
  if (day) return new Date(Number(day[1]), Number(day[2]) - 1, Number(day[3]));
  if (!ISO_TIMESTAMP.test(text)) return null;
  const d = new Date(text.replace(" ", "T").replace(/([+-]\d{2})$/, "$1:00"));
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "10/26/2026". Anything that is not a date is shown as given. */
export function usDate(value) {
  const d = parse(value);
  if (!d) return value === null || value === undefined ? "" : String(value);
  return `${pad(d.getMonth() + 1)}/${pad(d.getDate())}/${d.getFullYear()}`;
}

/** "10/26/2026, 5:38 PM"; a calendar day with no time stays "10/26/2026". */
export function usDateTime(value) {
  const d = parse(value);
  if (!d) return value === null || value === undefined ? "" : String(value);
  if (typeof value === "string" && ISO_DAY.test(value.trim())) return usDate(d);
  return `${usDate(d)}, ${d.toLocaleTimeString("en-US", {hour: "numeric", minute: "2-digit"})}`;
}

/** "10/26/2026" -> "2026-10-26"; "" unless it is a whole, real date (not 10/26/26, not 02/30/2026). */
export function isoFromUs(text) {
  const value = String(text ?? "").trim();
  if (ISO_DAY.test(value)) return value;
  const m = value.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (!m) return "";
  const [month, day, year] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const d = new Date(year, month - 1, day);
  if (d.getFullYear() !== year || d.getMonth() !== month - 1 || d.getDate() !== day) return "";
  return `${year}-${pad(month)}-${pad(day)}`;
}

export const MONTHS = ["January", "February", "March", "April", "May", "June", "July",
  "August", "September", "October", "November", "December"];
export const WEEKDAYS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

const isoOf = (y, m, d) => `${y}-${pad(m + 1)}-${pad(d)}`;

/**
 * One month as weeks of seven ISO days, Sunday first (the US calendar); days
 * of the neighbouring months are null.
 */
export function monthGrid(year, month) {
  const first = new Date(year, month, 1).getDay();
  const days = new Date(year, month + 1, 0).getDate();
  const cells = [...Array(first).fill(null),
    ...Array.from({length: days}, (_, i) => isoOf(year, month, i + 1))];
  while (cells.length % 7) cells.push(null);
  return Array.from({length: cells.length / 7}, (_, w) => cells.slice(w * 7, w * 7 + 7));
}

/** {year, month} one month before or after. */
export function shiftMonth({year, month}, by) {
  const d = new Date(year, month + by, 1);
  return {year: d.getFullYear(), month: d.getMonth()};
}

let calendarIds = 0;

/**
 * A date field shown and typed as MM/DD/YYYY, with a calendar button.
 *
 * A browser's own date field and calendar take their language and format from
 * the computer's settings (French on a French Windows), so they cannot promise
 * an English, MM/DD/YYYY calendar. This one can: it holds what the person
 * types, reports an ISO day (or "") through ``onChange`` once the text is a
 * whole valid date within ``min``/``max``, and its button opens COMPASS's own
 * English calendar (10 Nov 2026), Sunday first, days outside min/max disabled.
 */
export function createDateInput({html, useState, useEffect}) {
  return function DateInput({value = "", onChange, min, max, id, ariaLabel, disabled, className,
    placeholder = "MM/DD/YYYY"}) {
    const [text, setText] = useState(() => usDate(value));
    const [open, setOpen] = useState(false);
    const [shown, setShown] = useState(null);
    const [up, setUp] = useState(false);
    const [cal] = useState(() => `cal-${++calendarIds}`);
    // A value set from outside (a reset, a hand-off) replaces what is shown.
    useEffect(() => {
      if (isoFromUs(text) !== (value || "")) setText(usDate(value));
    }, [value]);
    // A click elsewhere or Escape closes the calendar.
    useEffect(() => {
      if (!open) return undefined;
      const away = (e) => { if (!e.target.closest?.(`[data-cal="${cal}"]`)) setOpen(false); };
      const key = (e) => { if (e.key === "Escape") setOpen(false); };
      document.addEventListener("mousedown", away);
      document.addEventListener("keydown", key);
      return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", key); };
    }, [open]);
    const iso = isoFromUs(text);
    const outside = Boolean(iso) && ((min && iso < min) || (max && iso > max));
    const invalid = text.trim() !== "" && (!iso || outside);

    function typed(next) {
      setText(next);
      const day = isoFromUs(next);
      if (!next.trim()) onChange("");
      else if (day && !(min && day < min) && !(max && day > max)) onChange(day);
    }

    function toggle(event) {
      if (open) { setOpen(false); return; }
      const start = parse(value || iso) || parse(min) || new Date();
      setShown({year: start.getFullYear(), month: start.getMonth()});
      // Open upward when the window has no room below for the month.
      const box = event?.currentTarget?.getBoundingClientRect?.();
      setUp(Boolean(box) && box.bottom + 310 > window.innerHeight && box.top > 310);
      setOpen(true);
    }

    function pick(day) {
      setText(usDate(day));
      onChange(day);
      setOpen(false);
    }

    const now = new Date();
    const today = isoOf(now.getFullYear(), now.getMonth(), now.getDate());
    const allowed = (day) => !(min && day < min) && !(max && day > max);

    return html`<span class=${"date-input" + (invalid ? " invalid" : "") + (className ? ` ${className}` : "")}
      data-cal=${cal}>
      <input type="text" inputMode="numeric" placeholder=${placeholder} maxLength="10" autoComplete="off"
        id=${id} aria-label=${ariaLabel} value=${text} disabled=${disabled} aria-invalid=${invalid}
        title=${invalid ? (outside ? "Outside the allowed dates" : "Use MM/DD/YYYY") : undefined}
        onInput=${(e) => typed(e.target.value)}
        onBlur=${() => { if (!invalid) setText(usDate(value)); }}/>
      <button type="button" class="date-input-pick" aria-label="Open calendar" title="Open calendar"
        aria-expanded=${open} disabled=${disabled} onClick=${toggle}><svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true"><rect x="3.5" y="5" width="17" height="15" rx="2" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M3.5 9.5h17M8 3v4M16 3v4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></button>
      ${open && shown && html`<div class=${"date-cal" + (up ? " up" : "")} role="dialog" aria-label="Choose a date">
        <div class="date-cal-head">
          <button type="button" aria-label="Previous month" onClick=${() => setShown(shiftMonth(shown, -1))}>‹</button>
          <strong>${MONTHS[shown.month]} ${shown.year}</strong>
          <button type="button" aria-label="Next month" onClick=${() => setShown(shiftMonth(shown, 1))}>›</button>
        </div>
        <table class="date-cal-grid" role="grid">
          <thead><tr>${WEEKDAYS.map(d => html`<th key=${d} scope="col">${d}</th>`)}</tr></thead>
          <tbody>${monthGrid(shown.year, shown.month).map((week, w) => html`<tr key=${w}>
            ${week.map((day, i) => html`<td key=${i}>${day && html`<button type="button"
              class=${"date-cal-day" + (day === value ? " selected" : "") + (day === today ? " today" : "")}
              aria-label=${usDate(day)} aria-pressed=${day === value} disabled=${!allowed(day)}
              onClick=${() => pick(day)}>${Number(day.slice(8))}</button>`}</td>`)}
          </tr>`)}</tbody>
        </table>
        <div class="date-cal-foot">
          <button type="button" disabled=${!allowed(today)} onClick=${() => pick(today)}>Today</button>
          ${value && html`<button type="button" onClick=${() => { setText(""); onChange(""); setOpen(false); }}>Clear</button>`}
        </div>
      </div>`}
    </span>`;
  };
}

/** An event's span (4 Nov 2026): "03/01/2027 – 03/04/2027 (4 days)", or its one day.
 *  An end date missing, the same as the start or before it shows the start only. */
export function eventSpan(start, end) {
  const first = parse(start);
  if (!first) return "";
  const last = parse(end);
  if (!last || last <= first) return usDate(first);
  const days = Math.round((Date.UTC(last.getFullYear(), last.getMonth(), last.getDate())
    - Date.UTC(first.getFullYear(), first.getMonth(), first.getDate())) / 86400000) + 1;
  return `${usDate(first)} – ${usDate(last)} (${days} days)`;
}
