// R3 WP 4b.8 (06 §6.1): pull-to-refresh. Touch only and only at the top; a pull
// past the threshold asks a first page with entry=pull; new items go in above with
// no duplicate, and the card under the finger stays where it was.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resetPageEntry } from "@/lib/homeRefresh";
import { attachPullToRefresh, keepAnchor, PULL } from "@/lib/pullToRefresh";
import HomeView from "@/views/HomeView.vue";

import { feedItem, feedPage, flush, ID, livePost, mount, routeApi, setup, teardown } from "./deliveryHarness";

vi.mock("@/components/layout/AppShell.vue", async () => (await import("./deliveryHarness")).shellStub());
vi.mock("@/components/post/CreatePostCard.vue", async () => (await import("./deliveryHarness")).blankStub());
vi.mock("@/components/auth/CompleteProfileCard.vue", async () => (await import("./deliveryHarness")).blankStub());
vi.mock("@/components/stories/StoriesRail.vue", async () => (await import("./deliveryHarness")).blankStub());

function touch(type: string, y: number, target: EventTarget = document) {
  const e = new Event(type, { bubbles: true }) as Event & { touches: Array<{ clientY: number }> };
  Object.defineProperty(e, "touches", { value: type === "touchend" ? [] : [{ clientY: y }] });
  target.dispatchEvent(e);
}

function pull(px: number) {
  touch("touchstart", 100);
  touch("touchmove", 100 + px / 2);
  touch("touchmove", 100 + px / PULL.resistance);
  touch("touchend", 0);
}

describe("the gesture", () => {
  it("refreshes after a pull past the threshold, at the top only", () => {
    const onPull = vi.fn();
    const progress: Array<[number, boolean]> = [];
    let top = true;
    const off = attachPullToRefresh({ atTop: () => top, onPull, onProgress: (px, armed) => progress.push([px, armed]) });
    pull(PULL.threshold - 10);
    expect(onPull).not.toHaveBeenCalled();
    pull(PULL.threshold + 10);
    expect(onPull).toHaveBeenCalledTimes(1);
    expect(progress.some(([, armed]) => armed)).toBe(true);
    expect(progress.at(-1)).toEqual([0, false]); // the indicator goes away
    top = false;
    pull(PULL.maxPull * 3);
    expect(onPull).toHaveBeenCalledTimes(1);
    off();
    top = true;
    pull(PULL.maxPull * 3);
    expect(onPull).toHaveBeenCalledTimes(1); // detached
  });

  it("ignores an upward drag, two fingers, and a pull while busy", () => {
    const onPull = vi.fn();
    let busy = false;
    const off = attachPullToRefresh({ atTop: () => true, onPull, busy: () => busy });
    touch("touchstart", 300);
    touch("touchmove", 100);
    touch("touchend", 0);
    const two = new Event("touchstart") as Event & { touches: unknown[] };
    Object.defineProperty(two, "touches", { value: [{ clientY: 0 }, { clientY: 10 }] });
    document.dispatchEvent(two);
    touch("touchend", 0);
    busy = true;
    pull(PULL.maxPull * 3);
    expect(onPull).not.toHaveBeenCalled();
    off();
  });

  it("turns the page's own overscroll refresh off while listening", () => {
    const off = attachPullToRefresh({ atTop: () => true, onPull: () => undefined });
    expect(document.documentElement.style.overscrollBehaviorY).toBe("contain");
    off();
    expect(document.documentElement.style.overscrollBehaviorY).toBe("");
  });
});

describe("keepAnchor", () => {
  it("scrolls by however far the card under the finger moved", async () => {
    document.body.innerHTML = `<div data-feed-item="a"></div><div data-feed-item="b"></div>`;
    const [a] = document.querySelectorAll<HTMLElement>("[data-feed-item]");
    let shift = 0;
    a.getBoundingClientRect = () => ({ top: 80 + shift, bottom: 600 + shift, height: 520 }) as DOMRect;
    const scrollBy = vi.fn(({ top }: { top: number }) => {
      shift -= top;
    });
    vi.stubGlobal("scrollBy", scrollBy);
    const off = await keepAnchor(async () => {
      shift = 1500; // three cards went in above
    });
    expect(scrollBy).toHaveBeenCalledWith({ top: 1500, behavior: "instant" });
    expect(Math.abs(off)).toBeLessThanOrEqual(8);
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });
});

describe("Home: pull-to-refresh (ar)", () => {
  beforeEach(() => {
    setup("ar");
    resetPageEntry();
    Object.defineProperty(window, "scrollY", { value: 0, configurable: true, writable: true });
  });
  afterEach(() => teardown());

  it("asks entry=pull and inserts only the new items above, without duplicates", async () => {
    const P = (n: number) => ID(300 + n);
    let firsts = 0;
    const { get } = routeApi({
      feed: (p) => {
        if (p.cursor) return feedPage([], null);
        firsts++;
        const ids = firsts === 1 ? [1, 2, 3] : [7, 8, 1, 2];
        return feedPage(ids.map((n) => feedItem(P(n))), "c1", { meta: { as_of: "2026-11-05T10:00:00+00:00", visit: null } });
      },
      batch: (ids) => ids.map((id) => livePost(id)),
    });
    vi.stubGlobal("scrollBy", vi.fn());
    const el = await mount(HomeView, "/home?mode=recent");
    pull(PULL.threshold * 2);
    await flush(20);
    const params = get.mock.calls.filter(([u]) => u === "/feed/").map(([, c]) => (c as { params: Record<string, unknown> }).params);
    expect(params[1]).toMatchObject({ entry: "pull", mode: "recent" });
    const ids = [...el.querySelectorAll<HTMLElement>("[data-feed-item]")].map((n) => n.dataset.feedItem);
    expect(ids).toEqual([P(7), P(8), P(1), P(2), P(3)]);
    // The pill says how many went in above (count from the insert, not a guess).
    expect(el.querySelector<HTMLElement>('[data-testid="new-posts-pill"] button')?.dataset.count).toBe("2");
    expect(el.querySelector('[data-testid="pull-indicator"]')).toBeNull();
  });
});
