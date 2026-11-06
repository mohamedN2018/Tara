import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, createApp, h } from "vue";

import InterestProfile from "@/components/feed/InterestProfile.vue";
import { i18n, setLocale } from "@/i18n";
import { api } from "@/lib/api";
import type { InterestProfile as Profile, InterestRow } from "@/services/feed";

// Tara Intelligence WP 6.4 / 8.5-B2: interests grouped by tier, with the server's
// counts by event type (never item ids), edit, delete and the topic picker.

let app: App | null = null;
let host: HTMLElement | null = null;
let changed = 0;

async function flush() {
  for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0));
}

const row = (key: string, extra: Partial<InterestRow> = {}): InterestRow => ({
  dim: "topic",
  key,
  label_ar: `ar-${key}`,
  label_en: `en-${key}`,
  source: "inferred",
  counts: {},
  updated_at: "2026-11-05T00:00:00Z",
  ...extra,
});

const PROFILE: Profile = {
  tiers: {
    explicit: [row("cooking", { source: "explicit", polarity: "like", counts: { onboarding: 1 } })],
    emerging: [row("tech", { counts: { reaction: 3, post_open: 5, video_complete: 0 } })],
    short: [],
    long: [row("football", { counts: { comment: 2, mystery_event: 4 } })],
    negative: [row("gossip", { source: "explicit", polarity: "dislike" })],
  },
  muted_topics: [],
  hidden_creators: [],
  sensitive_inference: false,
};

async function mount(profile: Profile = PROFILE) {
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp({ render: () => h(InterestProfile, { profile, onChanged: () => (changed += 1) }) });
  app.use(createPinia()).use(i18n);
  app.mount(host);
  await flush();
  return host;
}
const tier = (el: HTMLElement, name: string) => el.querySelector<HTMLElement>(`[data-testid="interest-tier-${name}"]`);

beforeEach(() => {
  setActivePinia(createPinia());
  setLocale("en");
  changed = 0;
  vi.spyOn(api, "get").mockResolvedValue({ data: { data: [] } });
});

afterEach(() => {
  app?.unmount();
  host?.remove();
  app = null;
  host = null;
  vi.restoreAllMocks();
  setLocale("en");
});

describe("interests by tier (WP 8.5-B2)", () => {
  it("lists each non-empty tier in order, with its counts by event type", async () => {
    const el = await mount();
    const titles = [...el.querySelectorAll("h3")].map((n) => n.textContent?.trim());
    expect(titles).toEqual(["You chose", "New interest", "Long-term", "Less interested"]);
    expect(tier(el, "short")).toBeNull();
    const counts = tier(el, "emerging")!.querySelector('[data-testid="interest-counts"]')!.textContent;
    // Largest first; a zero is not shown.
    expect(counts).toBe("opens: 5 · reactions: 3");
    // An unknown event type is "other activity", with the server's number.
    expect(tier(el, "long")!.textContent).toContain("other activity: 4");
    expect(tier(el, "long")!.textContent).toContain("comments: 2");
    expect(tier(el, "explicit")!.textContent).toContain("Interested");
  });

  it("never shows an item id or a number the server did not send", async () => {
    const el = await mount();
    expect(el.textContent).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-/);
    const numbers = (el.textContent ?? "").match(/\d+/g) ?? [];
    expect(numbers.sort()).toEqual(["1", "2", "3", "4", "5"]);
  });

  it("edits with an explicit choice and deletes a row", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: {} });
    const del = vi.spyOn(api, "delete").mockResolvedValue({ data: null });
    const el = await mount();
    tier(el, "emerging")!.querySelector<HTMLElement>('[data-testid="interest-dislike"]')!.click();
    await flush();
    expect(post).toHaveBeenCalledWith("/feed/preferences/profile/", { dim: "topic", key: "tech", polarity: "dislike" });
    tier(el, "long")!.querySelector<HTMLElement>('[data-testid="interest-remove"]')!.click();
    await flush();
    expect(del).toHaveBeenCalledWith("/feed/preferences/profile/topic/football/");
    expect(changed).toBe(2);
  });

  it("adds a topic from the picker (GET /feed/topics/?q=)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const get = vi.spyOn(api, "get").mockResolvedValue({ data: { data: [{ slug: "travel", label_ar: "سفر", label_en: "Travel" }] } });
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: {} });
    const el = await mount();
    el.querySelector<HTMLElement>('[data-testid="interest-add"]')!.click();
    await flush();
    const input = el.querySelector<HTMLInputElement>('[data-testid="topic-search"]')!;
    input.value = "tra";
    input.dispatchEvent(new Event("input"));
    await vi.advanceTimersByTimeAsync(300);
    await flush();
    expect(get).toHaveBeenLastCalledWith("/feed/topics/", { params: { q: "tra", limit: 20 } });
    el.querySelector<HTMLElement>('[data-testid="topic-like-travel"]')!.click();
    await flush();
    expect(post).toHaveBeenCalledWith("/feed/preferences/profile/", { dim: "topic", key: "travel", polarity: "like" });
    vi.useRealTimers();
  });

  it("says so when there is nothing yet", async () => {
    const el = await mount({ tiers: {}, muted_topics: [], hidden_creators: [], sensitive_inference: false });
    expect(el.querySelector('[data-testid="interests-empty"]')).not.toBeNull();
  });

  it("speaks Arabic with the Arabic labels", async () => {
    setLocale("ar");
    const el = await mount();
    expect(document.documentElement.dir).toBe("rtl");
    expect(tier(el, "emerging")!.textContent).toContain("اهتمام جديد");
    expect(tier(el, "emerging")!.textContent).toContain("ar-tech");
  });
});
