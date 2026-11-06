// R3 WP 4b.7 (06 §6.2): "New since your last visit" after `meta.visit.anchor_index`,
// only from `min_to_show` new rows, and "You're all caught up" at
// `meta.caught_up_index`, in Arabic (RTL) and English; never duplicating the end card.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { i18n } from "@/i18n";
import { resetPageEntry } from "@/lib/homeRefresh";
import HomeView from "@/views/HomeView.vue";

import { feedItem, feedPage, flush, ID, livePost, mount, routeApi, setup, teardown } from "./deliveryHarness";

vi.mock("@/components/layout/AppShell.vue", async () => (await import("./deliveryHarness")).shellStub());
vi.mock("@/components/post/CreatePostCard.vue", async () => (await import("./deliveryHarness")).blankStub());
vi.mock("@/components/auth/CompleteProfileCard.vue", async () => (await import("./deliveryHarness")).blankStub());
vi.mock("@/components/stories/StoriesRail.vue", async () => (await import("./deliveryHarness")).blankStub());

const P = (n: number) => ID(200 + n);

function visitMeta(newCount: number, anchor: number | null, caught: number | null, minToShow = 3) {
  return {
    as_of: "2026-11-08T10:00:00+00:00",
    refresh_after_s: 600,
    auto_refetch_after_s: 1800,
    visit: { kind: "returning", since: "2026-11-05T10:00:00+00:00", new_count: newCount, anchor_index: anchor, min_to_show: minToShow },
    caught_up_index: caught,
  };
}

/** The feed's children in order: post ids, and the markers by their test id. */
function sequence(el: HTMLElement): string[] {
  const out: string[] = [];
  el.querySelectorAll<HTMLElement>("[data-feed-item], [data-testid='new-since-divider'], [data-testid='caught-up-marker']").forEach((n) => {
    out.push(n.dataset.feedItem ?? (n.dataset.testid as string));
  });
  return out;
}

async function home(items: number[], meta: Record<string, unknown>, next: string | null = "c1") {
  routeApi({
    feed: (p) => (p.cursor ? feedPage([], null) : feedPage(items.map((n) => feedItem(P(n))), next, { meta })),
    batch: (ids) => ids.map((id) => livePost(id)),
  });
  const el = await mount(HomeView, "/home?mode=recent");
  await flush();
  return el;
}

for (const locale of ["ar", "en"] as const) {
  describe(`new since your last visit (${locale})`, () => {
    beforeEach(() => {
      setup(locale);
      resetPageEntry();
    });
    afterEach(() => teardown());

    it("draws the divider after the new rows and the caught-up marker at the first older one", async () => {
      // A return after 3 days: 4 new rows on top, then older ones (recent: order unchanged).
      const el = await home([1, 2, 3, 4, 5, 6], visitMeta(4, 4, 4));
      expect(sequence(el)).toEqual([P(1), P(2), P(3), P(4), "new-since-divider", "caught-up-marker", P(5), P(6)]);
      const divider = el.querySelector<HTMLElement>('[data-testid="new-since-divider"]')!;
      const marker = el.querySelector<HTMLElement>('[data-testid="caught-up-marker"]')!;
      const words = locale === "ar" ? ["جديد من آخر زيارة", "انت كده شفت الجديد"] : ["New since your last visit", "You're all caught up"];
      expect(divider.textContent?.trim()).toBe(words[0]);
      expect(marker.textContent?.trim()).toBe(words[1]);
      expect(divider.getAttribute("role")).toBe("separator");
      expect(divider.getAttribute("aria-label")).toBe(words[0]);
      expect(document.documentElement.dir).toBe(locale === "ar" ? "rtl" : "ltr");
      // Logical classes only (flex + gap), no left/right that would break RTL.
      expect(divider.className).not.toMatch(/\b(ml|mr|pl|pr|left|right)-/);
      expect(i18n.global.t("homeRefresh.newSince")).toBe(words[0]);
    });

    it("hides the divider under min_to_show new rows, keeping the marker", async () => {
      const el = await home([1, 2, 3, 4], visitMeta(2, 2, 2));
      expect(sequence(el)).toEqual([P(1), P(2), "caught-up-marker", P(3), P(4)]);
    });

    it("shows nothing when nothing is new (a second open 45 minutes later)", async () => {
      const el = await home([1, 2, 3], visitMeta(0, null, null));
      expect(sequence(el)).toEqual([P(1), P(2), P(3)]);
    });

    it("shows nothing with personalization off (meta.visit null)", async () => {
      const el = await home([1, 2], { as_of: "2026-11-08T10:00:00+00:00", visit: null, caught_up_index: null });
      expect(sequence(el)).toEqual([P(1), P(2)]);
    });

    it("For You with no circle item left: the marker before the first suggestion", async () => {
      const el = await home([1, 2], visitMeta(0, null, 0));
      expect(sequence(el)).toEqual(["caught-up-marker", P(1), P(2)]);
    });

    it("never repeats the end card: no marker after the very last post when nothing more comes", async () => {
      const el = await home([1, 2, 3], visitMeta(3, 3, 3), null);
      expect(sequence(el)).toEqual([P(1), P(2), P(3), "new-since-divider"]);
      expect(el.querySelector('[data-testid="feed-end"]')).not.toBeNull();
    });
  });
}
