// Track T8: creator studio maths, service calls and the home page's real numbers.
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import { type App, createApp, nextTick } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import { i18n } from "@/i18n";
import { api } from "@/lib/api";
import {
  addDays,
  canScheduleOn,
  dayKey,
  defaultSlot,
  gridRange,
  groupByDay,
  monthGrid,
  moveToDay,
  postTime,
  rescheduleProblem,
  weekGrid,
  zoneLabel,
} from "@/lib/planner";
import { composerService } from "@/services/composer";
import { studioService } from "@/services/studio";
import StudioEngagementView from "@/views/studio/StudioEngagementView.vue";
import StudioHomeView from "@/views/studio/StudioHomeView.vue";
import StudioInsightsView from "@/views/studio/StudioInsightsView.vue";

describe("planner calendar maths", () => {
  it("builds whole Sunday-first weeks around the month", () => {
    const days = monthGrid(new Date(2026, 10, 15)); // November 2026
    expect(days.length % 7).toBe(0);
    expect(days[0].getDay()).toBe(0);
    expect(dayKey(days[0])).toBe("2026-11-01");
    expect(days.some((d) => dayKey(d) === "2026-11-30")).toBe(true);
    expect(dayKey(days[days.length - 1])).toBe("2026-12-05");
  });

  it("a week grid is seven days from Sunday", () => {
    const days = weekGrid(new Date(2026, 10, 4)); // Wednesday
    expect(days).toHaveLength(7);
    expect(dayKey(days[0])).toBe("2026-11-01");
    expect(dayKey(days[6])).toBe("2026-11-07");
  });

  it("asks the API for local midnight to the midnight after the last day", () => {
    const days = weekGrid(new Date(2026, 10, 4));
    const { from, to } = gridRange(days);
    expect(new Date(from).getTime()).toBe(new Date(2026, 10, 1).getTime());
    expect(new Date(to).getTime()).toBe(new Date(2026, 10, 8).getTime());
  });

  it("places scheduled posts on their schedule and published ones on their publication", () => {
    const at = new Date(2026, 10, 10, 20, 0).toISOString();
    const made = new Date(2026, 10, 2, 8, 0).toISOString();
    expect(postTime({ state: "scheduled", publish_at: at, created_at: made })).toBe(at);
    expect(postTime({ state: "published", publish_at: null, created_at: made })).toBe(made);
    const grouped = groupByDay([
      { state: "scheduled", publish_at: at, created_at: made },
      { state: "published", publish_at: null, created_at: made },
    ]);
    expect([...grouped.keys()].sort()).toEqual(["2026-11-02", "2026-11-10"]);
  });

  it("a drag to another day keeps the local time of day", () => {
    const moved = moveToDay(new Date(2026, 10, 10, 20, 30).toISOString(), new Date(2026, 10, 17));
    expect(dayKey(moved)).toBe("2026-11-17");
    expect(moved.getHours()).toBe(20);
    expect(moved.getMinutes()).toBe(30);
  });

  it("refuses the past and beyond the scheduling horizon like the server", () => {
    const now = new Date(2026, 10, 4, 12, 0);
    expect(rescheduleProblem(new Date(2026, 10, 4, 11, 0), now)).toBe("past");
    expect(rescheduleProblem(addDays(now, 400), now)).toBe("far");
    expect(rescheduleProblem(addDays(now, 3), now)).toBeNull();
    expect(canScheduleOn(new Date(2026, 10, 3), now)).toBe(false);
    expect(canScheduleOn(new Date(2026, 10, 4), now)).toBe(true);
  });

  it("defaults a new scheduled post to 09:00, or the next hour today", () => {
    const now = new Date(2026, 10, 4, 12, 20);
    expect(defaultSlot(new Date(2026, 10, 9), now).getHours()).toBe(9);
    const today = defaultSlot(new Date(2026, 10, 4), now);
    expect(today.getHours()).toBe(13);
    expect(today.getTime()).toBeGreaterThan(now.getTime());
  });

  it("labels the zone with its IANA name", () => {
    expect(zoneLabel("en", "Africa/Cairo")).toContain("Africa/Cairo");
    expect(zoneLabel("en", "Not/AZone")).toBe("Not/AZone");
  });
});

describe("studio service", () => {
  afterEach(() => vi.restoreAllMocks());

  it("reads the calendar for a range and the library by type", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue({ data: { data: [], meta: { truncated: false } } });
    await studioService.calendar("2026-11-01T00:00:00Z", "2026-12-06T00:00:00Z");
    expect(get).toHaveBeenCalledWith("/posts/calendar/", {
      params: { from: "2026-11-01T00:00:00Z", to: "2026-12-06T00:00:00Z" },
    });
    await studioService.published("image");
    expect(get).toHaveBeenLastCalledWith("/posts/studio/published/", { params: { type: "image", cursor: undefined } });
  });

  it("opens one draft by id for deep links", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue({ data: { data: { id: "d1", state: "draft" } } });
    const draft = await composerService.draft("d1");
    expect(get).toHaveBeenCalledWith("/posts/drafts/d1/");
    expect(draft.id).toBe("d1");
  });
});

