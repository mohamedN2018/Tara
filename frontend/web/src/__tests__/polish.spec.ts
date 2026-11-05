// Polish track: page categories in the reader's language, the intro/bio
// de-duplication, studio ranges and CSV, the activity log's sentences and
// links, settings search, and the name hover card's open rules and actions.
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, createApp, h, nextTick } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import NameHoverCard from "@/components/social/NameHoverCard.vue";
import EngagementChart from "@/components/studio/EngagementChart.vue";
import { searchSettings, SETTINGS_ENTRIES } from "@/components/settings/settingsIndex";
import { i18n } from "@/i18n";
import { api } from "@/lib/api";
import { groupByDay, rowLink, sentenceKey } from "@/lib/activityLog";
import { friendState, resetHoverCards } from "@/lib/hoverCard";
import { categorySlug, pageCategoryLabel } from "@/lib/pageCategory";
import { sameText } from "@/lib/profileFormat";
import { csvCell, dayEdge, lastDays, localDay, metricOf, spanDays, toCsv } from "@/lib/studioRange";
import { activityService, type ActivityRow } from "@/services/activity";
import { graphService } from "@/services/graph";
import { profileService } from "@/services/profile";
import { relationshipsService } from "@/services/relationships";
import { studioService } from "@/services/studio";
import { useAuthStore } from "@/stores/auth";

const g = i18n.global as unknown as { t: (k: string) => string; te: (k: string) => boolean; locale: { value: string } };

describe("page categories", () => {
  afterEach(() => (g.locale.value = "en"));

  it("slugs free-text categories the way the i18n map is keyed", () => {
    expect(categorySlug("News & Media")).toBe("news_and_media");
    expect(categorySlug("Science & Technology")).toBe("science_and_technology");
    expect(categorySlug("  Shopping & Retail ")).toBe("shopping_and_retail");
  });

  it("shows a known category in Arabic and anything else as typed", () => {
    g.locale.value = "ar";
    expect(pageCategoryLabel("Science", g)).toBe("علوم");
    expect(pageCategoryLabel("Entertainment", g)).toBe("ترفيه");
    expect(pageCategoryLabel("News & Media", g)).toBe("أخبار وإعلام");
    expect(pageCategoryLabel("مطاعم شعبية", g)).toBe("مطاعم شعبية");
    expect(pageCategoryLabel("Quantum knitting", g)).toBe("Quantum knitting");
    expect(pageCategoryLabel("", g)).toBe("");
    g.locale.value = "en";
    expect(pageCategoryLabel("science", g)).toBe("Science");
  });
});

describe("intro and bio", () => {
  it("treats the same words as the same text", () => {
    expect(sameText("طالب هندسة", " طالب  هندسة ")).toBe(true);
    expect(sameText("Engineer", "engineer")).toBe(true);
    expect(sameText("Engineer", "Engineer at Tara")).toBe(false);
    expect(sameText("", "")).toBe(false);
  });
});

