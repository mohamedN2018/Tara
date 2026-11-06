// Impressions (Tara Intelligence WP 2.8; rule v2: 08 §7.12, WP 4c.9-B3).
//
// A card counts as seen once, in a visible tab, it has been on screen long
// enough: at least `min_card_visible` of the card, OR at least
// `min_viewport_cover` of the viewport covered by the card (so a card taller
// than two screens can count), for `min_ms` in total. The time accumulates
// across short scrolls; the tracker keeps one impression per (session, item).
// The rule's thresholds and version are the server's (`delivery.impression`):
// each impression carries `idef`, the version it followed. While the server's
// values are unknown the legacy v1 rule applies (half the card for 1 s) and the
// event says `idef: 1`; it never claims v2.
//
// An impression is visibility only: nothing here runs on fetch, render or
// prefetch. An impression is not interest: the server gives it no interest
// weight (02 §13).
//
// Dwell (R3 WP 4b.2): the same rule's visible time keeps adding up after the
// impression. Once the card has been displayed, one `feed_dwell {item, st,
// dwell_ms}` goes out per (session, item) when it leaves the viewport, the tab
// hides, or the card unmounts (virtualization, navigation). The server turns it
// into the skipped / viewed / consumed exposure states and drops what the wall
// clock cannot allow. With personalization off `track` sends nothing.
import { onBeforeUnmount, onMounted, type Ref, watch } from "vue";

import { delivery, type DeliverySurface, deliverySource } from "./delivery";
import { type SignalSurface, track } from "./signals";

/** The legacy rule (v1, WP 2.8): kept for when the server's rule is unknown. */
export const IMPRESSION_RULES = { visibleRatio: 0.5, visibleMs: 1_000 } as const;

export interface ImpressionRuleInUse {
  cardRatio: number;
  /** 0 disables the viewport-cover branch (v1). */
  viewportCover: number;
  ms: number;
  version: number;
}

const DELIVERY_OF: Partial<Record<SignalSurface, DeliverySurface>> = { home: "home", reels: "reels", video: "video" };

/** The rule a surface's impressions follow right now. */
export function impressionRule(surface: SignalSurface): ImpressionRuleInUse {
  const block = DELIVERY_OF[surface] ?? "home";
  if (deliverySource(block) !== "server") {
    return { cardRatio: IMPRESSION_RULES.visibleRatio, viewportCover: 0, ms: IMPRESSION_RULES.visibleMs, version: 1 };
  }
  const r = delivery(block).impression;
  return { cardRatio: r.min_card_visible, viewportCover: r.min_viewport_cover, ms: r.min_ms, version: r.def_version };
}

/** Whether one observer entry meets the rule (exported for tests). */
export function meetsRule(
  entry: Pick<IntersectionObserverEntry, "isIntersecting" | "intersectionRatio" | "intersectionRect" | "rootBounds">,
  rule: ImpressionRuleInUse,
): boolean {
  if (!entry.isIntersecting) return false;
  if (entry.intersectionRatio >= rule.cardRatio) return true;
  if (rule.viewportCover <= 0) return false;
  const rootHeight = entry.rootBounds?.height || (typeof window !== "undefined" ? window.innerHeight : 0);
  return rootHeight > 0 && entry.intersectionRect.height / rootHeight >= rule.viewportCover;
}

// Many thresholds, so a tall card reports while it scrolls (its ratio moves slowly).
const THRESHOLDS = Array.from({ length: 21 }, (_, i) => i / 20);

export interface ImpressionTarget {
  item: string;
  surface: SignalSurface;
  pos?: number;
}

/**
 * Watch one element; `target()` names the item (or `null` for nothing to
 * track, e.g. a sponsored or a pending card). Works without IntersectionObserver
 * (old browsers, jsdom): then nothing is sent, never a guess.
 */
export function useImpression(el: Ref<HTMLElement | null>, target: () => ImpressionTarget | null) {
  let observer: IntersectionObserver | null = null;
  let visibleSince: number | null = null;
  let accumulated = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let done = false;
  // Dwell (R3 WP 4b.2): the time the rule is met, before and after the impression.
  let dwellMs = 0;
  let dwellSince: number | null = null;
  let dwellSent = false;
  // The item the impression went out for (the card may be reused for another).
  let shown: ImpressionTarget | null = null;
  let rule: ImpressionRuleInUse = impressionRule(target()?.surface ?? "home");

  const tabVisible = () => typeof document === "undefined" || document.visibilityState !== "hidden";

  function clearTimer() {
    if (timer) clearTimeout(timer);
    timer = null;
  }

  function pauseDwell() {
    if (dwellSince !== null) dwellMs += Date.now() - dwellSince;
    dwellSince = null;
  }

  function pause() {
    if (visibleSince !== null) accumulated += Date.now() - visibleSince;
    visibleSince = null;
    clearTimer();
    pauseDwell();
  }

  /** The card left the viewport, the tab hid or the card unmounts: its one dwell. */
  function sendDwell() {
    pauseDwell();
    if (!shown || dwellSent) return;
    dwellSent = true;
    track({ t: "feed_dwell", item: shown.item, surface: shown.surface, dwell_ms: Math.round(dwellMs) });
    observer?.disconnect();
    observer = null;
  }

  function fire() {
    const t = target();
    if (!t || done) return;
    done = true;
    shown = t;
    track({ t: "feed_impression", item: t.item, surface: t.surface, pos: t.pos, idef: rule.version });
    // Still watched: the dwell goes on until the card leaves.
  }

  function resume() {
    if (dwellSent || !tabVisible()) return;
    if (dwellSince === null) dwellSince = Date.now();
    if (done || visibleSince !== null) return;
    visibleSince = Date.now();
    clearTimer();
    timer = setTimeout(() => {
      pause();
      if (accumulated >= rule.ms) fire();
      // Measuring goes on (the dwell, or the rest of the impression time).
      resume();
    }, Math.max(0, rule.ms - accumulated));
  }

  let intersecting = false;
  function onVisibility() {
    if (!tabVisible()) {
      pause();
      if (done) sendDwell();
    } else if (intersecting) resume();
  }

  function observe(node: HTMLElement | null) {
    observer?.disconnect();
    observer = null;
    pause();
    if (!node || dwellSent || typeof IntersectionObserver === "undefined") return;
    // The rule is read when watching starts: a card counts by one rule only.
    rule = impressionRule(target()?.surface ?? "home");
    observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[entries.length - 1];
        const was = intersecting;
        intersecting = !!entry && meetsRule(entry, rule);
        if (intersecting) resume();
        else {
          pause();
          if (was && done) sendDwell();
        }
      },
      { threshold: THRESHOLDS },
    );
    observer.observe(node);
  }

  onMounted(() => {
    observe(el.value);
    if (typeof document !== "undefined") document.addEventListener("visibilitychange", onVisibility);
  });
  watch(el, (node) => observe(node));
  // A card reused for another item starts over (the previous item's dwell goes first).
  watch(
    () => target()?.item,
    (item, previous) => {
      if (item === previous) return;
      sendDwell();
      done = false;
      shown = null;
      accumulated = 0;
      dwellMs = 0;
      dwellSince = null;
      dwellSent = false;
      intersecting = false;
      observe(el.value);
    },
  );
  onBeforeUnmount(() => {
    sendDwell();
    observer?.disconnect();
    observer = null;
    clearTimer();
    if (typeof document !== "undefined") document.removeEventListener("visibilitychange", onVisibility);
  });
}
