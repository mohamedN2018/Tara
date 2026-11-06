// Feed delivery settings (Tara Intelligence 08 §7.2, WP 4c.2-B3 on the web).
//
// The server owns every delivery value: page sizes, prefetch distance, media
// warm-up, virtualization, retries, rail deferral, the video policy and the
// impression rule. They arrive in two ways:
// - `meta.delivery` of a Home `/feed/` page (the `home` block);
// - `GET /feed/delivery/` (`{data: {home, reels, video}}`), fetched once per
//   session in the background (never before the first `/feed/` call) and kept
//   in sessionStorage for the rest of the tab's life.
//
// The web holds no delivery constants of its own, with one exception:
// `SAFE_DEFAULTS`, used only while the server's values are unreachable. A unit
// test compares it with the backend's package defaults
// (`services/feed/intel/config/defaults/{home,reels,video}.json`), so the two
// cannot drift. Without server values impressions keep the legacy v1 rule and
// say so (`idef` 1): they never pretend to follow v2.
import { reactive } from "vue";

import { api } from "./api";

export const DELIVERY_SURFACES = ["home", "reels", "video"] as const;
export type DeliverySurface = (typeof DELIVERY_SURFACES)[number];

export interface VideoPolicy {
  autoplay: "muted_single" | "click";
  min_visible: number;
  min_visible_ms: number;
  pause_below: number;
  load_margin_vp: number;
  unmount_beyond_vp: number;
  respect_save_data: boolean;
  respect_reduced_motion: boolean;
}

export interface ImpressionRule {
  min_card_visible: number;
  min_viewport_cover: number;
  min_ms: number;
  def_version: number;
}

export interface DeliveryBlock {
  first_page_size: number;
  page_size: number;
  prefetch_remaining_items: number;
  prefetch_root_margin_vp: number;
  media_warm_items: number;
  media_resolve_window_ms: number;
  virtualize_after_items: number;
  keep_mounted_vp: number;
  next_page_retries: number;
  next_page_backoff_ms: number;
  defer_rails_until_first_post: boolean;
  defer_rails_max_ms: number;
  /** Reload position (08 §7.6): the window in minutes and the most pages paged forward. */
  reload_window_min: number;
  reload_max_pages: number;
  video: VideoPolicy;
  impression: ImpressionRule;
}

const BASE_VIDEO: VideoPolicy = {
  autoplay: "muted_single",
  min_visible: 0.6,
  min_visible_ms: 300,
  pause_below: 0.25,
  load_margin_vp: 1.0,
  unmount_beyond_vp: 3,
  respect_save_data: true,
  respect_reduced_motion: true,
};
const BASE_IMPRESSION: ImpressionRule = { min_card_visible: 0.5, min_viewport_cover: 0.5, min_ms: 1000, def_version: 2 };
const base = (first: number, page: number): DeliveryBlock => ({
  first_page_size: first,
  page_size: page,
  prefetch_remaining_items: 5,
  prefetch_root_margin_vp: 2.5,
  media_warm_items: 6,
  media_resolve_window_ms: 20,
  virtualize_after_items: 40,
  keep_mounted_vp: 3,
  next_page_retries: 3,
  next_page_backoff_ms: 1000,
  defer_rails_until_first_post: true,
  defer_rails_max_ms: 1500,
  reload_window_min: 30,
  reload_max_pages: 3,
  video: { ...BASE_VIDEO },
  impression: { ...BASE_IMPRESSION },
});

/**
 * Fallback only, for when the server's values cannot be reached. Must equal
 * the backend package defaults (deliveryStore.spec.ts asserts deep equality).
 */
export const SAFE_DEFAULTS: Readonly<Record<DeliverySurface, DeliveryBlock>> = {
  home: base(10, 20),
  reels: base(5, 10),
  video: base(20, 20),
};

const NUMBER_KEYS = [
  "first_page_size",
  "page_size",
  "prefetch_remaining_items",
  "prefetch_root_margin_vp",
  "media_warm_items",
  "media_resolve_window_ms",
  "virtualize_after_items",
  "keep_mounted_vp",
  "next_page_retries",
  "next_page_backoff_ms",
  "defer_rails_max_ms",
] as const;
const VIDEO_NUMBERS = ["min_visible", "min_visible_ms", "pause_below", "load_margin_vp", "unmount_beyond_vp"] as const;
const IMPRESSION_NUMBERS = ["min_card_visible", "min_viewport_cover", "min_ms", "def_version"] as const;

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v) && v >= 0;
const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);

