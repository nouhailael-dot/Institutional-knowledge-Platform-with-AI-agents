// Every date on the platform is shown the US way - MM/DD/YYYY, and a time of
// day as 3:05 PM - from this one place, so no page drifts to another format.

const pad = (n) => String(n).padStart(2, "0");

/**
 * A Date from what the API sends: a calendar day ("2026-10-26"), a timestamp
 * ("2026-10-26T17:38:00+00:00"), epoch seconds, or a Date. A calendar day is
 * read by its parts: through the Date constructor it would be UTC midnight and
 * show the previous day west of Greenwich.
 */
function parse(value) {
  if (value === null || value === undefined || value === "") return null;
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  if (typeof value === "number") return new Date(value * 1000);
  const day = String(value).match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (day) return new Date(Number(day[1]), Number(day[2]) - 1, Number(day[3]));
  const d = new Date(String(value));
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
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) return usDate(d);
  return `${usDate(d)}, ${d.toLocaleTimeString("en-US", {hour: "numeric", minute: "2-digit"})}`;
}
