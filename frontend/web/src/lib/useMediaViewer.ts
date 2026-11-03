import { computed, type ComputedRef } from "vue";
import { useRoute, useRouter } from "vue-router";

import { clampIndex, formatView, parseView, VIEW_PARAM } from "@/lib/mediaViewer";

export interface MediaViewer {
  /** The open photo's index, or null while this post's viewer is closed. */
  index: ComputedRef<number | null>;
  open: (index: number) => void;
  go: (index: number) => void;
  close: () => void;
}

// Marks the history entry the viewer pushed, so closing goes Back (the entry
// disappears) only when this app added it, never off a page opened from a link.
const STATE_KEY = "taraViewer";

/** The viewer for one post's photos, kept in `?view=<key>:<index>`. */
export function useMediaViewer(getKey: () => string, getCount: () => number): MediaViewer {
  const route = useRoute();
  const router = useRouter();

  const index = computed<number | null>(() => {
    const target = parseView(route.query[VIEW_PARAM]);
    if (!target || target.postId !== getKey() || getCount() <= 0) return null;
    return clampIndex(target.index, getCount());
  });

  function withView(value: string | null) {
    const query = { ...route.query };
    if (value === null) delete query[VIEW_PARAM];
    else query[VIEW_PARAM] = value;
    return { query, hash: route.hash };
  }

  return {
    index,
    open(i: number) {
      const to = withView(formatView(getKey(), clampIndex(i, getCount())));
      router.push({ ...to, state: { [STATE_KEY]: true } }).catch(() => {});
    },
    go(i: number) {
      const to = withView(formatView(getKey(), clampIndex(i, getCount())));
      // Keep the mark as it was: a viewer opened from a link must still not go Back.
      const pushed = !!window.history.state?.[STATE_KEY];
      router.replace({ ...to, state: { [STATE_KEY]: pushed } }).catch(() => {});
    },
    close() {
      if (window.history.state?.[STATE_KEY]) {
        router.back();
      } else {
        // Opened from a link: stay on the page, just drop the parameter.
        router.replace(withView(null)).catch(() => {});
      }
    },
  };
}
