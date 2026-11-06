// WP 4c.1-B3 / 4c.4-B3 (08 §7.4, §7.7): Home draws the `/feed/` snapshots at
// once, hydrates them in place, removes what hydration omits, and shows card
// skeletons (3 on the first load, 2 for the next page) instead of text rows.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { railsHeld, railsReady } from "@/lib/delivery";
import type { Post } from "@/types";
import HomeView from "@/views/HomeView.vue";

import { feedItem, feedPage, flush, livePost, mount, routeApi, sentinelObserver, setup, teardown } from "./deliveryHarness";

vi.mock("@/components/layout/AppShell.vue", async () => (await import("./deliveryHarness")).shellStub());
vi.mock("@/components/post/CreatePostCard.vue", async () => (await import("./deliveryHarness")).blankStub());
vi.mock("@/components/auth/CompleteProfileCard.vue", async () => (await import("./deliveryHarness")).blankStub());
vi.mock("@/components/stories/StoriesRail.vue", async () => (await import("./deliveryHarness")).blankStub());

const A = "00000000-0000-4000-8000-00000000000a";
const B = "00000000-0000-4000-8000-00000000000b";
const C = "00000000-0000-4000-8000-00000000000c";

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

beforeEach(() => setup("en"));
afterEach(teardown);

const items = (el: HTMLElement) =>
  [...el.querySelectorAll<HTMLElement>("[data-feed-item]")].map((n) => `${n.dataset.feedItem}:${n.dataset.feedState}`);

describe("first paint from snapshots", () => {
  it("shows three card skeletons (no text rows) until the first page answers", async () => {
    const page = deferred<unknown>();
    routeApi({ feed: () => page.promise, batch: () => [] });
    const el = await mount(HomeView);
    const first = el.querySelector('[data-testid="feed-first-loading"]')!;
    expect(first.querySelectorAll('[data-testid="feed-card-skeleton"]')).toHaveLength(3);
    expect(first.getAttribute("role")).toBe("status");
    expect(first.querySelector(".skeleton.aspect-\\[4\\/3\\]")).not.toBeNull(); // a media block sized like a card
    page.resolve(feedPage([], null));
    await flush();
    expect(el.querySelector('[data-testid="feed-first-loading"]')).toBeNull();
  });

  it("draws snapshots before hydration: content only when the server sent it, ids-only as a skeleton", async () => {
    const batch = deferred<Post[]>();
    const { get } = routeApi({ feed: () => feedPage([feedItem(A), feedItem(B, false)], null), batch: () => batch.promise });
    const el = await mount(HomeView);
    // One API call before the first post: /feed/ (no limit sent, the server applies the sizes).
    const feedCalls = get.mock.calls.filter(([url]) => url === "/feed/");
    expect(feedCalls).toHaveLength(1);
    // R3 (06 §4.2): the first page names how it was reached (`load`, then `nav`).
    expect(feedCalls[0][1]?.params).toMatchObject({ entry: expect.stringMatching(/^(load|nav)$/) });
    expect(feedCalls[0][1]?.params).not.toHaveProperty("limit");

    expect(items(el)).toEqual([`${A}:snapshot`, `${B}:snapshot`]);
    const a = el.querySelector(`[data-feed-item="${A}"]`)!;
    expect(a.querySelector('[data-testid="feed-snapshot-card"]')?.textContent).toContain(`snap ${A}`);
    // No counts drawn from a snapshot: the action row is a skeleton.
    expect(a.querySelector('[data-testid="post-actions"], [aria-label*="reaction" i]')).toBeNull();
    const b = el.querySelector(`[data-feed-item="${B}"]`)!;
    expect(b.querySelector('[data-testid="feed-card-skeleton"]')).not.toBeNull();
    expect(b.textContent?.trim()).toBe(""); // ids only: no text at all
    expect(b.querySelector("[data-post-id]")).toBeNull();

    batch.resolve([livePost(A), livePost(B)]);
    await flush();
    // Same keys, same order, now the live cards.
    expect(items(el)).toEqual([`${A}:live`, `${B}:live`]);
    expect(el.querySelector(`[data-feed-item="${A}"] article`)?.textContent).toContain(`live ${A}`);
    expect(el.querySelector(`[data-feed-item="${B}"] article`)?.textContent).toContain(`live ${B}`);
  });

  it("removes a card whose post hydration leaves out (deleted or no longer visible)", async () => {
    routeApi({ feed: () => feedPage([feedItem(A), feedItem(B, false), feedItem(C)], null), batch: () => [livePost(A), livePost(C)] });
    const el = await mount(HomeView);
    await flush();
    expect(items(el)).toEqual([`${A}:live`, `${C}:live`]);
    expect(el.textContent).not.toContain(B);
  });

  it("drops id-only cards when hydration fails, and keeps only snapshots that carried content", async () => {
    routeApi({
      feed: () => feedPage([feedItem(A), feedItem(B, false)], null),
      batch: () => Promise.reject(Object.assign(new Error("503"), { response: { status: 503 } })),
    });
    const el = await mount(HomeView);
    await flush();
    expect(items(el)).toEqual([`${A}:snapshot`]);
  });
});

