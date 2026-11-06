// WP 4c.4-B3 (08 §7.7): a failed next page is retried `next_page_retries` times
// with backoff `next_page_backoff_ms` × 2^n, then an inline retry card (Arabic
// in an Arabic UI), never an English toast; the sentinel is watched again after
// each attempt; the card's button recovers.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { applyDelivery, SAFE_DEFAULTS } from "@/lib/delivery";
import { useToastStore } from "@/stores/toasts";
import HomeView from "@/views/HomeView.vue";

import { feedItem, feedPage, flush, livePost, mount, routeApi, sentinelObserver, setup, teardown } from "./deliveryHarness";

vi.mock("@/components/layout/AppShell.vue", async () => (await import("./deliveryHarness")).shellStub());
vi.mock("@/components/post/CreatePostCard.vue", async () => (await import("./deliveryHarness")).blankStub());
vi.mock("@/components/auth/CompleteProfileCard.vue", async () => (await import("./deliveryHarness")).blankStub());
vi.mock("@/components/stories/StoriesRail.vue", async () => (await import("./deliveryHarness")).blankStub());

const A = "00000000-0000-4000-8000-00000000000a";
const B = "00000000-0000-4000-8000-00000000000b";
const down = () => Object.assign(new Error("Network Error"), { response: undefined });

afterEach(teardown);

/** A server block with a 1 ms backoff, so the 1/2/4 pattern is measured without waiting seconds. */
function fastBackoff() {
  applyDelivery("home", { ...SAFE_DEFAULTS.home, next_page_backoff_ms: 1 });
}

async function failingNextPage(okAfter: number) {
  let calls = 0;
  const api = routeApi({
    feed: (p) => {
      if (!p.cursor) return feedPage([feedItem(A)], "c1");
      calls++;
      if (calls <= okAfter) throw down();
      return feedPage([feedItem(B)], null);
    },
    batch: (ids) => ids.map((id) => livePost(id)),
  });
  return { api, calls: () => calls };
}

for (const lang of ["ar", "en"] as const) {
  describe(`next-page failure (${lang})`, () => {
    beforeEach(() => {
      setup(lang);
      fastBackoff();
    });

    it("retries 3 times with backoff 1×, 2×, 4× the configured step, then shows the inline retry card", async () => {
      const timeouts: number[] = [];
      const real = globalThis.setTimeout;
      vi.spyOn(globalThis, "setTimeout").mockImplementation(((fn: () => void, ms?: number) => {
        if (ms && ms > 0 && ms < 10) timeouts.push(ms);
        return real(fn, ms);
      }) as typeof setTimeout);
      const { calls } = await failingNextPage(99);
      const el = await mount(HomeView);
      await flush();
      const io = sentinelObserver()!;
      const unobserve = vi.spyOn(io, "unobserve");
      io.fire(true);
      await flush(40);
      expect(calls()).toBe(4); // the first try and 3 retries
      expect(timeouts.filter((ms) => [1, 2, 4].includes(ms))).toEqual([1, 2, 4]);
      expect(unobserve).toHaveBeenCalled(); // the sentinel is watched again after each attempt
      const card = el.querySelector('[data-testid="feed-retry"]')!;
      expect(card).not.toBeNull();
      expect(card.getAttribute("role")).toBe("alert");
      expect(card.textContent).toContain(lang === "ar" ? "تعذّر التحميل، حاول تاني" : "Couldn't load, try again");
      expect(useToastStore().items).toHaveLength(0); // no toast, in any language
      expect(el.querySelector('[data-testid="feed-sentinel"]')).toBeNull();
    });

    it("recovers by itself when a retry succeeds (within 3 retries)", async () => {
      const { calls } = await failingNextPage(2);
      const el = await mount(HomeView);
      await flush();
      sentinelObserver()!.fire(true);
      await flush(40);
      expect(calls()).toBe(3);
      expect([...el.querySelectorAll<HTMLElement>("[data-feed-item]")].map((n) => n.dataset.feedItem)).toEqual([A, B]);
      expect(el.querySelector('[data-testid="feed-retry"]')).toBeNull();
    });

    it("the retry card's button asks again and the feed continues", async () => {
      const { calls } = await failingNextPage(4);
      const el = await mount(HomeView);
      await flush();
      sentinelObserver()!.fire(true);
      await flush(40);
      expect(calls()).toBe(4);
      el.querySelector<HTMLButtonElement>('[data-testid="feed-retry-button"]')!.click();
      await flush(20);
      expect(calls()).toBe(5);
      expect(el.querySelector('[data-testid="feed-retry"]')).toBeNull();
      expect([...el.querySelectorAll<HTMLElement>("[data-feed-item]")].map((n) => n.dataset.feedItem)).toEqual([A, B]);
    });
  });
}
