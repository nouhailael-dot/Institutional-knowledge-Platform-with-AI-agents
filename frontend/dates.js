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

/**
 * A date field shown and typed as MM/DD/YYYY, with a calendar button.
 *
 * A browser's own date field takes its format from the computer's language
 * settings, so it cannot promise MM/DD/YYYY. This one can: it holds what the
 * person types, reports an ISO day (or "") through ``onChange`` once the text
 * is a whole valid date within ``min``/``max``, and opens the browser's
 * calendar from the button.
 */
export function createDateInput({html, useState, useEffect}) {
  return function DateInput({value = "", onChange, min, max, id, ariaLabel, disabled, className,
    placeholder = "MM/DD/YYYY"}) {
    const [text, setText] = useState(() => usDate(value));
    // A value set from outside (a reset, a hand-off) replaces what is shown.
    useEffect(() => {
      if (isoFromUs(text) !== (value || "")) setText(usDate(value));
    }, [value]);
    const iso = isoFromUs(text);
    const outside = Boolean(iso) && ((min && iso < min) || (max && iso > max));
    const invalid = text.trim() !== "" && (!iso || outside);

    function typed(next) {
      setText(next);
      const day = isoFromUs(next);
      if (!next.trim()) onChange("");
      else if (day && !(min && day < min) && !(max && day > max)) onChange(day);
    }

    function openCalendar(event) {
      const picker = event.currentTarget.nextElementSibling;
      try { picker.showPicker(); } catch { picker.focus(); picker.click(); }
    }

    return html`<span class=${"date-input" + (invalid ? " invalid" : "") + (className ? ` ${className}` : "")}>
      <input type="text" inputMode="numeric" placeholder=${placeholder} maxLength="10" autoComplete="off"
        id=${id} aria-label=${ariaLabel} value=${text} disabled=${disabled} aria-invalid=${invalid}
        title=${invalid ? (outside ? "Outside the allowed dates" : "Use MM/DD/YYYY") : undefined}
        onInput=${(e) => typed(e.target.value)}
        onBlur=${() => { if (!invalid) setText(usDate(value)); }}/>
      <button type="button" class="date-input-pick" aria-label="Open calendar" title="Open calendar"
        disabled=${disabled} onClick=${openCalendar}><svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true"><rect x="3.5" y="5" width="17" height="15" rx="2" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M3.5 9.5h17M8 3v4M16 3v4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></button>
      <input type="date" class="date-input-native" tabIndex="-1" aria-hidden="true"
        value=${value || ""} min=${min} max=${max}
        onChange=${(e) => { setText(usDate(e.target.value)); onChange(e.target.value); }}/>
    </span>`;
  };
}
