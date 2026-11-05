// Pure helpers for the reels pager (components/reels/ReelPager.vue), kept apart
// so they are unit tested without a browser.
import { ref } from "vue";

/** At most this many players exist at once: the active reel and one on each side. */
export const MAX_MOUNTED = 3;

/** The indexes whose <video> is mounted around `active` (clamped to the list). */
export function mountedRange(active: number, length: number): { start: number; end: number } {
  if (length <= 0) return { start: 0, end: -1 };
  const at = Math.min(Math.max(active, 0), length - 1);
  let start = Math.max(0, at - 1);
  const end = Math.min(length - 1, start + MAX_MOUNTED - 1);
  start = Math.max(0, end - MAX_MOUNTED + 1);
  return { start, end };
}

export function isMounted(index: number, active: number, length: number): boolean {
  const { start, end } = mountedRange(active, length);
  return index >= start && index <= end;
}

/** Which slide fills the snap container at this scroll position. */
export function indexFromScroll(scrollTop: number, slideHeight: number, length: number): number {
  if (length <= 0 || slideHeight <= 0) return 0;
  return Math.min(length - 1, Math.max(0, Math.round(scrollTop / slideHeight)));
}

/**
 * Tell a tap from a double tap: `single` runs once no second tap came within
 * `delayMs`; `double` runs at once on the second tap (and cancels the single).
 */
export function createTapDetector(single: () => void, double: () => void, delayMs = 280) {
  let timer: ReturnType<typeof setTimeout> | null = null;
  return function tap() {
    if (timer) {
      clearTimeout(timer);
      timer = null;
      double();
      return;
    }
    timer = setTimeout(() => {
      timer = null;
      single();
    }, delayMs);
  };
}

/** Reels start muted (autoplay rules); unmuting once lasts for the visit. */
export const reelsMuted = ref(true);

/** "1.2K"-style counts in the viewer's locale. */
export function compactCount(n: number, locale: string): string {
  try {
    return new Intl.NumberFormat(locale, { notation: "compact", maximumFractionDigits: 1 }).format(n);
  } catch {
    return String(n);
  }
}
