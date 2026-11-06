// WP 4c.8-B3 (08 §7.6): the feed position survives a full reload in the
// chronological modes: stored on pagehide in sessionStorage; restored within the
// window by asking the first page with entry=reload and paging forward until the
// card is in (at most 3 pages); otherwise a normal open from the top.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearPosition, readPosition, savePosition } from "@/lib/feedPosition";
import HomeView from "@/views/HomeView.vue";

import { feedItem, feedPage, flush, livePost, mount, routeApi, setup, teardown } from "./deliveryHarness";

vi.mock("@/components/layout/AppShell.vue", async () => (await import("./deliveryHarness")).shellStub());
vi.mock("@/components/post/CreatePostCard.vue", async () => (await import("./deliveryHarness")).blankStub());
vi.mock("@/components/auth/CompleteProfileCard.vue", async () => (await import("./deliveryHarness")).blankStub());
vi.mock("@/components/stories/StoriesRail.vue", async () => (await import("./deliveryHarness")).blankStub());

const P = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const NOW = 1_800_000_000_000;

beforeEach(() => setup("ar"));
afterEach(() => {
  teardown();
  clearPosition();
});

describe("stored position", () => {
  it("round-trips for a chronological mode within 30 minutes", () => {
    expect(savePosition({ surface: "home", mode: "recent", anchor_post_id: P(5), offset_px: 120.4, cursor: "c2" }, NOW)).toBe(true);
    expect(readPosition("recent", NOW + 29 * 60_000)).toMatchObject({ anchor_post_id: P(5), offset_px: 120, cursor: "c2" });
    expect(readPosition("recent", NOW + 31 * 60_000)).toBeNull(); // too old: start at the top
    expect(readPosition("following", NOW)).toBeNull(); // another mode
  });

  it("is never kept for a ranked mode, nor for junk", () => {
    expect(savePosition({ surface: "home", mode: "for_you" as never, anchor_post_id: P(5), offset_px: 0, cursor: null }, NOW)).toBe(false);
    expect(savePosition({ surface: "home", mode: "recent", anchor_post_id: "<script>", offset_px: 0, cursor: null }, NOW)).toBe(false);
    sessionStorage.setItem("tara.feedPosition.v1", "{not json");
    expect(readPosition("recent", NOW)).toBeNull();
  });

  it("survives blocked storage without throwing", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(savePosition({ surface: "home", mode: "recent", anchor_post_id: P(5), offset_px: 0, cursor: null })).toBe(false);
  });
});

describe("Home on load", () => {
  it("asks entry=open on a normal first load", async () => {
    const { get } = routeApi({ feed: () => feedPage([feedItem(P(1))], null), batch: (ids) => ids.map((id) => livePost(id)) });
    await mount(HomeView, "/home?mode=recent");
    expect(get.mock.calls.find(([u]) => u === "/feed/")?.[1]).toMatchObject({ params: { entry: "open", mode: "recent" } });
  });

  it("on a reload pages forward with entry=reload until the anchor is in (max 3 pages), then scrolls to it", async () => {
    vi.spyOn(performance, "getEntriesByType").mockReturnValue([{ type: "reload" }] as never);
    savePosition({ surface: "home", mode: "recent", anchor_post_id: P(25), offset_px: 40, cursor: "c2" });
    const scroll = vi.fn();
    vi.stubGlobal("scrollTo", scroll);
    const pages: Record<string, ReturnType<typeof feedPage>> = {
      "": feedPage([1, 2, 3].map((n) => feedItem(P(n))), "c1"),
      c1: feedPage([11, 12].map((n) => feedItem(P(n))), "c2"),
      c2: feedPage([25, 26].map((n) => feedItem(P(n))), "c3"),
      c3: feedPage([31].map((n) => feedItem(P(n))), null),
    };
    const { get } = routeApi({ feed: (p) => pages[(p.cursor as string) ?? ""], batch: (ids) => ids.map((id) => livePost(id)) });
    const el = await mount(HomeView, "/home?mode=recent");
    await flush(20);
    const feedCalls = get.mock.calls.filter(([u]) => u === "/feed/").map(([, c]) => (c as { params: Record<string, string> }).params);
    expect(feedCalls[0]).toMatchObject({ entry: "reload", mode: "recent" });
    expect(feedCalls.slice(0, 3).map((p) => p.cursor ?? "")).toEqual(["", "c1", "c2"]);
    expect(feedCalls.some((p) => p.cursor === "c3")).toBe(false); // stopped once the card was in
    expect(el.querySelector(`[data-feed-item="${P(25)}"]`)).not.toBeNull();
    expect(scroll).toHaveBeenCalled();
  });

  it("gives up after 3 pages and stays at the top when the card is gone", async () => {
    vi.spyOn(performance, "getEntriesByType").mockReturnValue([{ type: "reload" }] as never);
    savePosition({ surface: "home", mode: "recent", anchor_post_id: P(99), offset_px: 0, cursor: null });
    let n = 0;
    const { get } = routeApi({ feed: () => feedPage([feedItem(P(++n))], `c${n}`), batch: (ids) => ids.map((id) => livePost(id)) });
    await mount(HomeView, "/home?mode=recent");
    await flush(20);
    expect(get.mock.calls.filter(([u]) => u === "/feed/")).toHaveLength(3);
  });

  it("stores the card at the top on pagehide (chronological modes only)", async () => {
    routeApi({ feed: () => feedPage([feedItem(P(1)), feedItem(P(2))], null), batch: (ids) => ids.map((id) => livePost(id)) });
    const el = await mount(HomeView, "/home?mode=recent");
    await flush();
    const cards = el.querySelectorAll<HTMLElement>("[data-feed-item]");
    cards[0].getBoundingClientRect = () => ({ top: -500, bottom: 60, height: 560 }) as DOMRect;
    cards[1].getBoundingClientRect = () => ({ top: 60, bottom: 600, height: 540 }) as DOMRect;
    window.dispatchEvent(new Event("pagehide"));
    expect(readPosition("recent")).toMatchObject({ anchor_post_id: P(2), offset_px: 4 });
  });
});