describe("studio home", () => {
  let app: App | null = null;
  afterEach(() => {
    app?.unmount();
    app = null;
    document.body.innerHTML = "";
    vi.restoreAllMocks();
  });

  it("shows the author's real totals and the draft and scheduled counts", async () => {
    vi.spyOn(studioService, "summary").mockResolvedValue({
      posts: 12,
      reactions: 40,
      comments: 7,
      shares: 3,
      saves: 2,
      drafts: 4,
      scheduled: 5,
      top_posts: [],
    });
    vi.spyOn(studioService, "calendar").mockResolvedValue({ data: [], meta: { truncated: false } });
    setActivePinia(createPinia());
    i18n.global.locale.value = "en";
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:p(.*)*", component: { template: "<div/>" } }] });
    const el = document.createElement("div");
    document.body.appendChild(el);
    app = createApp(StudioHomeView).use(i18n).use(router).use(createPinia());
    app.mount(el);
    for (let i = 0; i < 5; i += 1) await nextTick();
    await new Promise((r) => setTimeout(r, 0));
    await nextTick();
    const values = [...el.querySelectorAll('[data-testid="studio-stat-value"]')].map((n) => n.textContent?.trim());
    expect(values).toEqual(["12", "40", "7", "3", "2"]);
    expect(el.querySelector('[data-testid="studio-drafts-count"]')?.textContent).toContain("4");
    expect(el.querySelector('[data-testid="studio-scheduled-count"]')?.textContent).toContain("5");
    // No impressions or reach until telemetry exists.
    expect(el.textContent?.toLowerCase()).not.toContain("impression");
  });
});

describe("studio insights and engagement", () => {
  let app: App | null = null;
  afterEach(() => {
    app?.unmount();
    app = null;
    document.body.innerHTML = "";
    vi.restoreAllMocks();
  });

  async function mountView(component: object) {
    setActivePinia(createPinia());
    i18n.global.locale.value = "en";
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:p(.*)*", component: { template: "<div/>" } }] });
    const el = document.createElement("div");
    document.body.appendChild(el);
    app = createApp(component).use(i18n).use(router).use(createPinia());
    app.mount(el);
    for (let i = 0; i < 5; i += 1) await nextTick();
    await new Promise((r) => setTimeout(r, 0));
    await nextTick();
    return el;
  }

  it("reads insights and pages my posts' comments", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue({ data: { data: { by_type: [], top_posts: [] } } });
    await studioService.insights();
    expect(get).toHaveBeenLastCalledWith("/posts/studio/insights/");
    await studioService.comments("c2");
    expect(get).toHaveBeenLastCalledWith("/posts/studio/comments/", { params: { cursor: "c2" } });
  });

  it("insights show real counts per post type and the average per post", async () => {
    vi.spyOn(studioService, "insights").mockResolvedValue({
      by_type: [{ type: "image", posts: 2, reactions: 5, comments: 2, shares: 1 }],
      top_posts: [],
    });
    const el = await mountView(StudioInsightsView);
    const row = el.querySelector('[data-testid="insights-by-type"] tbody tr');
    const cells = [...(row?.querySelectorAll("td") ?? [])].map((c) => c.textContent?.trim());
    expect(row?.textContent).toContain("Photo");
    expect(cells).toEqual(["2", "5", "2", "1", "4"]);
    expect(el.textContent).toContain("Reach and views are not tracked");
  });

  it("engagement lists comments with the post they are on and opens the thread", async () => {
    vi.spyOn(studioService, "comments").mockResolvedValue({
      data: [
        {
          id: "c1",
          post_id: "p1",
          author_id: "00000000-0000-4000-8000-000000000009",
          parent_id: "c0",
          body: "Great photo",
          reaction_count: 0,
          created_at: new Date().toISOString(),
          post_excerpt: "Sunset at the beach",
          post_type: "image",
        },
      ],
      page: { next_cursor: null, prev_cursor: null, has_more: false },
    });
    vi.spyOn(api, "get").mockResolvedValue({ data: { data: [] } });
    const el = await mountView(StudioEngagementView);
    const item = el.querySelector('[data-comment="c1"]');
    expect(item?.textContent).toContain("Great photo");
    expect(item?.textContent).toContain("On: Sunset at the beach");
    expect(item?.querySelector('[data-testid="studio-comment-open"]')?.getAttribute("href")).toBe("/posts/p1?comment=c1&thread=c0");
  });
});
