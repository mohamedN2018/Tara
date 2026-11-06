// R3 WP 4b.8 (06 §6.1, 08 §7.6): refresh on return. The time away decides between
// nothing, the "new posts" pill (a peek; list and scroll unchanged) and a silent
// first page with entry=return at the top; the thresholds are the server's. Also
// the entry hints, the sid, 429 with Retry-After and the fallback refill.
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, KeepAlive, ref } from "vue";

import {
  createHomeRefresh,
  decideReturn,
  pageEntry,
  REFRESH_DEFAULTS,
  resetPageEntry,
  retryAfterMs,
  timersFrom,
} from "@/lib/homeRefresh";
import { resetSignals } from "@/lib/signals";
import { tokenStore } from "@/lib/tokens";
import HomeView from "@/views/HomeView.vue";

import { feedItem, feedPage, flush, ID, livePost, mount, routeApi, setup, teardown } from "./deliveryHarness";

vi.mock("@/components/layout/AppShell.vue", async () => (await import("./deliveryHarness")).shellStub());
vi.mock("@/components/post/CreatePostCard.vue", async () => (await import("./deliveryHarness")).blankStub());
vi.mock("@/components/auth/CompleteProfileCard.vue", async () => (await import("./deliveryHarness")).blankStub());
vi.mock("@/components/stories/StoriesRail.vue", async () => (await import("./deliveryHarness")).blankStub());

const here = dirname(fileURLToPath(import.meta.url));
const homeDefaults = JSON.parse(readFileSync(resolve(here, "../../../../services/feed/intel/config/defaults/home.json"), "utf8"));

const MIN = 60_000;
const T = timersFrom(600, 1800);

describe("the return rule", () => {
  it("nothing before refresh_after_s, the pill after, a refetch at the top after auto_refetch_after_s", () => {
    expect(decideReturn(9 * MIN, false, T)).toBe("none");
    expect(decideReturn(10 * MIN, false, T)).toBe("peek");
    expect(decideReturn(10 * MIN, true, T)).toBe("peek");
    expect(decideReturn(29 * MIN, true, T)).toBe("peek");
    expect(decideReturn(30 * MIN, true, T)).toBe("refetch");
    expect(decideReturn(45 * MIN, false, T)).toBe("peek"); // scrolled: never replace the list
    expect(decideReturn(Number.NaN, true, T)).toBe("none");
  });

  it("uses the server's timers, and the backend's package defaults before the first answer", () => {
    expect(REFRESH_DEFAULTS).toEqual({
      refresh_after_s: homeDefaults.session.refresh_after_s,
      auto_refetch_after_s: homeDefaults.session.auto_refetch_after_s,
    });
    expect(timersFrom()).toEqual({ refreshAfterMs: 600_000, autoRefetchAfterMs: 1_800_000 });
    expect(timersFrom(60, 120)).toEqual({ refreshAfterMs: 60_000, autoRefetchAfterMs: 120_000 });
    expect(timersFrom(-1, Number.NaN)).toEqual(timersFrom());
  });

  it("measures the time away between leave and back, once", () => {
    let now = 0;
    const onPeek = vi.fn();
    const onRefetch = vi.fn();
    const r = createHomeRefresh({ timers: () => T, atTop: () => true, onPeek, onRefetch, now: () => now });
    expect(r.activate()).toBe("none"); // the first activation (mount) is not a return
    r.deactivate();
    now = 31 * MIN;
    expect(r.activate()).toBe("refetch");
    expect(r.activate()).toBe("none");
    r.leave();
    now += 12 * MIN;
    r.leave(); // a second leave keeps the first time
    expect(r.back()).toBe("peek");
    expect([onPeek.mock.calls.length, onRefetch.mock.calls.length]).toEqual([1, 1]);
  });

  it("names the page load's first page load or reload, and every later one nav", () => {
    resetPageEntry();
    expect(pageEntry()).toBe("load");
    expect(pageEntry()).toBe("nav");
    resetPageEntry();
    vi.spyOn(performance, "getEntriesByType").mockReturnValue([{ type: "reload" }] as never);
    expect(pageEntry()).toBe("reload");
    vi.restoreAllMocks();
  });

  it("reads Retry-After in seconds or as a date", () => {
    expect(retryAfterMs("12")).toBe(12_000);
    expect(retryAfterMs("0.5")).toBe(500);
    expect(retryAfterMs(new Date(10_000).toUTCString(), 4_000)).toBe(6_000);
    expect(retryAfterMs(undefined)).toBeNull();
    expect(retryAfterMs("soon")).toBeNull();
  });
});

