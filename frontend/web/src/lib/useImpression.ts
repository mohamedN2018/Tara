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
  let rule: ImpressionRuleInUse = impressionRule(target()?.surface ?? "home");

  const tabVisible = () => typeof document === "undefined" || document.visibilityState !== "hidden";

  function clearTimer() {
    if (timer) clearTimeout(timer);
    timer = null;
  }

  function pause() {
    if (visibleSince !== null) accumulated += Date.now() - visibleSince;
    visibleSince = null;
    clearTimer();
  }

  function fire() {
    const t = target();
    if (!t || done) return;
    done = true;
    track({ t: "feed_impression", item: t.item, surface: t.surface, pos: t.pos, idef: rule.version });
    observer?.disconnect();
  }

  function resume() {
    if (done || visibleSince !== null || !tabVisible()) return;
    visibleSince = Date.now();
    clearTimer();
    timer = setTimeout(() => {
      pause();
      if (accumulated >= rule.ms) fire();
      else resume();
    }, Math.max(0, rule.ms - accumulated));
  }

  let intersecting = false;
  function onVisibility() {
    if (!tabVisible()) pause();
    else if (intersecting) resume();
  }

  function observe(node: HTMLElement | null) {
    observer?.disconnect();
    observer = null;
    pause();
    if (!node || done || typeof IntersectionObserver === "undefined") return;
    // The rule is read when watching starts: a card counts by one rule only.
    rule = impressionRule(target()?.surface ?? "home");
    observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[entries.length - 1];
        intersecting = !!entry && meetsRule(entry, rule);
        if (intersecting) resume();
        else pause();
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
  // A card reused for another item starts over.
  watch(
    () => target()?.item,
    (item, previous) => {
      if (item === previous) return;
      done = false;
      accumulated = 0;
      observe(el.value);
    },
  );
  onBeforeUnmount(() => {
    observer?.disconnect();
    observer = null;
    clearTimer();
    if (typeof document !== "undefined") document.removeEventListener("visibilitychange", onVisibility);
  });
}
