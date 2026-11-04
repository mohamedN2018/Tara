// Campaign schedule helpers (ads manager): the form's local date-times to the
// API's ISO strings, and a one-line summary of a campaign's window.
type Translate = (key: string, named?: Record<string, unknown>) => string;

/** A `datetime-local` value (local time) to ISO, or null when empty or invalid. */
export function toIso(local: string): string | null {
  if (!local) return null;
  const d = new Date(local);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

function format(iso: string, locale: string): string {
  try {
    return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
  } catch {
    return iso.slice(0, 16).replace("T", " ");
  }
}

/** "Runs from … to …", "Starts …", "Ends …", or "" without a schedule. */
export function scheduleLabel(
  c: { schedule_start?: string | null; schedule_end?: string | null },
  locale: string,
  t: Translate,
): string {
  const start = c.schedule_start ? format(c.schedule_start, locale) : "";
  const end = c.schedule_end ? format(c.schedule_end, locale) : "";
  if (start && end) return t("commerce.ads.runs", { start, end });
  if (start) return t("commerce.ads.starts", { start });
  if (end) return t("commerce.ads.ends", { end });
  return "";
}