describe("rails wait for the first card (08 §7.4)", () => {
  it("are held while Home's first page loads, and released once a card is drawn", async () => {
    const page = deferred<unknown>();
    routeApi({ feed: () => page.promise, batch: () => [livePost(A)] });
    await mount(HomeView);
    expect(railsHeld()).toBe(true);
    let started = false;
    void railsReady().then(() => (started = true));
    await flush();
    expect(started).toBe(false);
    page.resolve(feedPage([feedItem(A)], null));
    await flush();
    expect(started).toBe(true);
  });

  it("are released after defer_rails_max_ms at the latest", async () => {
    vi.useFakeTimers();
    try {
      routeApi({ feed: () => new Promise(() => {}) });
      const { holdRails } = await import("@/lib/delivery");
      holdRails(1500);
      let started = false;
      void railsReady().then(() => (started = true));
      await vi.advanceTimersByTimeAsync(1499);
      expect(started).toBe(false);
      await vi.advanceTimersByTimeAsync(1);
      expect(started).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("next page", () => {
  it("shows two card skeletons while it loads", async () => {
    const next = deferred<unknown>();
    routeApi({
      feed: (p) => (p.cursor ? next.promise : feedPage([feedItem(A)], "c1")),
      batch: (ids) => ids.map((id) => livePost(id)),
    });
    const el = await mount(HomeView);
    await flush();
    sentinelObserver()!.fire(true);
    await flush(2);
    const loading = el.querySelector('[data-testid="feed-next-loading"]')!;
    expect(loading.querySelectorAll('[data-testid="feed-card-skeleton"]')).toHaveLength(2);
    expect(el.textContent).not.toContain("Loading…");
    next.resolve(feedPage([feedItem(B)], null));
    await flush();
    expect(el.querySelector('[data-testid="feed-next-loading"]')).toBeNull();
  });

  it("is asked for once per cursor, however many triggers fire while it is pending", async () => {
    const next = deferred<unknown>();
    const { get } = routeApi({
      feed: (p) => (p.cursor ? next.promise : feedPage([feedItem(A)], "c1")),
      batch: (ids) => ids.map((id) => livePost(id)),
    });
    await mount(HomeView);
    await flush();
    sentinelObserver()!.fire(true);
    sentinelObserver()?.fire(true);
    await flush(2);
    expect(get.mock.calls.filter(([url, c]) => url === "/feed/" && (c as { params: { cursor?: string } }).params.cursor === "c1")).toHaveLength(1);
    next.resolve(feedPage([], null));
    await flush();
  });

  it("uses a sentinel margin of prefetch_root_margin_vp viewports (computed, not 600px)", async () => {
    routeApi({ feed: () => feedPage([feedItem(A)], "c1"), batch: (ids) => ids.map((id) => livePost(id)) });
    await mount(HomeView);
    await flush();
    const io = sentinelObserver()!;
    expect(io.options.rootMargin).toBe(`${Math.round(2.5 * window.innerHeight)}px 0px`);
  });
});

describe("virtualization (08 §7.10)", () => {
  const many = (n: number) => Array.from({ length: n }, (_, i) => `00000000-0000-4000-8000-${String(i + 1).padStart(12, "0")}`);

  it("after virtualize_after_items, a card beyond keep_mounted_vp becomes a placeholder of its height and comes back", async () => {
    const ids = many(45);
    routeApi({ feed: () => feedPage(ids.map((id) => feedItem(id)), null), batch: (asked) => asked.map((id) => livePost(id)) });
    const el = await mount(HomeView);
    await flush();
    const { FakeIO } = await import("./deliveryHarness");
    const far = FakeIO.all.find((o) => o.options.rootMargin === `${Math.round(3 * window.innerHeight)}px 0px`)!;
    const first = el.querySelector<HTMLElement>(`[data-feed-item="${ids[0]}"]`)!;
    far.fire(false, first, { boundingClientRect: { top: -5000, bottom: -4100, height: 900 } as DOMRectReadOnly });
    await flush();
    const placeholder = el.querySelector<HTMLElement>(`[data-feed-item="${ids[0]}"]`)!;
    expect(placeholder.hasAttribute("data-feed-parked")).toBe(true);
    expect(placeholder.style.height).toBe("900px");
    expect(placeholder.querySelector("article")).toBeNull();
    // The placeholder is watched in turn; coming near again mounts the card.
    expect(far.targets.has(placeholder)).toBe(true);
    far.fire(true, placeholder);
    await flush();
    const back = el.querySelector<HTMLElement>(`[data-feed-item="${ids[0]}"]`)!;
    expect(back.hasAttribute("data-feed-parked")).toBe(false);
    expect(back.querySelector("article")).not.toBeNull();
  });

  it("parks nothing while the list is short", async () => {
    const ids = many(5);
    routeApi({ feed: () => feedPage(ids.map((id) => feedItem(id)), null), batch: (asked) => asked.map((id) => livePost(id)) });
    const el = await mount(HomeView);
    await flush();
    const { FakeIO } = await import("./deliveryHarness");
    const far = FakeIO.all.find((o) => o.options.rootMargin === `${Math.round(3 * window.innerHeight)}px 0px`)!;
    far.fire(false, el.querySelector(`[data-feed-item="${ids[0]}"]`)!);
    await flush();
    expect(el.querySelector("[data-feed-parked]")).toBeNull();
  });
});
