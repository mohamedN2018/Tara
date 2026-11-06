// WP 4c.9-B3 on the web (08 §7.12): impression rule v2. A card counts when at
// least `min_card_visible` of it OR `min_viewport_cover` of the viewport is
// covered, for `min_ms` in a visible tab, once per (session, item), stamped
// `idef`. Unknown server rule: legacy v1 with idef 1. Never on fetch, render or
// prefetch: only visibility.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, createApp, defineComponent, h, ref } from "vue";

import { applyDelivery, resetDelivery, SAFE_DEFAULTS } from "@/lib/delivery";
import { pendingSignals, resetSignals } from "@/lib/signals";
import { tokenStore } from "@/lib/tokens";
import { impressionRule, meetsRule, useImpression } from "@/lib/useImpression";

const ID = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;

function jwt(expSeconds: number): string {
  const b64 = (o: object) => btoa(JSON.stringify(o)).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `${b64({ alg: "none" })}.${b64({ sub: ID(999), exp: expSeconds })}.sig`;
}

class IO {
  static all: IO[] = [];
  options: IntersectionObserverInit;
  constructor(
    public cb: IntersectionObserverCallback,
    options: IntersectionObserverInit = {},
  ) {
    this.options = options;
    IO.all.push(this);
  }
  observe() {}
  unobserve() {}
  disconnect() {}
  report(e: Partial<IntersectionObserverEntry>) {
    this.cb([{ isIntersecting: true, intersectionRatio: 0, intersectionRect: { height: 0 }, rootBounds: { height: 800 }, ...e } as never], this as never);
  }
}

let apps: App[] = [];
function mountCards(n: number) {
  for (let i = 0; i < n; i++) {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const app = createApp(
      defineComponent({
        setup() {
          const el = ref<HTMLElement | null>(null);
          useImpression(el, () => ({ item: `post:${ID(i + 1)}`, surface: "home" }));
          return () => h("article", { ref: el });
        },
      }),
    );
    app.mount(host);
    apps.push(app);
  }
}

beforeEach(() => {
  resetSignals();
  resetDelivery();
  IO.all = [];
  tokenStore.set(jwt(Math.floor(Date.now() / 1000) + 3600), "refresh");
  vi.stubGlobal("IntersectionObserver", IO);
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 202 }) as Response));
});
afterEach(() => {
  apps.forEach((a) => a.unmount());
  apps = [];
  resetSignals();
  resetDelivery();
  tokenStore.clear();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const impressions = () => pendingSignals().filter((e) => e.t === "feed_impression");

describe("the rule", () => {
  it("v1 while the server's rule is unknown: half the card, never the viewport branch", () => {
    const rule = impressionRule("home");
    expect(rule).toEqual({ cardRatio: 0.5, viewportCover: 0, ms: 1000, version: 1 });
    const tall = { isIntersecting: true, intersectionRatio: 0.3, intersectionRect: { height: 700 }, rootBounds: { height: 800 } } as never;
    expect(meetsRule(tall, rule)).toBe(false);
  });

  it("v2 from the server: a card taller than two viewports counts by covering the viewport", () => {
    applyDelivery("home", SAFE_DEFAULTS.home);
    const rule = impressionRule("home");
    expect(rule).toEqual({ cardRatio: 0.5, viewportCover: 0.5, ms: 1000, version: 2 });
    // A 2,000 px card in an 800 px viewport: at most 40 % of it is ever visible.
    const tall = { isIntersecting: true, intersectionRatio: 0.4, intersectionRect: { height: 800 }, rootBounds: { height: 800 } } as never;
    expect(meetsRule(tall, rule)).toBe(true);
    const sliver = { isIntersecting: true, intersectionRatio: 0.1, intersectionRect: { height: 200 }, rootBounds: { height: 800 } } as never;
    expect(meetsRule(sliver, rule)).toBe(false);
  });
});

describe("useImpression", () => {
  it("sends nothing for 10 fetched cards that are mounted but never on screen", async () => {
    vi.useFakeTimers();
    applyDelivery("home", SAFE_DEFAULTS.home);
    mountCards(10);
    await vi.advanceTimersByTimeAsync(5000);
    expect(impressions()).toHaveLength(0);
  });

  it("counts a tall card after min_ms of covering the viewport, once, with idef = def_version", async () => {
    vi.useFakeTimers();
    applyDelivery("home", { ...SAFE_DEFAULTS.home, impression: { ...SAFE_DEFAULTS.home.impression, def_version: 2 } });
    mountCards(1);
    await vi.advanceTimersByTimeAsync(0);
    const io = IO.all.at(-1)!;
    expect((io.options.threshold as number[]).length).toBeGreaterThan(3); // tall cards report while scrolling
    io.report({ intersectionRatio: 0.35, intersectionRect: { height: 640 } as DOMRectReadOnly });
    await vi.advanceTimersByTimeAsync(999);
    expect(impressions()).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1);
    expect(impressions()).toHaveLength(1);
    expect(impressions()[0]).toMatchObject({ t: "feed_impression", item: `post:${ID(1)}`, idef: 2 });
    io.report({ intersectionRatio: 1, intersectionRect: { height: 640 } as DOMRectReadOnly });
    await vi.advanceTimersByTimeAsync(2000);
    expect(impressions()).toHaveLength(1);
  });

  it("stamps idef 1 under the legacy rule (server rule unknown)", async () => {
    vi.useFakeTimers();
    mountCards(1);
    await vi.advanceTimersByTimeAsync(0);
    IO.all.at(-1)!.report({ intersectionRatio: 0.6, intersectionRect: { height: 300 } as DOMRectReadOnly });
    await vi.advanceTimersByTimeAsync(1000);
    expect(impressions()[0]).toMatchObject({ idef: 1 });
  });
});
