// Impressions (Tara Intelligence WP 2.8): a card counts as seen once at least
// half of it has been on screen for a full second, in a visible tab. The time
// accumulates across short scrolls; the tracker keeps one impression per
// (session, item). An impression is not interest: the server gives it no
// interest weight (02 §13).
import { onBeforeUnmount, onMounted, type Ref, watch } from "vue";

import { type SignalSurface, track } from "./signals";

export const IMPRESSION_RULES = { visibleRatio: 0.5, visibleMs: 1_000 } as const;

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
    track({ t: "feed_impression", item: t.item, surface: t.surface, pos: t.pos });
    observer?.disconnect();
  }

  function resume() {
    if (done || visibleSince !== null || !tabVisible()) return;
    visibleSince = Date.now();
    clearTimer();
    timer = setTimeout(() => {
      pause();
      if (accumulated >= IMPRESSION_RULES.visibleMs) fire();
      else resume();
    }, Math.max(0, IMPRESSION_RULES.visibleMs - accumulated));
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
    observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[entries.length - 1];
        intersecting = !!entry && entry.isIntersecting && entry.intersectionRatio >= IMPRESSION_RULES.visibleRatio;
        if (intersecting) resume();
        else pause();
      },
      { threshold: [0, IMPRESSION_RULES.visibleRatio, 1] },
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
