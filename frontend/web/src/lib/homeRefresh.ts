// Home refresh on return (Tara Intelligence 06 §6.1, 07 WP 4b.8, 08 §7.6).
//
// When the viewer comes back to Home (KeepAlive `onActivated`, or the tab
// becoming visible) the time away decides what happens:
// - away < `refresh_after_s`: nothing;
// - away ≥ `refresh_after_s`: a `peek` (new rows since the visit's `since`) feeds
//   the "new posts" pill; the list and the scroll position stay as they were;
// - away ≥ `auto_refetch_after_s` while the list is at the top: a silent first
//   page with `entry=return` replaces the list.
//
// Both thresholds are the server's (`meta.refresh_after_s`,
// `meta.auto_refetch_after_s`, from the Home config's `session` block). The web
// holds one copy, `REFRESH_DEFAULTS`, used only before the first answer; a unit
// test compares it with the backend's package defaults so the two cannot drift.
//
// `pageEntry()` names the first page's `entry` hint (06 §4.2): `reload` for a
// browser reload, `load` for the first page of a full page load, `nav` after.
import { isReload } from "./feedPosition";

export const REFRESH_DEFAULTS = { refresh_after_s: 600, auto_refetch_after_s: 1800 } as const;

export interface RefreshTimers {
  refreshAfterMs: number;
  autoRefetchAfterMs: number;
}

const ok = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v) && v >= 0;

/** The server's timers (seconds) when it sent them, else the defaults. */
export function timersFrom(refreshAfterS?: number, autoRefetchAfterS?: number): RefreshTimers {
  return {
    refreshAfterMs: (ok(refreshAfterS) ? refreshAfterS : REFRESH_DEFAULTS.refresh_after_s) * 1000,
    autoRefetchAfterMs: (ok(autoRefetchAfterS) ? autoRefetchAfterS : REFRESH_DEFAULTS.auto_refetch_after_s) * 1000,
  };
}

export type ReturnAction = "none" | "peek" | "refetch";

/** What coming back after `awayMs` does (06 §6.1). */
export function decideReturn(awayMs: number, atTop: boolean, timers: RefreshTimers): ReturnAction {
  if (!(awayMs >= timers.refreshAfterMs)) return "none";
  if (atTop && awayMs >= timers.autoRefetchAfterMs) return "refetch";
  return "peek";
}

let firstPageAsked = false;

/** The `entry` of a first page: `reload` / `load` once per page load, then `nav`. */
export function pageEntry(): "reload" | "load" | "nav" {
  if (firstPageAsked) return "nav";
  firstPageAsked = true;
  return isReload() ? "reload" : "load";
}

/** Tests: a new page load. */
export function resetPageEntry() {
  firstPageAsked = false;
}

/** The list is scrolled to (near) its top: within half the sticky header. */
export function atScrollTop(slackPx = 32): boolean {
  return typeof window === "undefined" || (window.scrollY || 0) <= slackPx;
}

export interface HomeRefreshOptions {
  timers: () => RefreshTimers;
  atTop?: () => boolean;
  /** Away long enough, scrolled (or not long enough for a refetch): ask for the pill. */
  onPeek: () => void;
  /** Away long enough at the top: replace the list (`entry=return`). */
  onRefetch: () => void;
  now?: () => number;
}

/**
 * The return logic as a small state machine. `leave()` when Home stops being on
 * screen (deactivated, tab hidden), `back()` when it is again; `listen()` wires
 * `visibilitychange` (the view decides whether it is the active one).
 */
export function createHomeRefresh(opts: HomeRefreshOptions) {
  const now = opts.now ?? (() => Date.now());
  const atTop = opts.atTop ?? (() => atScrollTop());
  let awayAt: number | null = null;
  let active = true;

  function leave() {
    if (awayAt === null) awayAt = now();
  }

  function back(): ReturnAction {
    if (awayAt === null) return "none";
    const away = now() - awayAt;
    awayAt = null;
    const action = decideReturn(away, atTop(), opts.timers());
    if (action === "peek") opts.onPeek();
    else if (action === "refetch") opts.onRefetch();
    return action;
  }

  function onVisibility() {
    if (!active || typeof document === "undefined") return;
    if (document.visibilityState === "hidden") leave();
    else back();
  }

  function listen(): () => void {
    if (typeof document === "undefined") return () => undefined;
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }

  return {
    leave,
    back,
    listen,
    /** KeepAlive: Home left the screen (another route). */
    deactivate() {
      active = false;
      leave();
    },
    /** KeepAlive: Home is shown again. */
    activate(): ReturnAction {
      active = true;
      return back();
    },
    awaySince: () => awayAt,
  };
}

/** Milliseconds to wait from a `Retry-After` header (seconds or an HTTP date); null when absent. */
export function retryAfterMs(header: unknown, nowMs = Date.now()): number | null {
  if (typeof header !== "string" || !header.trim()) return null;
  const secs = Number(header.trim());
  if (Number.isFinite(secs) && secs >= 0) return Math.round(secs * 1000);
  const at = Date.parse(header);
  return Number.isFinite(at) ? Math.max(0, at - nowMs) : null;
}
