// Tara Intelligence WP 2.8: the web tracker (lib/signals.ts), the watch-time
// session (lib/videoSignals.ts) and impressions (lib/useImpression.ts).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, createApp, defineComponent, h, nextTick, ref } from "vue";

import {
  flush,
  noteServed,
  pendingSignals,
  resetSignals,
  setPersonalizationOff,
  SIGNAL_LIMITS,
  surfaceForRoute,
  track,
} from "@/lib/signals";
import { tokenStore } from "@/lib/tokens";
import { IMPRESSION_RULES, useImpression } from "@/lib/useImpression";
import { WatchSession } from "@/lib/videoSignals";

const ID = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const POST = (n: number) => `post:${ID(n)}`;

function jwt(expSeconds: number): string {
  const b64 = (o: object) => btoa(JSON.stringify(o)).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `${b64({ alg: "none" })}.${b64({ sub: ID(999), exp: expSeconds })}.sig`;
}

type Sent = { url: string; init: RequestInit; body: { batch_id: string; session_id: string; events: Record<string, unknown>[] } };
let sent: Sent[];
let status: number | "network";

beforeEach(() => {
  resetSignals();
  sent = [];
  status = 202;
  tokenStore.set(jwt(Math.floor(Date.now() / 1000) + 3600), "refresh");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      sent.push({ url, init, body: JSON.parse(String(init.body)) });
      if (status === "network") throw new TypeError("offline");
      return { ok: status >= 200 && status < 300, status } as Response;
    }),
  );
});

