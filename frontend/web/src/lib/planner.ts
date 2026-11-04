// The planner's calendar maths (track T8). Every day is a day in the viewer's
// own time zone: grids are built from local midnights, the API gets the grid's
// edges as UTC instants, and a post moved to another day keeps its local time.
import { MAX_SCHEDULE_DAYS } from "@/services/composer";

export type PlannerView = "month" | "week";

/** The calendar's first weekday (0 = Sunday), as in the reference layout. */
export const WEEK_START = 0;

const DAY_MS = 86_400_000;
const pad = (n: number) => String(n).padStart(2, "0");

export function startOfDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

export function addDays(d: Date, n: number): Date {
  // Calendar arithmetic, not 24 h steps: correct across daylight-saving changes.
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n, d.getHours(), d.getMinutes(), d.getSeconds());
}

export function addMonths(d: Date, n: number): Date {
  return new Date(d.getFullYear(), d.getMonth() + n, 1);
}

/** `YYYY-MM-DD` of a date in the viewer's zone. */
export function dayKey(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function startOfWeek(d: Date, weekStart = WEEK_START): Date {
  const day = startOfDay(d);
  return addDays(day, -((day.getDay() - weekStart + 7) % 7));
}

/** The days of the month grid: whole weeks from the one holding the 1st to the one holding the last day. */
export function monthGrid(anchor: Date, weekStart = WEEK_START): Date[] {
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
  const last = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0);
  const start = startOfWeek(first, weekStart);
  const end = addDays(startOfWeek(last, weekStart), 7);
  const days: Date[] = [];
  for (let d = start; d < end; d = addDays(d, 1)) days.push(d);
  return days;
}

export function weekGrid(anchor: Date, weekStart = WEEK_START): Date[] {
  const start = startOfWeek(anchor, weekStart);
  return Array.from({ length: 7 }, (_, i) => addDays(start, i));
}

/** The API range of a grid: the first day's local midnight to the midnight after the last day. */
export function gridRange(days: Date[]): { from: string; to: string } {
  return {
    from: startOfDay(days[0]).toISOString(),
    to: addDays(startOfDay(days[days.length - 1]), 1).toISOString(),
  };
}

export interface Dated {
  state?: string;
  publish_at?: string | null;
  created_at: string;
}

/** When a post shows on the calendar: its schedule, or its publication time. */
export function postTime(post: Dated): string {
  return post.state === "scheduled" && post.publish_at ? post.publish_at : post.created_at;
}

/** Posts by local day, each day in time order. */
export function groupByDay<T extends Dated>(posts: T[]): Map<string, T[]> {
  const out = new Map<string, T[]>();
  const sorted = [...posts].sort((a, b) => postTime(a).localeCompare(postTime(b)));
  for (const post of sorted) {
    const key = dayKey(new Date(postTime(post)));
    const list = out.get(key);
    if (list) list.push(post);
    else out.set(key, [post]);
  }
  return out;
}

/** The same local hour and minute on another day (a drag to that day). */
export function moveToDay(iso: string, day: Date): Date {
  const at = new Date(iso);
  return new Date(day.getFullYear(), day.getMonth(), day.getDate(), at.getHours(), at.getMinutes());
}

/** Why a scheduled post cannot go to this time, as the server would judge it. */
export function rescheduleProblem(target: Date, now = new Date()): "past" | "far" | null {
  if (target.getTime() <= now.getTime()) return "past";
  if (target.getTime() > now.getTime() + MAX_SCHEDULE_DAYS * DAY_MS) return "far";
  return null;
}

/** Whether a day can still take a new scheduled post (today or later, within 75 days). */
export function canScheduleOn(day: Date, now = new Date()): boolean {
  const end = addDays(startOfDay(day), 1);
  return end.getTime() > now.getTime() + 60_000 && startOfDay(day).getTime() <= now.getTime() + MAX_SCHEDULE_DAYS * DAY_MS;
}

/**
 * A default time for a new post scheduled on `day`: the next whole hour when
 * the day is today (two hours ahead in the last two minutes), else 09:00 local.
 */
export function defaultSlot(day: Date, now = new Date()): Date {
  if (dayKey(day) === dayKey(now)) {
    const next = new Date(now.getFullYear(), now.getMonth(), now.getDate(), now.getHours() + 1);
    // Keep a margin for the server's "in the future" check.
    if (next.getTime() - now.getTime() < 120_000) next.setHours(next.getHours() + 1);
    return next;
  }
  return new Date(day.getFullYear(), day.getMonth(), day.getDate(), 9, 0);
}

/** The viewer's zone as "Eastern European Standard Time (Africa/Cairo)". */
export function zoneLabel(locale: string, timeZone: string, at = new Date()): string {
  try {
    const part = new Intl.DateTimeFormat(locale, { timeZone, timeZoneName: "long" })
      .formatToParts(at)
      .find((p) => p.type === "timeZoneName")?.value;
    return part && part !== timeZone ? `${part} (${timeZone})` : timeZone;
  } catch {
    return timeZone;
  }
}