// ---- Home ---------------------------------------------------------------------------------

const P = (n: number) => ID(100 + n);
const AS_OF = "2026-11-05T10:00:00+00:00";
const firstMeta = { as_of: AS_OF, refresh_after_s: 600, auto_refetch_after_s: 1800, visit: null };

function setVisibility(state: "hidden" | "visible") {
  Object.defineProperty(document, "visibilityState", { value: state, configurable: true });
  document.dispatchEvent(new Event("visibilitychange"));
}

function setScrollY(y: number) {
  Object.defineProperty(window, "scrollY", { value: y, configurable: true, writable: true });
}

const feedIds = (el: HTMLElement) => [...el.querySelectorAll<HTMLElement>("[data-feed-item]")].map((n) => n.dataset.feedItem);
const feedParams = (get: ReturnType<typeof routeApi>["get"]) =>
  get.mock.calls.filter(([u]) => u === "/feed/").map(([, c]) => (c as { params: Record<string, unknown> }).params);

beforeEach(() => {
  setup("en");
  resetPageEntry();
  resetSignals();
  tokenStore.set("x.eyJleHAiOjQxMDI0NDQ4MDB9.y", "refresh");
  setScrollY(0);
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-05T10:00:00Z"));
});
afterEach(() => {
  vi.useRealTimers();
  setVisibility("visible");
  teardown();
  tokenStore.clear();
  resetSignals();
});

describe("Home: first page hints", () => {
  it("sends entry=load and the tab's sid on the page load's first page", async () => {
    const { get } = routeApi({
      feed: () => feedPage([feedItem(P(1))], null, { meta: firstMeta }),
      batch: (ids) => ids.map((id) => livePost(id)),
    });
    await mount(HomeView, "/home?mode=recent");
    const [first] = feedParams(get);
    expect(first).toMatchObject({ entry: "load", mode: "recent" });
    expect(first.sid).toMatch(/^[0-9a-f-]{36}$/);
  });
});

describe("Home: back after time away", () => {
  function api(peekCount = 3) {
    let firstPages = 0;
    return routeApi({
      feed: (p) => {
        if (p.peek) {
          return {
            data: {
              data: [feedItem(P(50)), feedItem(P(51))],
              ids: [P(50), P(51), P(1)],
              new_count: peekCount,
              new_count_capped: false,
              since: AS_OF,
              mode: "recent",
              peek: true,
            },
          };
        }
        firstPages++;
        // The silent refresh brings a new head and one row twice: no duplicate ids.
        const items = firstPages === 1 ? [P(1), P(2), P(3)] : [P(9), P(1), P(9), P(2)];
        return feedPage(items.map((id) => feedItem(id)), null, { meta: firstMeta });
      },
      batch: (ids) => ids.map((id) => livePost(id)),
    });
  }

  it("under 10 minutes: nothing", async () => {
    const { get } = api();
    const el = await mount(HomeView, "/home?mode=recent");
    setVisibility("hidden");
    vi.setSystemTime(Date.now() + 9 * MIN);
    setVisibility("visible");
    await flush();
    expect(feedParams(get)).toHaveLength(1);
    expect(el.querySelector('[data-testid="new-posts-pill"]')).toBeNull();
  });

  it("after 10 minutes while scrolled: the pill with the server's count; list and scroll unchanged", async () => {
    const { get } = api(3);
    const el = await mount(HomeView, "/home?mode=recent");
    const scroll = vi.fn();
    vi.stubGlobal("scrollTo", scroll);
    setScrollY(900);
    const before = feedIds(el);
    setVisibility("hidden");
    vi.setSystemTime(Date.now() + 11 * MIN);
    setVisibility("visible");
    await flush();
    const peek = feedParams(get).find((p) => p.peek);
    expect(peek).toMatchObject({ peek: 1, since: AS_OF, mode: "recent" });
    // 3 new per the server, one of which (P(1)) is already in the list.
    const pill = el.querySelector<HTMLElement>('[data-testid="new-posts-pill"] button')!;
    expect(pill.dataset.count).toBe("2");
    expect(pill.textContent).toContain("2 new posts");
    expect(feedIds(el)).toEqual(before);
    expect(scroll).not.toHaveBeenCalled();
    expect(window.scrollY).toBe(900);
    expect(feedParams(get).filter((p) => !p.peek)).toHaveLength(1); // no first page
  });

  it("after 30 minutes at the top: a silent first page with entry=return replaces the list, no duplicates", async () => {
    const { get } = api();
    const el = await mount(HomeView, "/home?mode=recent");
    expect(feedIds(el)).toEqual([P(1), P(2), P(3)]);
    setVisibility("hidden");
    vi.setSystemTime(Date.now() + 31 * MIN);
    setVisibility("visible");
    await flush(20);
    const firsts = feedParams(get).filter((p) => !p.peek);
    expect(firsts[1]).toMatchObject({ entry: "return", mode: "recent" });
    expect(feedIds(el)).toEqual([P(9), P(1), P(2)]);
    expect(el.querySelector('[data-testid="feed-first-loading"]')).toBeNull(); // silent
  });

  it("the same on KeepAlive activation (back to Home from another route)", async () => {
    const { get } = api();
    const show = ref(true);
    const Other = defineComponent({ name: "Other", render: () => h("div", "other") });
    const Shell = defineComponent({ render: () => h(KeepAlive, null, [show.value ? h(HomeView) : h(Other)]) });
    const el = await mount(Shell, "/home?mode=recent");
    show.value = false;
    await flush();
    vi.setSystemTime(Date.now() + 40 * MIN);
    show.value = true;
    await flush(20);
    expect(feedParams(get).filter((p) => !p.peek)[1]).toMatchObject({ entry: "return" });
    expect(feedIds(el)).toEqual([P(9), P(1), P(2)]);
  });
});