describe("studio ranges and CSV", () => {
  it("builds local-day ranges", () => {
    const today = new Date(2026, 10, 5, 15, 0);
    expect(lastDays(7, today)).toEqual({ from: "2026-10-30", to: "2026-11-05" });
    expect(localDay(today)).toBe("2026-11-05");
    expect(spanDays("2026-11-01", "2026-11-28")).toBe(28);
    expect(spanDays("2026-11-02", "2026-11-01")).toBe(0);
    expect(spanDays("nope", "2026-11-01")).toBe(0);
    expect(new Date(dayEdge("2026-11-05")!).getTime()).toBe(new Date(2026, 10, 5).getTime());
    expect(new Date(dayEdge("2026-11-05", true)!).getTime()).toBe(new Date(2026, 10, 6).getTime());
  });

  it("engagement adds every interaction, views stay their own", () => {
    const day = { date: "2026-11-01", views: 9, reactions: 3, comments: 2, shares: 1, saves: 4, posts: 1 };
    expect(metricOf(day, "engagement")).toBe(10);
    expect(metricOf(day, "views")).toBe(9);
  });

  it("quotes cells and defuses spreadsheet formulas", () => {
    expect(csvCell('say "hi"')).toBe('"say ""hi"""');
    expect(csvCell("=HYPERLINK(1)")).toBe(`"'=HYPERLINK(1)"`);
    expect(csvCell("+1")).toBe(`"'+1"`);
    expect(csvCell(5)).toBe('"5"');
    const csv = toCsv(["a", "b"], [["مرحبا", 1]]);
    expect(csv.startsWith("﻿")).toBe(true);
    expect(csv).toContain('"مرحبا","1"');
  });

  it("asks the server for days, text and dates", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue({ data: { data: { days: [] } } });
    await studioService.daily("2026-11-01", "2026-11-07", "Africa/Cairo");
    expect(get).toHaveBeenCalledWith("/posts/studio/daily/", { params: { from: "2026-11-01", to: "2026-11-07", tz: "Africa/Cairo" } });
    await studioService.published({ q: " sunset ", from: "2026-11-01T00:00:00.000Z" }, null, 100);
    expect(get).toHaveBeenLastCalledWith("/posts/studio/published/", {
      params: { type: undefined, q: "sunset", from: "2026-11-01T00:00:00.000Z", to: undefined, cursor: undefined, limit: 100 },
    });
    vi.restoreAllMocks();
  });
});

describe("engagement chart", () => {
  let app: App | null = null;
  afterEach(() => {
    app?.unmount();
    app = null;
    document.body.innerHTML = "";
  });

  it("reads each day with the keyboard and offers a table", async () => {
    g.locale.value = "en";
    const el = document.createElement("div");
    document.body.appendChild(el);
    const points = [
      { date: "2026-11-01", value: 2 },
      { date: "2026-11-02", value: 5 },
      { date: "2026-11-03", value: 0 },
    ];
    app = createApp({ render: () => h(EngagementChart, { points, label: "Engagement" }) }).use(i18n);
    app.mount(el);
    const svg = el.querySelector("svg")!;
    expect(svg.getAttribute("aria-label")).toContain("7");
    svg.dispatchEvent(new KeyboardEvent("keydown", { key: "Home", bubbles: true }));
    await nextTick();
    expect(el.querySelector('[data-testid="engagement-tooltip"]')?.textContent).toContain("2");
    svg.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    await nextTick();
    expect(el.querySelector('[data-testid="engagement-tooltip"]')?.textContent).toContain("5");
    (el.querySelector('[data-testid="engagement-table-toggle"]') as HTMLButtonElement).click();
    await nextTick();
    expect(el.querySelectorAll('[data-testid="engagement-table"] tbody tr')).toHaveLength(3);
  });
});

