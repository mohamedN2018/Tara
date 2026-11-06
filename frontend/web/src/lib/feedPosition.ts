// Feed position across a full reload (Tara Intelligence 08 §7.6, WP 4c.8-B3).
//
// On `pagehide` Home stores which card was at the top of the screen and how far
// it was scrolled past, in sessionStorage (this tab only). A reload within the
// window (`positionRules().windowMs`) asks for the first page with
// `entry=reload`, pages forward until that card is in the list (at most
// `positionRules().maxPages` pages) and scrolls back to it. Otherwise the feed
// starts at the top. Only the chronological modes are restored: a ranked page 1
// is rebuilt on every open (R3), so its old card may not be there.
//
// What is stored is ids and pixel offsets of this viewer's own tab, never
// anything about the posts; storage that is blocked or full simply means no
// restore.
import { positionRules } from "./delivery";

export const CHRONOLOGICAL_MODES = ["recent", "following", "friends", "favorites"] as const;
export type ChronologicalMode = (typeof CHRONOLOGICAL_MODES)[number];
export const isChronological = (m: unknown): m is ChronologicalMode =>
  typeof m === "string" && (CHRONOLOGICAL_MODES as readonly string[]).includes(m);

export interface FeedPosition {
  surface: "home";
  mode: ChronologicalMode;
  anchor_post_id: string;
  offset_px: number;
  cursor: string | null;
  at: number;
}

const KEY = "tara.feedPosition.v1";
const UUID = /^[0-9a-f-]{36}$/i;

export function savePosition(pos: Omit<FeedPosition, "at">, now = Date.now()): boolean {
  if (!isChronological(pos.mode) || !UUID.test(pos.anchor_post_id)) return false;
  try {
    sessionStorage.setItem(KEY, JSON.stringify({ ...pos, offset_px: Math.round(pos.offset_px), at: now }));
    return true;
  } catch {
    return false;
  }
}

/** The stored position for this mode when it is recent enough; null otherwise. */
export function readPosition(mode: string, now = Date.now()): FeedPosition | null {
  if (!isChronological(mode)) return null;
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    const p = JSON.parse(raw) as Partial<FeedPosition>;
    if (p.surface !== "home" || p.mode !== mode || typeof p.anchor_post_id !== "string" || !UUID.test(p.anchor_post_id)) return null;
    if (typeof p.at !== "number" || now - p.at > positionRules("home").windowMs || now < p.at) return null;
    return {
      surface: "home",
      mode,
      anchor_post_id: p.anchor_post_id,
      offset_px: typeof p.offset_px === "number" && Number.isFinite(p.offset_px) ? p.offset_px : 0,
      cursor: typeof p.cursor === "string" ? p.cursor : null,
      at: p.at,
    };
  } catch {
    return null;
  }
}

export function clearPosition() {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    // Nothing stored.
  }
}

/** Whether this page load is a reload (Navigation Timing); false when unknown. */
export function isReload(): boolean {
  try {
    const nav = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined;
    return nav?.type === "reload";
  } catch {
    return false;
  }
}

/**
 * The card at the top of the viewport under the sticky header, and how far the
 * page is scrolled past its top edge.
 */
export function topCard(header = 64): { id: string; offset: number } | null {
  const items = document.querySelectorAll<HTMLElement>("[data-feed-item]");
  for (const node of items) {
    const rect = node.getBoundingClientRect();
    if (rect.bottom > header + 1 && rect.height > 0) {
      const id = node.dataset.feedItem;
      return id ? { id, offset: header - rect.top } : null;
    }
  }
  return null;
}

/** Scroll so that the card is where it was (its top `offset` px above the header line). */
export function scrollToCard(id: string, offset: number, header = 64): boolean {
  const node = [...document.querySelectorAll<HTMLElement>("[data-feed-item]")].find((n) => n.dataset.feedItem === id);
  if (!node) return false;
  const top = node.getBoundingClientRect().top + window.scrollY - header + offset;
  window.scrollTo({ top: Math.max(0, top), behavior: "instant" as ScrollBehavior });
  return true;
}