describe("Home: 429 on a first page", () => {
  it("shows the retry card, tries once more after Retry-After, then waits for a click", async () => {
    vi.useRealTimers();
    let calls = 0;
    const refused = () => {
      calls++;
      throw Object.assign(new Error("429"), { response: { status: 429, headers: { "retry-after": "0.4" } } });
    };
    routeApi({ feed: refused, batch: (ids) => ids.map((id) => livePost(id)) });
    const el = await mount(HomeView, "/home?mode=recent");
    expect(el.querySelector('[data-testid="feed-retry"]')).not.toBeNull();
    expect(calls).toBe(1);
    await new Promise((r) => setTimeout(r, 500));
    await flush();
    expect(calls).toBe(2); // one automatic try after Retry-After
    await new Promise((r) => setTimeout(r, 600));
    await flush();
    expect(calls).toBe(2); // never a loop
    expect(el.querySelector('[data-testid="feed-retry-button"]')?.hasAttribute("disabled")).toBe(false);
  });
});

describe("Home: a ranked session continued chronologically", () => {
  it("drops known ids and asks one more page when fewer than 5 new remain", async () => {
    const pages: Record<string, ReturnType<typeof feedPage>> = {
      "": feedPage([1, 2, 3, 4, 5].map((n) => feedItem(P(n))), "c1", { meta: firstMeta, mode: "for_you" }),
      // fallback: 3 of 5 already shown
      c1: feedPage([3, 4, 5, 6, 7].map((n) => feedItem(P(n))), "c2", { mode: "for_you" }),
      c2: feedPage([8, 9].map((n) => feedItem(P(n))), null, { mode: "for_you" }),
    };
    pages.c1.data.page = { ...pages.c1.data.page, fallback: true } as never;
    const { get } = routeApi({ feed: (p) => pages[(p.cursor as string) ?? ""], batch: (ids) => ids.map((id) => livePost(id)) });
    const el = await mount(HomeView, "/home?mode=for_you");
    el.querySelector<HTMLButtonElement>('[data-testid="feed-more"] button')!.click();
    await flush(20);
    expect(feedParams(get).map((p) => p.cursor ?? "")).toEqual(["", "c1", "c2"]);
    const ids = feedIds(el);
    expect(ids).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9].map(P));
    expect(new Set(ids).size).toBe(ids.length);
  });
});