afterEach(() => {
  resetSignals();
  tokenStore.clear();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("signals tracker", () => {
  it("batches to /feed/signals/ with a bearer token, and flushes every 10 s", async () => {
    vi.useFakeTimers();
    track({ t: "post_open", item: POST(1), surface: "profile" });
    track({ t: "post_open", item: POST(2), surface: "profile" });
    expect(sent).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(SIGNAL_LIMITS.flushMs);
    expect(sent).toHaveLength(1);
    expect(sent[0].url).toMatch(/\/feed\/signals\/$/);
    expect((sent[0].init.headers as Record<string, string>).Authorization).toMatch(/^Bearer /);
    expect(sent[0].init.keepalive).toBe(false);
    expect(sent[0].body.events.map((e) => e.item)).toEqual([POST(1), POST(2)]);
    expect(sent[0].body.batch_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(sent[0].body.session_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(pendingSignals()).toHaveLength(0);
  });

  it("flushes at 30 queued events and never sends more than 50 in a batch", async () => {
    for (let i = 0; i < SIGNAL_LIMITS.flushAt - 1; i++) track({ t: "post_open", item: POST(i), surface: "search" });
    expect(sent).toHaveLength(0);
    track({ t: "post_open", item: POST(500), surface: "search" });
    await vi.waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0].body.events).toHaveLength(SIGNAL_LIMITS.flushAt);

    for (let i = 0; i < 120; i++) track({ t: "video_start", item: `video:${ID(2000 + i)}`, play_index: 1 });
    await vi.waitFor(async () => {
      await flush();
      expect(pendingSignals()).toHaveLength(0);
    });
    expect(sent.every((s) => s.body.events.length <= SIGNAL_LIMITS.maxBatch)).toBe(true);
    expect(sent.reduce((n, s) => n + s.body.events.length, 0)).toBe(150);
  });

  it("keeps at most 200 events in memory, dropping the oldest", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {}))); // a send that never ends
    for (let i = 0; i < 400; i++) track({ t: "video_start", item: `video:${ID(i)}`, play_index: 1 });
    const pending = pendingSignals();
    expect(pending).toHaveLength(SIGNAL_LIMITS.maxQueue);
    expect(pending.at(-1)?.item).toBe(`video:${ID(399)}`);
    expect(pending[0].item).toBe(`video:${ID(200)}`);
  });

  it("uses keepalive when the tab is hidden", async () => {
    track({ t: "post_open", item: POST(1), surface: "link" });
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0].init.keepalive).toBe(true);
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
  });

  it("dedupes impressions and opens per session, and profile visits per day", async () => {
    expect(track({ t: "feed_impression", item: POST(1), surface: "home", pos: 0 })).toBe(true);
    expect(track({ t: "feed_impression", item: POST(1), surface: "home", pos: 0 })).toBe(false);
    expect(track({ t: "post_open", item: POST(1), surface: "home" })).toBe(true);
    expect(track({ t: "post_open", item: POST(1), surface: "home" })).toBe(false);
    expect(track({ t: "profile_visit", item: `profile:${ID(7)}`, surface: "profile" })).toBe(true);
    expect(track({ t: "profile_visit", item: `profile:${ID(7)}`, surface: "profile" })).toBe(false);
    expect(pendingSignals()).toHaveLength(3);
  });

  it("sends video progress at most once per 5 s per item", () => {
    vi.useFakeTimers();
    const item = `video:${ID(3)}`;
    expect(track({ t: "video_progress", item, watch_ms: 5000, pos_ms: 5000 })).toBe(true);
    vi.advanceTimersByTime(2000);
    expect(track({ t: "video_progress", item, watch_ms: 7000, pos_ms: 7000 })).toBe(false);
    vi.advanceTimersByTime(3000);
    expect(track({ t: "video_progress", item, watch_ms: 10000, pos_ms: 10000 })).toBe(true);
  });

  it("passes the serve token through, and never cfg, variant or other fields", () => {
    noteServed(POST(1), { st: "tok-1", pos: 4, surface: "home" });
    track({
      t: "feed_impression",
      item: POST(1),
      surface: "home",
      ...({ cfg: "home@9", variant: "b", email: "x@example.com" } as object),
    } as Parameters<typeof track>[0]);
    track({ t: "video_start", item: `video:${ID(1)}`, play_index: 1, surface: "home" });
    track({ t: "post_open", item: POST(2), surface: "profile" });
    const [impression, start, open] = pendingSignals();
    expect(impression).toMatchObject({ t: "feed_impression", st: "tok-1", pos: 4 });
    expect(Object.keys(impression).sort()).toEqual(["id", "item", "pos", "st", "t", "ts"]);
    expect(impression).not.toHaveProperty("surface"); // attributed by the token
    expect(start).toMatchObject({ st: "tok-1", play_index: 1 }); // the post's token covers its video
    expect(start).not.toHaveProperty("pos");
    expect(open).toMatchObject({ surface: "profile" });
    expect(open).not.toHaveProperty("st");
    for (const e of pendingSignals()) {
      expect(e).not.toHaveProperty("cfg");
      expect(e).not.toHaveProperty("variant");
      expect(JSON.stringify(e)).not.toContain("example.com");
    }
  });

  it("refuses server-only event types and malformed items", () => {
    for (const t of ["post_like", "post_save", "post_hide", "follow", "interested"]) {
      expect(track({ t: t as never, item: POST(1) })).toBe(false);
    }
    expect(track({ t: "post_open", item: "post:not-a-uuid" })).toBe(false);
    expect(track({ t: "post_open", item: `user:${ID(1)}` })).toBe(false);
    expect(pendingSignals()).toHaveLength(0);
  });

  it("is silent with personalization off: nothing queued, zero requests", async () => {
    vi.useFakeTimers();
    track({ t: "post_open", item: POST(1), surface: "home" });
    setPersonalizationOff(true);
    expect(pendingSignals()).toHaveLength(0);
    expect(track({ t: "feed_impression", item: POST(2), surface: "home", pos: 1 })).toBe(false);
    await flush();
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(SIGNAL_LIMITS.flushMs * 3);
    expect(sent).toHaveLength(0);
  });

  it("sends nothing for a signed-out visitor", async () => {
    tokenStore.clear();
    expect(track({ t: "post_open", item: POST(1), surface: "link" })).toBe(false);
    await flush();
    expect(sent).toHaveLength(0);
  });

  it("retries a failed batch with the same batch id, and stops after a 404", async () => {
    status = 503;
    track({ t: "post_open", item: POST(1), surface: "link" });
    await flush();
    status = 202;
    await flush();
    expect(sent).toHaveLength(2);
    expect(sent[1].body.batch_id).toBe(sent[0].body.batch_id);

    status = 404; // a server without the signals endpoint
    track({ t: "post_open", item: POST(2), surface: "link" });
    await flush();
    const after404 = sent.length;
    expect(track({ t: "post_open", item: POST(3), surface: "link" })).toBe(false);
    await flush();
    expect(sent).toHaveLength(after404);
  });

  it("drops a batch the server refuses as invalid", async () => {
    status = 400;
    track({ t: "post_open", item: POST(1), surface: "link" });
    await flush();
    status = 202;
    await flush();
    expect(sent).toHaveLength(1);
  });

  it("maps routes to surfaces", () => {
    expect(surfaceForRoute("home")).toBe("home");
    expect(surfaceForRoute("reel")).toBe("reels");
    expect(surfaceForRoute("videos")).toBe("video");
    expect(surfaceForRoute("group")).toBe("groups");
    expect(surfaceForRoute("page")).toBe("profile");
    expect(surfaceForRoute("search")).toBe("search");
    expect(surfaceForRoute("post")).toBe("link");
    expect(surfaceForRoute(undefined)).toBe("link");
  });
});

