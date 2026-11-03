// The full-screen photo viewer is driven by the URL: `?view=<postId>:<index>`
// (index from 0). Opening pushes one history entry, so Back closes it, and a
// shared or reloaded link reopens the same photo. Moving between photos
// replaces that entry instead of adding more.
//
// Navigation follows the reading direction. In LTR "next" is to the right
// (ArrowRight, swipe left); in RTL it is to the left (ArrowLeft, swipe right).

export type Direction = "ltr" | "rtl";

export const VIEW_PARAM = "view";
export const SWIPE_THRESHOLD_PX = 45;

export interface ViewTarget {
  postId: string;
  index: number;
}

const ID_RE = /^[0-9a-zA-Z-]{1,64}$/;

/** Read `?view=`. Anything malformed is "closed"; a bad index opens photo 0. */
export function parseView(raw: unknown): ViewTarget | null {
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (typeof value !== "string" || !value) return null;
  const sep = value.lastIndexOf(":");
  const postId = sep === -1 ? value : value.slice(0, sep);
  if (!ID_RE.test(postId)) return null;
  const rawIndex = sep === -1 ? "0" : value.slice(sep + 1);
  const index = /^\d{1,4}$/.test(rawIndex) ? Number(rawIndex) : 0;
  return { postId, index };
}

export function formatView(postId: string, index: number): string {
  return `${postId}:${Math.max(0, Math.floor(index))}`;
}

/** Keep an index inside a post's photos (a stale link may point past the end). */
export function clampIndex(index: number, count: number): number {
  if (count <= 0) return 0;
  return Math.min(Math.max(0, Math.floor(index)), count - 1);
}

/** Move by `delta`, wrapping at both ends. */
export function stepIndex(index: number, delta: number, count: number): number {
  if (count <= 0) return 0;
  return (((index + delta) % count) + count) % count;
}

/** +1 (next), -1 (previous) or 0 for a key, mirrored for RTL. */
export function keyToDelta(key: string, dir: Direction): number {
  const sign = dir === "rtl" ? -1 : 1;
  if (key === "ArrowRight") return sign;
  if (key === "ArrowLeft") return -sign;
  return 0;
}

/**
 * +1, -1 or 0 for a horizontal swipe of `dx` pixels (end minus start).
 * Content follows the finger: dragging it towards the reading start shows
 * the next photo, so swipe left is "next" in LTR and swipe right in RTL.
 */
export function swipeToDelta(dx: number, dir: Direction, dy = 0): number {
  if (Math.abs(dx) < SWIPE_THRESHOLD_PX || Math.abs(dx) <= Math.abs(dy)) return 0;
  const towardsLeft = dx < 0;
  if (dir === "rtl") return towardsLeft ? -1 : 1;
  return towardsLeft ? 1 : -1;
}

export function pageDirection(): Direction {
  if (typeof document === "undefined") return "ltr";
  return document.documentElement.dir === "rtl" ? "rtl" : "ltr";
}
