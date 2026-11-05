import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, createApp, h, nextTick } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import { createTapDetector, indexFromScroll, isMounted, MAX_MOUNTED, mountedRange, reelsMuted } from "@/components/reels/pager";
import ReelPager from "@/components/reels/ReelPager.vue";
import ReelsRail from "@/components/reels/ReelsRail.vue";
import { i18n } from "@/i18n";
import { api } from "@/lib/api";
import type { Reel } from "@/services/reels";

// Reels (5.8): the snap pager keeps at most three players mounted, starts muted,
// tells a tap (pause) from a double tap (like), and the home rail only shows
// when real reels exist.

vi.mock("hls.js", () => {
  class FakeHls {
    static Events = { ERROR: "hlsError" };
    static ErrorTypes = { MEDIA_ERROR: "mediaError" };
    static isSupported = () => true;
    loadSource() {}
    attachMedia() {}
    on() {}
    recoverMediaError() {}
    destroy() {}
  }
  return { default: FakeHls };
});

function reel(i: number, over: Partial<Reel> = {}): Reel {
  return {
    id: `0000000${i}-0000-7000-8000-000000000000`,
    author_id: `1000000${i}-0000-7000-8000-000000000000`,
    author_type: "user",
    type: "reel",
    body: `caption ${i}`,
    audience: "public",
    media_ids: [`2000000${i}-0000-7000-8000-000000000000`],
    reaction_count: 0,
    comment_count: 0,
    share_count: 0,
    my_reaction: null,
    created_at: "2026-11-05T10:00:00Z",
    reel: {
      media_id: `2000000${i}-0000-7000-8000-000000000000`,
      cover_media_id: null,
      duration_ms: 15000,
      width: 720,
      height: 1280,
      view_count: 1200 + i,
      viewed_today: false,
    },
    ...over,
  } as Reel;
}

const playback = {
  data: {
    data: { id: "x", status: "ready", failure_code: null, duration_ms: 15000, width: 720, height: 1280, hls_url: "media/x/hls/master.m3u8?token=t", mp4_url: null, poster_url: null, expires_in: 3600 },
  },
};

let app: App | null = null;
let host: HTMLElement | null = null;

async function flush() {
  for (let i = 0; i < 8; i++) await new Promise((r) => setTimeout(r, 0));
}

async function mount(component: unknown, props: Record<string, unknown> = {}) {
  host = document.createElement("div");
  document.body.appendChild(host);
  const pinia = createPinia();
  setActivePinia(pinia);
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/u/id/:id", name: "profile-by-id", component: { template: "<div/>" } },
      { path: "/pages/id/:id", name: "page-by-id", component: { template: "<div/>" } },
      { path: "/reels/:id", name: "reel", component: { template: "<div/>" } },
      { path: "/:p(.*)*", component: { template: "<div/>" } },
    ],
  });
  app = createApp({ render: () => h(component as never, props) });
  app.use(pinia).use(router).use(i18n);
  app.mount(host);
  await flush();
  return host;
}

const all = (sel: string) => Array.from(host!.querySelectorAll<HTMLElement>(sel));

beforeEach(() => {
  i18n.global.locale.value = "ar";
  reelsMuted.value = true;
  // Name lookups (directory) go nowhere in these tests.
  vi.spyOn(api, "post").mockResolvedValue({ data: { data: [] } });
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(function (this: HTMLMediaElement) {
    this.dispatchEvent(new Event("play"));
    return Promise.resolve();
  });
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(function (this: HTMLMediaElement) {
    this.dispatchEvent(new Event("pause"));
  });
  // The pager scrolls with scrollTo; jsdom has none.
  Element.prototype.scrollTo = function scrollTo(this: Element, opts?: ScrollToOptions | number) {
    if (typeof opts === "object" && opts.top !== undefined) (this as HTMLElement).scrollTop = opts.top;
  } as typeof Element.prototype.scrollTo;
});