/** A server block, checked key by key; null when it is not a usable delivery block. */
export function parseBlock(raw: unknown): (DeliveryBlock & Record<string, unknown>) | null {
  if (!isObj(raw)) return null;
  if (!NUMBER_KEYS.every((k) => isNum(raw[k]))) return null;
  if (typeof raw.defer_rails_until_first_post !== "boolean") return null;
  const v = raw.video;
  if (!isObj(v) || !VIDEO_NUMBERS.every((k) => isNum(v[k]))) return null;
  if (v.autoplay !== "muted_single" && v.autoplay !== "click") return null;
  if (typeof v.respect_save_data !== "boolean" || typeof v.respect_reduced_motion !== "boolean") return null;
  const imp = raw.impression;
  if (!isObj(imp) || !IMPRESSION_NUMBERS.every((k) => isNum(imp[k]))) return null;
  if (!Number.isInteger(imp.def_version) || (imp.def_version as number) < 1) return null;
  return raw as DeliveryBlock & Record<string, unknown>;
}

type Source = "server" | "safe";
const state = reactive({
  blocks: {} as Partial<Record<DeliverySurface, DeliveryBlock & Record<string, unknown>>>,
});
let fetching: Promise<void> | null = null;
let fetched = false;
const STORAGE_KEY = "tara.delivery.v1";

function fromSession() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    for (const s of DELIVERY_SURFACES) {
      const block = parseBlock(parsed[s]);
      if (block && !state.blocks[s]) state.blocks[s] = block;
    }
  } catch {
    // Storage blocked or junk: the server's answer (or the fallback) is used.
  }
}

function toSession() {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state.blocks));
  } catch {
    // Storage blocked: kept in memory for this page only.
  }
}

/** Store a block the server sent (Home's `meta.delivery`, or `/feed/delivery/`). */
export function applyDelivery(surface: DeliverySurface, raw: unknown): boolean {
  const block = parseBlock(raw);
  if (!block) return false;
  state.blocks[surface] = block;
  toSession();
  return true;
}

/** The block for a surface: the server's when known, else the fallback. */
export function delivery(surface: DeliverySurface): DeliveryBlock & Record<string, unknown> {
  if (!state.blocks[surface]) fromSession();
  return state.blocks[surface] ?? (SAFE_DEFAULTS[surface] as DeliveryBlock & Record<string, unknown>);
}

/** Whether the surface's values came from the server (else they are the fallback). */
export function deliverySource(surface: DeliverySurface): Source {
  if (!state.blocks[surface]) fromSession();
  return state.blocks[surface] ? "server" : "safe";
}

/**
 * Reload position (08 §7.6): a full reload within `reload_window_min` returns to
 * the card that was on screen, paging forward at most `reload_max_pages`. A server
 * block without the keys (an older server) uses the fallback's.
 */
export function positionRules(surface: DeliverySurface = "home"): { windowMs: number; maxPages: number } {
  const block = delivery(surface);
  const safe = SAFE_DEFAULTS[surface];
  const windowMin = isNum(block.reload_window_min) ? block.reload_window_min : safe.reload_window_min;
  const maxPages = isNum(block.reload_max_pages) ? Math.floor(block.reload_max_pages) : safe.reload_max_pages;
  return { windowMs: windowMin * 60_000, maxPages };
}

/**
 * `GET /feed/delivery/` once per tab session, in the background. Never awaited
 * before the first feed call; a failure leaves the fallback in place.
 */
export function loadDelivery(): Promise<void> {
  if (fetched) return Promise.resolve();
  if (!fetching) {
    fetching = api
      .get<{ data: Record<string, unknown> }>("/feed/delivery/")
      .then(({ data }) => {
        for (const s of DELIVERY_SURFACES) applyDelivery(s, data?.data?.[s]);
        fetched = true;
      })
      .catch(() => undefined)
      .finally(() => {
        fetching = null;
      });
  }
  return fetching;
}

/** Forget the server's values (sign-out, tests). */
export function resetDelivery() {
  for (const s of DELIVERY_SURFACES) delete state.blocks[s];
  fetched = false;
  fetching = null;
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing stored.
  }
  releaseRails();
}

// Rail deferral (08 §7.4 step 2). Home holds the rails (stories, events, pages,
// suggestions, birthdays, trending, groups) until its first feed card is on
// screen or `defer_rails_max_ms` passed, whichever comes first. Anywhere else
// the gate is open and rails start at once.
const rails = reactive({ held: false });
let railTimer: ReturnType<typeof setTimeout> | null = null;
let railWaiters: Array<() => void> = [];

/** Hold the rails (Home, before its first page). Released after `maxMs` at the latest. */
export function holdRails(maxMs: number) {
  if (railTimer) clearTimeout(railTimer);
  rails.held = true;
  railTimer = setTimeout(releaseRails, Math.max(0, maxMs));
}

/** Let the rails start (Home's first card rendered, an error, or leaving Home). */
export function releaseRails() {
  if (railTimer) clearTimeout(railTimer);
  railTimer = null;
  rails.held = false;
  const waiting = railWaiters;
  railWaiters = [];
  waiting.forEach((w) => w());
}

/** Resolves when rails may make their calls (at once when nothing holds them). */
export function railsReady(): Promise<void> {
  if (!rails.held) return Promise.resolve();
  return new Promise((resolve) => railWaiters.push(resolve));
}

/** Whether rails are being held right now. */
export function railsHeld(): boolean {
  return rails.held;
}
