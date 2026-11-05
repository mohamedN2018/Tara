import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, createApp, defineComponent, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import TrendingList from "@/components/search/TrendingList.vue";
import { i18n, setLocale } from "@/i18n";
import { api } from "@/lib/api";
import type { TrendingTag } from "@/services/search";

// Tara Intelligence 4b.20-B3 (web): the server sends only `posts_floor`; a null
// floor shows no count, a floor shows "20+ posts in the last 24 h" (1K, 5K, 10K
// for the big ones), and the window is always named, never "today".

const Blank = defineComponent({ render: () => null });
let app: App | null = null;
let host: HTMLElement | null = null;

async function flush() {
  for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0));
}

function serve(byWindow: Record<"day" | "week", TrendingTag[]>) {
  return vi.spyOn(api, "get").mockImplementation(async (_url: string, config?: { params?: { window?: "day" | "week" } }) => {
    const w = config?.params?.window ?? "week";
    return { data: { data: byWindow[w] } };
  });
}

async function mount(props: Record<string, unknown> = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/search", name: "search", component: Blank },
      { path: "/:rest(.*)*", component: Blank },
    ],
  });
  await router.push("/search");
  await router.isReady();
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp({ render: () => h(TrendingList, props) });
  app.use(createPinia()).use(router).use(i18n);
  app.mount(host);
  await flush();
  return host;
}

const rows = (el: ParentNode) => [...el.querySelectorAll("li")];
const counts = (el: ParentNode) => [...el.querySelectorAll('[data-testid="trending-count"]')].map((n) => n.textContent?.trim());
const toggles = (el: ParentNode) => [...el.querySelectorAll<HTMLButtonElement>('[role="group"] button')];

const WEEK: TrendingTag[] = [
  { tag: "nile", posts_floor: null, window: "week" },
  { tag: "cairo", posts_floor: 20, window: "week" },
  { tag: "قهوة", posts_floor: 1000, window: "week" },
  { tag: "big", posts_floor: 10000, window: "week" },
  { tag: "mid", posts_floor: 5000, window: "week" },
  { tag: "half", posts_floor: 500, window: "week" },
];
const DAY: TrendingTag[] = [{ tag: "today", posts_floor: 50, window: "day" }];

beforeEach(() => {
  setActivePinia(createPinia());
  setLocale("en");
});

afterEach(() => {
  app?.unmount();
  host?.remove();
  app = null;
  host = null;
  vi.restoreAllMocks();
  setLocale("en");
});

describe("Trending list honesty (4b.20-B3)", () => {
  it("shows no count when the floor is null, and bucketed floors otherwise (en)", async () => {
    serve({ day: DAY, week: WEEK });
    const el = await mount();
    const items = rows(el);
    expect(items).toHaveLength(6);
    expect(items[0].querySelector('[data-testid="trending-count"]')).toBeNull();
    expect(counts(el)).toEqual([
      "20+ posts in the last 7 days",
      "1K+ posts in the last 7 days",
      "10K+ posts in the last 7 days",
      "5K+ posts in the last 7 days",
      "500+ posts in the last 7 days",
    ]);
    // Never a number below 20, never a raw count, never a percentage.
    for (const text of counts(el)) {
      expect(text).not.toMatch(/%/);
      expect(text).toMatch(/^(20|50|100|500|1K|5K|10K)\+/);
    }
    expect(el.textContent).not.toMatch(/today/i);
  });

  it("names the 24 h window and renames the toggles", async () => {
    serve({ day: DAY, week: WEEK });
    const el = await mount();
    expect(toggles(el).map((b) => b.textContent?.trim())).toEqual(["Last 24 h", "Last 7 days"]);
    toggles(el)[0].click();
    await flush();
    expect(counts(el)).toEqual(["50+ posts in the last 24 h"]);
    expect(toggles(el)[0].getAttribute("aria-pressed")).toBe("true");
  });

  it("speaks Arabic, right to left, with the tag isolated", async () => {
    setLocale("ar");
    serve({ day: DAY, week: WEEK });
    const el = await mount();
    expect(document.documentElement.dir).toBe("rtl");
    expect(toggles(el).map((b) => b.textContent?.trim())).toEqual(["آخر 24 ساعة", "آخر 7 أيام"]);
    expect(counts(el)[0]).toBe("20 منشور أو أكثر في آخر 7 أيام");
    expect(counts(el)[1]).toBe("1K منشور أو أكثر في آخر 7 أيام");
    expect(rows(el)[2].querySelector("bdi")?.textContent).toBe("قهوة");
    expect(el.textContent).not.toContain("اليوم");
    toggles(el)[0].click();
    await flush();
    expect(counts(el)).toEqual(["50 منشور أو أكثر في آخر 24 ساعة"]);
  });

  it("the compact rail shows the same honest lines and hides itself when empty", async () => {
    serve({ day: [], week: [{ tag: "nile", posts_floor: null, window: "week" }] });
    let el = await mount({ compact: true, limit: 5 });
    expect(el.querySelector('[data-testid="rail-trending"]')).not.toBeNull();
    expect(counts(el)).toEqual([]);
    app?.unmount();
    host?.remove();
    vi.restoreAllMocks();
    serve({ day: [], week: [] });
    el = await mount({ compact: true });
    expect(el.querySelector('[data-testid="rail-trending"]')).toBeNull();
  });
});