afterEach(() => {
  app?.unmount();
  host?.remove();
  app = null;
  host = null;
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("pager helpers", () => {
  it("mounts the active reel and one neighbour each side, never more than three", () => {
    expect(MAX_MOUNTED).toBe(3);
    expect(mountedRange(0, 10)).toEqual({ start: 0, end: 2 });
    expect(mountedRange(5, 10)).toEqual({ start: 4, end: 6 });
    expect(mountedRange(9, 10)).toEqual({ start: 7, end: 9 });
    expect(mountedRange(0, 1)).toEqual({ start: 0, end: 0 });
    expect(mountedRange(1, 2)).toEqual({ start: 0, end: 1 });
    expect(mountedRange(3, 0)).toEqual({ start: 0, end: -1 });
    for (let active = 0; active < 10; active++) {
      const mounted = Array.from({ length: 10 }, (_, i) => i).filter((i) => isMounted(i, active, 10));
      expect(mounted.length).toBeLessThanOrEqual(3);
      expect(mounted).toContain(active);
    }
  });

  it("reads the slide on screen from the scroll position", () => {
    expect(indexFromScroll(0, 800, 5)).toBe(0);
    expect(indexFromScroll(790, 800, 5)).toBe(1);
    expect(indexFromScroll(1150, 800, 5)).toBe(1);
    expect(indexFromScroll(99999, 800, 5)).toBe(4);
    expect(indexFromScroll(100, 0, 5)).toBe(0);
  });

  it("tells a tap from a double tap", () => {
    vi.useFakeTimers();
    const single = vi.fn();
    const double = vi.fn();
    const tap = createTapDetector(single, double, 250);
    tap();
    vi.advanceTimersByTime(300);
    expect(single).toHaveBeenCalledTimes(1);
    tap();
    tap();
    vi.advanceTimersByTime(300);
    expect(double).toHaveBeenCalledTimes(1);
    expect(single).toHaveBeenCalledTimes(1);
  });
});

describe("ReelPager", () => {
  it("keeps at most three players mounted as the viewer moves, and autoplays muted", async () => {
    vi.spyOn(api, "get").mockResolvedValue(playback);
    const reels = Array.from({ length: 6 }, (_, i) => reel(i));
    const active: number[] = [];
    await mount(ReelPager, { reels, onActive: (i: number) => active.push(i) });
    expect(all("[data-testid=reel-slide]")).toHaveLength(6);
    expect(all("[data-testid=reel-player]")).toHaveLength(3);
    const video = host!.querySelector<HTMLVideoElement>("[data-testid=reel-video]")!;
    expect(video.muted).toBe(true);
    expect(video.hasAttribute("loop")).toBe(true);

    // Next reel (the desktop button): the window moves with it.
    for (let i = 0; i < 4; i++) {
      host!.querySelector<HTMLButtonElement>("[data-testid=reel-next]")!.click();
      await flush();
    }
    expect(host!.querySelector("[data-testid=reel-pager]")!.getAttribute("data-active")).toBe("4");
    const mounted = all("[data-testid=reel-slide]")
      .filter((s) => s.querySelector("[data-testid=reel-player]"))
      .map((s) => s.dataset.reelId);
    expect(mounted).toEqual([reels[3].id, reels[4].id, reels[5].id]);
    expect(active.at(-1)).toBe(4);
    expect(all("[data-testid=reel-slide]")[4].getAttribute("aria-current")).toBe("true");
  });

  it("likes on a double tap only, and pauses on a single tap", async () => {
    vi.spyOn(api, "get").mockResolvedValue(playback);
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const likes: string[] = [];
    const reels = [reel(1), reel(2)];
    await mount(ReelPager, { reels, onLike: (r: Reel) => likes.push(r.id) });
    const tapArea = host!.querySelector<HTMLButtonElement>("[data-testid=reel-tap]")!;
    tapArea.click();
    tapArea.click();
    await nextTick();
    expect(likes).toEqual([reels[0].id]);
    expect(host!.querySelector("[data-testid=reel-heart]")).not.toBeNull();

    const pause = vi.mocked(HTMLMediaElement.prototype.pause);
    pause.mockClear();
    vi.spyOn(HTMLMediaElement.prototype, "paused", "get").mockReturnValue(false); // it is playing
    tapArea.click();
    vi.advanceTimersByTime(400);
    await flush();
    expect(likes).toHaveLength(1);
    expect(pause).toHaveBeenCalled();
  });

  it("shows counts in the viewer's language and the action rail on the end side", async () => {
    vi.spyOn(api, "get").mockResolvedValue(playback);
    await mount(ReelPager, { reels: [reel(1, { reaction_count: 3, my_reaction: "like" })] });
    // Compact, in the viewer's language ("1.2 ألف"), with the Arabic plural.
    expect(host!.querySelector("[data-testid=reel-views]")!.textContent).toContain("ألف");
    i18n.global.locale.value = "en";
    await nextTick();
    expect(host!.querySelector("[data-testid=reel-views]")!.textContent).toBe("1.2K views");
    const like = host!.querySelector<HTMLButtonElement>("[data-testid=reel-like]")!;
    expect(like.getAttribute("aria-pressed")).toBe("true");
    // Logical properties: the rail sits at the inline end (left in Arabic).
    expect(host!.querySelector("[data-testid=reel-actions]")!.className).toContain("end-2");
    expect(host!.querySelector("[data-testid=reel-caption]")!.getAttribute("dir")).toBe("auto");
  });
});

describe("ReelsRail", () => {
  it("renders nothing without reels", async () => {
    vi.spyOn(api, "get").mockResolvedValue({ data: { data: [], page: { next_cursor: null, prev_cursor: null, has_more: false } } });
    await mount(ReelsRail);
    expect(host!.querySelector("[data-testid=reels-rail]")).toBeNull();
  });

  it("lists real reels that open the pager", async () => {
    const reels = [reel(1), reel(2)];
    vi.spyOn(api, "get").mockImplementation(async (url: string) => {
      if (url === "/reels/") return { data: { data: reels, page: { next_cursor: null, prev_cursor: null, has_more: false } } };
      return playback;
    });
    await mount(ReelsRail);
    const items = all("[data-testid=reels-rail-item]");
    expect(items).toHaveLength(2);
    expect(items[0].getAttribute("href")).toBe(`/reels/${reels[0].id}`);
  });
});