describe("activity log", () => {
  const me = "me-1";
  const row = (over: Partial<ActivityRow>): ActivityRow => ({
    id: "r1",
    kind: "reaction",
    created_at: "2026-11-05T10:00:00Z",
    reaction: "love",
    text: "",
    item_type: null,
    item_id: null,
    target: { post_id: "p1", author_id: "u2", author_type: "user", type: "text", excerpt: "hi" },
    ...over,
  });

  it("picks the sentence by kind and whose post it was", () => {
    expect(sentenceKey(row({}), me)).toBe("reaction_other");
    expect(sentenceKey(row({ target: { ...row({}).target!, author_id: me } }), me)).toBe("reaction_own");
    expect(sentenceKey(row({ target: null }), me)).toBe("reaction_gone");
    expect(sentenceKey(row({ kind: "post", item_type: "share" }), me)).toBe("shared");
    expect(sentenceKey(row({ kind: "save", item_type: "listing", target: null }), me)).toBe("saved_listing");
    expect(sentenceKey(row({ kind: "save", item_type: "post" }), me)).toBe("saved_post_other");
    // A page's post is never "your own", even when the ids happened to match.
    expect(sentenceKey(row({ target: { ...row({}).target!, author_id: me, author_type: "page" } }), me)).toBe("reaction_other");
  });

  it("every sentence key exists in both languages", () => {
    const keys = ["posted", "shared", "saved_listing", "saved_page", "saved_video"];
    for (const k of ["saved_post", "comment", "reaction", "comment_reaction", "vote"]) for (const w of ["own", "other", "gone"]) keys.push(`${k}_${w}`);
    for (const locale of ["en", "ar"]) {
      g.locale.value = locale;
      for (const k of keys) expect(g.te(`polish.activity.rows.${k}`), `${locale} ${k}`).toBe(true);
    }
    g.locale.value = "en";
  });

  it("links to what is still visible, and to a comment in place", () => {
    expect(rowLink(row({}))).toBe("/posts/p1");
    expect(rowLink(row({ target: null }))).toBeNull();
    expect(rowLink(row({ kind: "comment", item_id: "c9" }))).toEqual({ path: "/posts/p1", query: { comment: "c9" } });
    expect(rowLink(row({ kind: "save", item_type: "listing", item_id: "l1", target: null }))).toBe("/marketplace/l1");
  });

  it("groups by local day in server order", () => {
    const a = new Date(2026, 10, 5, 23, 0).toISOString();
    const b = new Date(2026, 10, 5, 1, 0).toISOString();
    const c = new Date(2026, 10, 4, 12, 0).toISOString();
    const groups = groupByDay([{ created_at: a }, { created_at: b }, { created_at: c }]);
    expect(groups.map((x) => [x.day, x.rows.length])).toEqual([
      ["2026-11-05", 2],
      ["2026-11-04", 1],
    ]);
  });

  it("reads my activity by kind and cursor", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue({ data: { data: [], page: { has_more: false } } });
    await activityService.list("comment", "abc");
    expect(get).toHaveBeenCalledWith("/posts/activity/", { params: { kind: "comment", cursor: "abc" } });
    vi.restoreAllMocks();
  });
});

describe("settings search", () => {
  it("finds settings by title or keyword in both languages", () => {
    g.locale.value = "en";
    expect(searchSettings("block", g.t).map((e) => e.key)).toContain("blocking");
    expect(searchSettings("dark", g.t).map((e) => e.key)).toContain("theme");
    expect(searchSettings("2fa", g.t).map((e) => e.key)).toEqual(["twoFactor"]);
    g.locale.value = "ar";
    expect(searchSettings("الحظر", g.t).map((e) => e.key)).toContain("blocking");
    expect(searchSettings("كلمة السر", g.t).map((e) => e.key)).toContain("password");
    expect(searchSettings("   ", g.t)).toEqual([]);
    g.locale.value = "en";
  });

  it("every entry points into the settings centre", () => {
    for (const e of SETTINGS_ENTRIES) expect(e.to.startsWith("/settings/")).toBe(true);
  });
});

