// Event times: the server stores UTC instants plus the host's IANA zone. The form
// works in the viewer's own zone (native date and time inputs, which stay usable
// in RTL when given dir="ltr"), and pages show times in the viewer's locale and zone.

/** The viewer's IANA time zone, or UTC when the browser will not say. */
export function viewerTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

const pad = (n: number) => String(n).padStart(2, "0");

/** An instant as the `date` and `time` input values in the viewer's zone. */
export function toInputParts(iso: string | null | undefined): { date: string; time: string } {
  if (!iso) return { date: "", time: "" };
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return { date: "", time: "" };
  return {
    date: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`,
    time: `${pad(d.getHours())}:${pad(d.getMinutes())}`,
  };
}

/** `date` (YYYY-MM-DD) and `time` (HH:mm) in the viewer's zone, as an ISO instant. */
export function fromInputParts(date: string, time: string): string | null {
  const dm = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date ?? "");
  const tm = /^(\d{2}):(\d{2})$/.exec(time ?? "");
  if (!dm || !tm) return null;
  const [y, mo, da, h, mi] = [dm[1], dm[2], dm[3], tm[1], tm[2]].map(Number);
  const d = new Date(y, mo - 1, da, h, mi, 0, 0);
  // Reject rolled-over values such as 2025-02-31 or 25:00.
  if (d.getFullYear() !== y || d.getMonth() !== mo - 1 || d.getDate() !== da || d.getHours() !== h) {
    return null;
  }
  return d.toISOString();
}

function format(iso: string, locale: string, options: Intl.DateTimeFormatOptions, timeZone?: string) {
  try {
    return new Intl.DateTimeFormat(locale, { ...options, ...(timeZone ? { timeZone } : {}) }).format(
      new Date(iso),
    );
  } catch {
    return new Date(iso).toLocaleString();
  }
}

const DAY: Intl.DateTimeFormatOptions = { weekday: "long", day: "numeric", month: "long", year: "numeric" };
const TIME: Intl.DateTimeFormatOptions = { hour: "numeric", minute: "2-digit" };

/** "Tuesday, 5 November 2026 · 7:00 PM – 9:00 PM" in the viewer's zone (or `timeZone`). */
export function formatRange(
  starts: string,
  ends: string | null,
  locale: string,
  timeZone?: string,
): string {
  const day = format(starts, locale, DAY, timeZone);
  const from = format(starts, locale, TIME, timeZone);
  if (!ends) return `${day} · ${from}`;
  const sameDay = format(starts, locale, DAY, timeZone) === format(ends, locale, DAY, timeZone);
  const to = sameDay ? format(ends, locale, TIME, timeZone) : `${format(ends, locale, DAY, timeZone)} ${format(ends, locale, TIME, timeZone)}`;
  return `${day} · ${from} – ${to}`;
}

/** The short day and month for a date badge on a card. */
export function dateBadge(iso: string, locale: string): { day: string; month: string } {
  return {
    day: format(iso, locale, { day: "numeric" }),
    month: format(iso, locale, { month: "short" }),
  };
}

/** A short name for a zone ("GMT+2", "EET"), or the IANA name when there is none. */
export function zoneLabel(timeZone: string, locale: string, at: string): string {
  try {
    const parts = new Intl.DateTimeFormat(locale, { timeZone, timeZoneName: "short" }).formatToParts(new Date(at));
    return parts.find((p) => p.type === "timeZoneName")?.value ?? timeZone;
  } catch {
    return timeZone;
  }
}

/** Whether the host's zone shows a different wall time from the viewer's at `at`. */
export function zoneDiffers(timeZone: string, at: string): boolean {
  const here = viewerTimeZone();
  if (!timeZone || timeZone === here) return false;
  const wall = (tz: string) => format(at, "en-GB", { ...DAY, ...TIME }, tz);
  return wall(timeZone) !== wall(here);
}

/** Only http(s) links are opened; anything else is shown as text. */
export function safeHttpUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
  } catch {
    return null;
  }
}
