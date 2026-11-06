// WP 4c.4-B3 (08 §7.7): "You're all caught up" only when the server says there
// is nothing more (has_more false), with links to Explore and Reels; never while
// has_more is true; in `for_you` too, the marker is the server's has_more.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import FeedEndCard from "@/components/feed/FeedEndCard.vue";
import HomeView from "@/views/HomeView.vue";

import { feedItem, feedPage, flush, livePost, mount, routeApi, setup, teardown } from "./deliveryHarness";

vi.mock("@/components/layout/AppShell.vue", async () => (await import("./deliveryHarness")).shellStub());
vi.mock("@/components/post/CreatePostCard.vue", async () => (await import("./deliveryHarness")).blankStub());
vi.mock("@/components/auth/CompleteProfileCard.vue", async () => (await import("./deliveryHarness")).blankStub());
vi.mock("@/components/stories/StoriesRail.vue", async () => (await import("./deliveryHarness")).blankStub());

const A = "00000000-0000-4000-8000-00000000000a";

afterEach(teardown);

for (const lang of ["ar", "en"] as const) {
  describe(`end of feed (${lang})`, () => {
    beforeEach(() => setup(lang));

    it("shows the end card with Explore and Reels links when has_more is false", async () => {
      routeApi({ feed: () => feedPage([feedItem(A)], null), batch: (ids) => ids.map((id) => livePost(id)) });
      const el = await mount(HomeView);
      await flush();
      const end = el.querySelector('[data-testid="feed-end"]')!;
      expect(end.textContent).toContain(lang === "ar" ? "خلّصت كل الجديد" : "You're all caught up");
      expect(end.querySelector('[data-testid="feed-end-explore"]')?.getAttribute("href")).toBe("/search");
      expect(end.querySelector('[data-testid="feed-end-reels"]')?.getAttribute("href")).toBe("/reels");
      // Directional chevrons are mirrored in RTL.
      expect(end.querySelectorAll("svg.rtl\\:-scale-x-100")).toHaveLength(2);
    });

    it("never shows while has_more is true", async () => {
      routeApi({ feed: () => feedPage([feedItem(A)], "c1"), batch: (ids) => ids.map((id) => livePost(id)) });
      const el = await mount(HomeView);
      await flush();
      expect(el.querySelector('[data-testid="feed-end"]')).toBeNull();
      expect(el.querySelector('[data-testid="feed-sentinel"]')).not.toBeNull();
    });

    it("in for_you follows the server's has_more, not the circle's caught-up marker", async () => {
      routeApi({
        feed: () => feedPage([feedItem(A)], "c1", { mode: "for_you", meta: { caught_up_index: 0 } }),
        batch: (ids) => ids.map((id) => livePost(id)),
      });
      const el = await mount(HomeView, "/home?mode=for_you");
      await flush();
      expect(el.querySelector('[data-testid="feed-end"]')).toBeNull();
    });

    it("is not shown on an empty feed (the empty state is)", async () => {
      routeApi({ feed: () => feedPage([], null), batch: () => [] });
      const el = await mount(HomeView);
      await flush();
      expect(el.querySelector('[data-testid="feed-end"]')).toBeNull();
    });
  });
}

describe("FeedEndCard", () => {
  it("has a labelled region", async () => {
    setup("en");
    const el = await mount(FeedEndCard);
    const section = el.querySelector("section")!;
    expect(section.getAttribute("aria-labelledby")).toBe("feed-end-title");
    expect(el.querySelector("#feed-end-title")?.textContent).toBe("You're all caught up");
    teardown();
  });
});