describe("name hover card", () => {
  let app: App | null = null;
  let hoverable = true;

  beforeEach(() => {
    resetHoverCards();
    vi.useFakeTimers();
    hoverable = true;
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: hoverable && q.includes("hover"), media: q, addEventListener() {}, removeEventListener() {} }));
    vi.spyOn(profileService, "getById").mockResolvedValue({ handle: "sara", display_name: "سارة", avatar_media_id: null, cover_media_id: null, intro: "Designer", visibility: "public" });
    vi.spyOn(relationshipsService, "counts").mockResolvedValue({ friends_count: 3, followers_count: 12, following_count: 1, mutual_count: 2 });
    vi.spyOn(graphService, "followingIds").mockResolvedValue([]);
    vi.spyOn(graphService, "friends").mockResolvedValue([]);
    vi.spyOn(graphService, "incomingRequests").mockResolvedValue([]);
    vi.spyOn(graphService, "outgoingRequests").mockResolvedValue([]);
  });
  afterEach(() => {
    app?.unmount();
    app = null;
    document.body.innerHTML = "";
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  async function mount(id = "u2") {
    const pinia = createPinia();
    setActivePinia(pinia);
    g.locale.value = "en";
    const auth = useAuthStore();
    auth.account = { id: "me-1", email: "me@example.com" } as never;
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:p(.*)*", name: "x", component: { template: "<div/>" } }, { path: "/u/id/:id", name: "profile-by-id", component: { template: "<div/>" } }, { path: "/pages/id/:id", name: "page-by-id", component: { template: "<div/>" } }] });
    const el = document.createElement("div");
    document.body.appendChild(el);
    app = createApp({ render: () => h(NameHoverCard, { id }, () => h("a", { href: "#", "data-testid": "name" }, "Sara")) })
      .use(i18n)
      .use(router)
      .use(pinia);
    app.mount(el);
    return el;
  }
  async function settle() {
    await vi.advanceTimersByTimeAsync(600);
    for (let i = 0; i < 6; i++) await nextTick();
  }
  const pointer = (type: string, pointerType: string) => {
    const e = new Event(type, { bubbles: false }) as PointerEvent;
    Object.defineProperty(e, "pointerType", { value: pointerType });
    return e;
  };

  it("opens for a mouse after a pause, with real counts and actions", async () => {
    const el = await mount();
    el.querySelector("span")!.dispatchEvent(pointer("pointerenter", "mouse"));
    expect(el.querySelector('[data-testid="hover-card"]')).toBeNull();
    await settle();
    const card = el.querySelector('[data-testid="hover-card"]');
    expect(card).not.toBeNull();
    expect(card?.querySelector('[data-testid="hover-card-name"]')?.textContent).toContain("سارة");
    expect(card?.querySelector('[data-testid="hover-card-followers"]')?.textContent).toContain("12 followers");
    expect(card?.querySelector('[data-testid="hover-card-mutual"]')?.textContent).toContain("2 mutual friends");
    expect(card?.querySelector('[data-testid="hover-card-add"]')).not.toBeNull();
    expect(card?.querySelector('[data-testid="hover-card-message"]')).not.toBeNull();
  });

  it("never opens on touch", async () => {
    const el = await mount();
    el.querySelector("span")!.dispatchEvent(pointer("pointerenter", "touch"));
    await settle();
    expect(el.querySelector('[data-testid="hover-card"]')).toBeNull();
    expect(profileService.getById).not.toHaveBeenCalled();
  });

  it("says a hidden profile is unavailable (the server's 404)", async () => {
    vi.mocked(profileService.getById).mockRejectedValue(new Error("404"));
    const el = await mount();
    el.querySelector("span")!.dispatchEvent(pointer("pointerenter", "mouse"));
    await settle();
    expect(el.querySelector('[data-testid="hover-card-unavailable"]')).not.toBeNull();
  });

  it("Add friend sends a real request and shows it as sent", async () => {
    const send = vi.spyOn(graphService, "sendFriendRequest").mockResolvedValue("req-1");
    const el = await mount();
    el.querySelector("span")!.dispatchEvent(pointer("pointerenter", "mouse"));
    await settle();
    (el.querySelector('[data-testid="hover-card-add"]') as HTMLButtonElement).click();
    await settle();
    expect(send).toHaveBeenCalledWith("u2");
    expect(el.querySelector('[data-testid="hover-card-requested"]')).not.toBeNull();
  });

  it("is not offered on my own name", async () => {
    const el = await mount("me-1");
    el.querySelector("span")!.dispatchEvent(pointer("pointerenter", "mouse"));
    await settle();
    expect(el.querySelector('[data-testid="hover-card"]')).toBeNull();
  });

  it("works out the friend state from my relations", () => {
    const rel = { following: new Set<string>(), friends: new Set(["a"]), incoming: new Map([["b", "r"]]), outgoing: new Set(["c"]) };
    expect(friendState(rel, "a")).toBe("friends");
    expect(friendState(rel, "b")).toBe("pending_in");
    expect(friendState(rel, "c")).toBe("pending_out");
    expect(friendState(rel, "d")).toBe("none");
  });
});