describe("WatchSession", () => {
  const item = `video:${ID(42)}`;
  const types = () => pendingSignals().map((e) => e.t);
  const play = (s: WatchSession, from: number, to: number, duration: number) => {
    for (let t = from; t <= to + 1e-9; t += 0.25) s.time(Math.round(t * 100) / 100, duration);
  };

  it("counts only real playback: seeks and jumps add nothing", () => {
    const s = new WatchSession({ item, surface: "video" });
    s.playing(0);
    play(s, 0, 4, 60);
    expect(s.watchMs).toBe(4000);
    s.time(40, 60); // a seek forward
    s.seeked(40);
    play(s, 40, 41, 60);
    expect(s.watchMs).toBe(5000);
    expect(types()).toEqual(["video_start", "video_progress"]);
    expect(pendingSignals()[1]).toMatchObject({ watch_ms: 5000 });
  });

  it("completes at 90% of the duration, once per play, then counts a rewatch on a loop", () => {
    const s = new WatchSession({ item, surface: "reels" });
    s.playing(0);
    play(s, 0, 9.5, 10);
    expect(types()).toContain("video_complete");
    s.time(0.1, 10); // the loop restarts
    expect(s.play).toBe(2);
    const t = types();
    expect(t.filter((x) => x === "video_complete")).toHaveLength(1);
    expect(t.slice(-2)).toEqual(["video_start", "video_rewatch"]);
    expect(pendingSignals().at(-1)).toMatchObject({ play_index: 2 });
  });

  it("an early exit is a skip; a longer watch is not", () => {
    const quick = new WatchSession({ item, surface: "video" });
    quick.playing(0);
    play(quick, 0, 1, 60);
    quick.left(60);
    quick.left(60);
    expect(types().filter((x) => x === "video_skip")).toHaveLength(1);

    resetSignals();
    tokenStore.set(jwt(Math.floor(Date.now() / 1000) + 3600), "refresh");
    const watched = new WatchSession({ item: `video:${ID(43)}`, surface: "video" });
    watched.playing(0);
    play(watched, 0, 3, 60);
    watched.left(60);
    expect(types()).not.toContain("video_skip");
  });

  it("a reel is viewed after 1 s of play, once, with the watch time", () => {
    const onReelView = vi.fn();
    const s = new WatchSession({ item: `reel:${ID(5)}`, surface: "reels", onReelView });
    s.playing(0);
    s.time(0.5, 15);
    expect(onReelView).not.toHaveBeenCalled();
    play(s, 0.5, 3, 15);
    expect(onReelView).toHaveBeenCalledTimes(1);
    expect(onReelView.mock.calls[0][0]).toBeGreaterThanOrEqual(1000);
    expect(types().filter((x) => x === "reel_view")).toHaveLength(1);
  });
});

describe("useImpression", () => {
  type Observer = { cb: IntersectionObserverCallback; node: Element | null; disconnected: boolean };
  let observers: Observer[];

  beforeEach(() => {
    observers = [];
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        o: Observer;
        constructor(cb: IntersectionObserverCallback) {
          this.o = { cb, node: null, disconnected: false };
          observers.push(this.o);
        }
        observe(node: Element) {
          this.o.node = node;
        }
        disconnect() {
          this.o.disconnected = true;
        }
      },
    );
  });

  const Card = defineComponent({
    props: { id: { type: String, required: true } },
    setup(props) {
      const el = ref<HTMLElement | null>(null);
      useImpression(el, () => ({ item: `post:${props.id}`, surface: "home", pos: 2 }));
      return () => h("div", { ref: el });
    },
  });

  const apps: App[] = [];
  afterEach(() => apps.splice(0).forEach((a) => a.unmount()));
  function mount(component: typeof Card, { props }: { props: { id: string } }) {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const app = createApp({ render: () => h(component, props) });
    app.mount(host);
    apps.push(app);
  }

  const show = (ratio: number) => {
    const o = observers.at(-1)!;
    o.cb([{ isIntersecting: ratio > 0, intersectionRatio: ratio } as IntersectionObserverEntry], {} as IntersectionObserver);
  };

  it("needs half the card on screen for a full second", async () => {
    vi.useFakeTimers();
    mount(Card, { props: { id: ID(1) } });
    await nextTick();
    show(0.4);
    vi.advanceTimersByTime(5000);
    expect(pendingSignals()).toHaveLength(0);
    show(0.6);
    vi.advanceTimersByTime(IMPRESSION_RULES.visibleMs - 200);
    show(0); // scrolled away early
    vi.advanceTimersByTime(5000);
    expect(pendingSignals()).toHaveLength(0);
    show(0.8); // back: the time adds up
    vi.advanceTimersByTime(250);
    expect(pendingSignals()).toHaveLength(1);
    expect(pendingSignals()[0]).toMatchObject({ t: "feed_impression", item: `post:${ID(1)}`, pos: 2 });
    show(0.8);
    vi.advanceTimersByTime(5000);
    expect(pendingSignals()).toHaveLength(1);
  });

  it("one impression per (session, item) even across two cards", async () => {
    vi.useFakeTimers();
    mount(Card, { props: { id: ID(9) } });
    mount(Card, { props: { id: ID(9) } });
    await nextTick();
    for (const o of observers) {
      o.cb([{ isIntersecting: true, intersectionRatio: 1 } as IntersectionObserverEntry], {} as IntersectionObserver);
    }
    vi.advanceTimersByTime(2000);
    expect(pendingSignals()).toHaveLength(1);
  });

  it("sends nothing without IntersectionObserver", async () => {
    vi.stubGlobal("IntersectionObserver", undefined);
    vi.useFakeTimers();
    mount(Card, { props: { id: ID(2) } });
    await nextTick();
    vi.advanceTimersByTime(5000);
    expect(pendingSignals()).toHaveLength(0);
  });
});
