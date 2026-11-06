// Pull-to-refresh for Home (Tara Intelligence 06 §6.1, 07 WP 4b.8).
//
// Touch only, and only when the page is scrolled to the top: pulling down past
// `threshold` px (after `resistance`) and letting go asks for a first page with
// `entry=pull`. The new items go in above the list without duplicating the ones
// already shown, and `keepAnchor` holds the card that was under the finger in
// place (± a few px) while they go in. The page's own overscroll refresh is turned
// off while Home listens, so one pull never reloads the whole page.
//
// The distances are gesture ergonomics, not feed rules: they decide how far a
// finger travels, never what is fetched or shown.
export const PULL = { threshold: 64, maxPull: 96, resistance: 0.5 } as const;

export interface PullHandlers {
  atTop: () => boolean;
  /** Pulled far enough and released. */
  onPull: () => void | Promise<void>;
  /** The indicator: distance pulled (px, after resistance) and whether a release refreshes. */
  onProgress?: (px: number, armed: boolean) => void;
  /** No pull while a refresh is running. */
  busy?: () => boolean;
}

/** Listen for the gesture on `target` (default: the document). Returns the detach function. */
export function attachPullToRefresh(handlers: PullHandlers, target: Document | HTMLElement = document): () => void {
  let startY: number | null = null;
  let pulled = 0;

  const reset = () => {
    startY = null;
    if (pulled) handlers.onProgress?.(0, false);
    pulled = 0;
  };

  function onStart(e: Event) {
    const t = e as TouchEvent;
    if (t.touches.length !== 1 || handlers.busy?.() || !handlers.atTop()) return reset();
    startY = t.touches[0].clientY;
    pulled = 0;
  }

  function onMove(e: Event) {
    const t = e as TouchEvent;
    if (startY === null || t.touches.length !== 1) return;
    if (!handlers.atTop()) return reset();
    const dy = t.touches[0].clientY - startY;
    if (dy <= 0) {
      if (pulled) handlers.onProgress?.(0, false);
      pulled = 0;
      return;
    }
    pulled = Math.min(dy * PULL.resistance, PULL.maxPull);
    handlers.onProgress?.(pulled, pulled >= PULL.threshold);
  }

  function onEnd() {
    const armed = startY !== null && pulled >= PULL.threshold;
    reset();
    if (armed) void handlers.onPull();
  }

  const opts: AddEventListenerOptions = { passive: true };
  target.addEventListener("touchstart", onStart, opts);
  target.addEventListener("touchmove", onMove, opts);
  target.addEventListener("touchend", onEnd, opts);
  target.addEventListener("touchcancel", reset, opts);
  const root = typeof document !== "undefined" ? document.documentElement : null;
  const before = root?.style.overscrollBehaviorY ?? "";
  if (root) root.style.overscrollBehaviorY = "contain";
  return () => {
    target.removeEventListener("touchstart", onStart);
    target.removeEventListener("touchmove", onMove);
    target.removeEventListener("touchend", onEnd);
    target.removeEventListener("touchcancel", reset);
    if (root) root.style.overscrollBehaviorY = before;
  };
}

/** The first card whose box is on screen below `header` px, and its top (px). */
export function cardUnder(header = 64): { id: string; top: number } | null {
  const items = document.querySelectorAll<HTMLElement>("[data-feed-item]");
  for (const node of items) {
    const rect = node.getBoundingClientRect();
    if (rect.bottom > header + 1 && rect.height > 0) {
      const id = node.dataset.feedItem;
      return id ? { id, top: rect.top } : null;
    }
  }
  return null;
}

function cardTop(id: string): number | null {
  const node = [...document.querySelectorAll<HTMLElement>("[data-feed-item]")].find((n) => n.dataset.feedItem === id);
  return node ? node.getBoundingClientRect().top : null;
}

/**
 * Run `change` (which inserts items above) and keep the card that was under the
 * finger where it was: the page scrolls by however far the card moved.
 * Returns how far the card ended up from where it was (px; 0 = exact).
 */
export async function keepAnchor(change: () => Promise<void>, header = 64): Promise<number> {
  const anchor = cardUnder(header);
  await change();
  if (!anchor) return 0;
  const after = cardTop(anchor.id);
  if (after === null) return 0;
  const moved = after - anchor.top;
  if (moved) window.scrollBy({ top: moved, behavior: "instant" as ScrollBehavior });
  return (cardTop(anchor.id) ?? anchor.top) - anchor.top;
}
