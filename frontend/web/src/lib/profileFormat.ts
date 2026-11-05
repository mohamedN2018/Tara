// Display helpers for profile work / education rows (About tab, Intro card).
import type { ProfileEducation, ProfileWork } from "@/types";

type T = (key: string, values?: Record<string, unknown>) => string;

function monthYear(iso: string | null | undefined, locale: string): string {
  if (!iso) return "";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(d.getTime())) return "";
  try {
    return d.toLocaleDateString(locale, { year: "numeric", month: "short" });
  } catch {
    return iso.slice(0, 7);
  }
}

/** "Jan 2020 to present", "Since Mar 2021", or "" when no dates were given. */
export function workRange(w: ProfileWork, t: T, locale: string): string {
  const from = monthYear(w.start_date, locale);
  const to = w.is_current ? t("people.about.present") : monthYear(w.end_date, locale);
  if (from && to) return t("people.about.fromTo", { from, to });
  if (from) return t("people.about.since", { from });
  if (to && !w.is_current) return to;
  return w.is_current ? t("people.about.present") : "";
}

/** "2016 to 2020", "Since 2019" or "". */
export function educationRange(e: ProfileEducation, t: T): string {
  if (e.start_year && e.end_year) return t("people.about.fromTo", { from: e.start_year, to: e.end_year });
  if (e.start_year) return t("people.about.since", { from: e.start_year });
  return e.end_year ? String(e.end_year) : "";
}

/** "Software engineer at Tara", "Works at Tara" or the title alone. */
export function workHeadline(w: ProfileWork, t: T): string {
  if (w.title && w.company) return t("people.intro.worksAt", { title: w.title, company: w.company });
  if (w.company) return t("people.intro.worksAtCompany", { company: w.company });
  return w.title;
}

/** "Studied Law at Cairo University" or "Studied at Cairo University". */
export function educationHeadline(e: ProfileEducation, t: T): string {
  return e.field ? t("people.intro.studied", { field: e.field, school: e.school }) : t("people.intro.studiedAt", { school: e.school });
}

/** "BSc · Law", "BSc" or "Law". */
export function degreeField(e: ProfileEducation, t: T): string {
  if (e.degree && e.field) return t("people.about.degreeField", { degree: e.degree, field: e.field });
  return e.degree || e.field || "";
}

export function linkHost(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** Two profile texts say the same thing (case, spacing and Unicode form aside). */
export function sameText(a?: string | null, b?: string | null): boolean {
  const norm = (s?: string | null) => (s ?? "").normalize("NFC").replace(/\s+/g, " ").trim().toLocaleLowerCase();
  return !!norm(a) && norm(a) === norm(b);
}
