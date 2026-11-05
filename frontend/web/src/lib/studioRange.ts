// Creator studio helpers: local-day date ranges (the engagement chart and the
// library's date filter) and the content library's CSV export.
import type { StudioDay } from "@/services/studio";

const pad = (n: number) => String(n).padStart(2, "0");

/** A date as YYYY-MM-DD in the viewer's own time zone. */
export function localDay(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** The last `days` local days, today included. */
export function lastDays(days: number, today = new Date()): { from: string; to: string } {
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate() - (days - 1));
  return { from: localDay(start), to: localDay(today) };
}

/** Local midnight of a YYYY-MM-DD as an ISO instant; `next` gives the following midnight. */
export function dayEdge(ymd: string, next = false): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(ymd);
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]) + (next ? 1 : 0));
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

/** Inclusive length in days of from..to (YYYY-MM-DD), or 0 when reversed or invalid. */
export function spanDays(from: string, to: string): number {
  const a = dayEdge(from);
  const b = dayEdge(to);
  if (!a || !b) return 0;
  const n = Math.round((Date.parse(b) - Date.parse(a)) / 86_400_000) + 1;
  return n > 0 ? n : 0;
}

export type ChartMetric = "engagement" | "views" | "reactions" | "comments" | "shares" | "saves";
export const CHART_METRICS: ChartMetric[] = ["engagement", "views", "reactions", "comments", "shares", "saves"];

/** Engagement is every interaction: reactions, comments, shares and saves. */
export function metricOf(day: StudioDay, metric: ChartMetric): number {
  if (metric === "engagement") return day.reactions + day.comments + day.shares + day.saves;
  return day[metric];
}

/**
 * One CSV cell: quoted, inner quotes doubled, and a leading = + - @ (or tab /
 * CR) defused with an apostrophe so a spreadsheet never runs it as a formula.
 */
export function csvCell(value: string | number | null | undefined): string {
  let s = value === null || value === undefined ? "" : String(value);
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return `"${s.replace(/"/g, '""')}"`;
}

export function toCsv(header: string[], rows: (string | number | null | undefined)[][]): string {
  // A BOM so spreadsheet apps read Arabic text as UTF-8.
  return "﻿" + [header, ...rows].map((r) => r.map(csvCell).join(",")).join("\r\n") + "\r\n";
}
