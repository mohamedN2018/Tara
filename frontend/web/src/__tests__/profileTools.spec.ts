import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, type Component, createApp, defineComponent, h } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";

import ManagePageRail from "@/components/pages/ManagePageRail.vue";
import PageTransparencyDialog from "@/components/pages/PageTransparencyDialog.vue";
import MediaTheater from "@/components/post/MediaTheater.vue";
import { i18n } from "@/i18n";
import { api } from "@/lib/api";
import {
  clampCropOffset,
  clampPan,
  coverOffsetAfterDrag,
  coverPosition,
  cropSourceRect,
  normaliseCoverOffset,
  stepZoom,
} from "@/lib/photoFrame";
import { mediaService } from "@/services/media";
import type { Page } from "@/services/pages";
import { postService, timelineParams } from "@/services/post";
import { useAuthStore } from "@/stores/auth";

// Plan 08, profile track: photo theater, cover / avatar framing, the posts
// filters and the Page owner tools.

describe("photo framing maths", () => {
  it("steps the theater zoom and stops at the ends", () => {
    expect(stepZoom(1, 1)).toBe(1.5);
    expect(stepZoom(1.5, 1)).toBe(2);
    expect(stepZoom(3, 1)).toBe(3);
    expect(stepZoom(2, -1)).toBe(1.5);
    expect(stepZoom(1, -1)).toBe(1);
  });

  it("keeps a zoomed photo's pan inside its extra size", () => {
    expect(clampPan({ x: 999, y: -999 }, 2, { width: 100, height: 50 })).toEqual({ x: 50, y: -25 });
    expect(clampPan({ x: 10, y: 10 }, 1, { width: 100, height: 50 })).toEqual({ x: 0, y: 0 });
  });

  it("moves the cover with the drag and clamps it to 0..100", () => {
    const frame = { width: 1000, height: 300 };
    const tall = { width: 1000, height: 1000 }; // 700 px of overflow
    expect(coverOffsetAfterDrag(50, 0, frame, tall)).toBe(50);
    expect(coverOffsetAfterDrag(50, 70, frame, tall)).toBe(40); // dragging down shows more of the top
    expect(coverOffsetAfterDrag(50, -70, frame, tall)).toBe(60);
    expect(coverOffsetAfterDrag(10, 5000, frame, tall)).toBe(0);
    expect(coverOffsetAfterDrag(90, -5000, frame, tall)).toBe(100);
    // A wide photo has no vertical room: it stays where it was.
    expect(coverOffsetAfterDrag(30, 100, frame, { width: 3000, height: 600 })).toBe(30);
  });

  it("normalises offsets from the server", () => {
    expect(normaliseCoverOffset(undefined)).toBe(50);
    expect(normaliseCoverOffset(140)).toBe(100);
    expect(normaliseCoverOffset("12")).toBe(12);
    expect(coverPosition(25)).toBe("50% 25%");
  });

  it("crops the square the circle shows", () => {
    const natural = { width: 2000, height: 1000 };
    // Zoom 1, centred: the middle 1000 x 1000.
    expect(cropSourceRect({ x: 0, y: 0 }, 1, natural, 200)).toEqual({ sx: 500, sy: 0, size: 1000 });
    // Zoom 2: a 500 px square, still centred.
    expect(cropSourceRect({ x: 0, y: 0 }, 2, natural, 200)).toEqual({ sx: 750, sy: 250, size: 500 });
    // Dragged fully right (offset clamped): the left edge of the photo.
    expect(clampCropOffset({ x: 9999, y: 0 }, 1, natural, 200)).toEqual({ x: 100, y: 0 });
    expect(cropSourceRect({ x: 9999, y: 0 }, 1, natural, 200).sx).toBe(0);
  });
});

describe("timeline filters", () => {
  it("sends the author, year and media, or tagged_id for other people's posts", () => {
    expect(timelineParams("u1", undefined, {})).toMatchObject({ author_id: "u1", tagged_id: undefined, year: undefined });
    expect(timelineParams("u1", "c2", { year: 2024, media: "photo" })).toMatchObject({
      author_id: "u1",
      year: 2024,
      media: "photo",
      cursor: "c2",
    });
    expect(timelineParams("u1", undefined, { postedBy: "others" })).toMatchObject({ author_id: undefined, tagged_id: "u1" });
  });

  it("asks the saved list for reels only", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue({
      data: { data: [{ id: "s1", item_id: "r1", item_type: "post" }], page: { next_cursor: null, has_more: false } },
    });
    const page = await postService.savedReelIds();
    expect(get).toHaveBeenCalledWith("/saved/", { params: { post_type: "reel", cursor: undefined } });
    expect(page).toEqual({ ids: ["r1"], nextCursor: null, hasMore: false });
  });
});

// ---- components ----------------------------------------------------------------

const Blank = defineComponent({ render: () => null });
let app: App | null = null;
let host: HTMLElement | null = null;
let router: Router;
let pinia: ReturnType<typeof createPinia>;

async function flush() {
  for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0));
}

async function mount(component: Component, props: Record<string, unknown> = {}, slots?: Record<string, () => unknown>) {
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/home", name: "home", component: Blank },
      { path: "/studio", name: "studio", component: Blank },
      { path: "/ads", name: "ads", component: Blank },
      { path: "/pages/id/:id/inbox", name: "page-inbox", component: Blank },
      { path: "/pages/:handle", name: "page", component: Blank },
      { path: "/:rest(.*)*", component: Blank },
    ],
  });
  await router.push("/home");
  await router.isReady();
  host = document.createElement("div");
  document.body.appendChild(host);
  const Root = defineComponent({ setup: () => () => h(component, props, slots) });
  app = createApp(Root);
  app.use(pinia).use(router).use(i18n);
  app.mount(host);
  await flush();
  return host;
}

const page = (extra: Partial<Page> = {}): Page =>
  ({
    id: "p1",
    handle: "nilebooks",
    name: "Nile Books",
    category: "",
    description: "",
    location: "",
    status: "published",
    avatar_media_id: null,
    cover_media_id: null,
    contact: {},
    owner_account_id: "o1",
    my_role: "owner",
    viewer_following: null,
    followers_count: null,
    created_at: "2025-01-02T00:00:00Z",
    ...extra,
  }) as Page;

beforeEach(() => {
  pinia = createPinia();
  setActivePinia(pinia);
  i18n.global.locale.value = "en";
  useAuthStore().account = { id: "me-1", email: "me@example.com" } as never;
  vi.spyOn(mediaService, "resolveUrl").mockResolvedValue("blob:photo");
});

afterEach(() => {
  app?.unmount();
  host?.remove();
  document.body.innerHTML = "";
  app = null;
  host = null;
  vi.restoreAllMocks();
});

describe("MediaTheater", () => {
  it("shows the panel slot and zooms in and out", async () => {
    await mount(MediaTheater, { mediaIds: ["m1", "m2"], index: 0, authorName: "Sara" }, { panel: () => h("p", { id: "panel-body" }, "post text") });
    const theater = document.querySelector<HTMLElement>("[data-testid='media-theater']")!;
    expect(theater.querySelector("#panel-body")?.textContent).toBe("post text");
    const stage = theater.querySelector<HTMLElement>("[data-testid='theater-stage']")!;
    const zoomIn = theater.querySelector<HTMLButtonElement>("[data-testid='theater-zoom-in']")!;
    const zoomOut = theater.querySelector<HTMLButtonElement>("[data-testid='theater-zoom-out']")!;
    expect(zoomOut.disabled).toBe(true);
    zoomIn.click();
    await flush();
    expect(stage.dataset.zoom).toBe("1.5");
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "+" }));
    await flush();
    expect(stage.dataset.zoom).toBe("2");
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "-" }));
    await flush();
    expect(stage.dataset.zoom).toBe("1.5");
    // The toggle hides and shows the panel.
    const toggle = theater.querySelector<HTMLButtonElement>("[data-testid='theater-panel-toggle']")!;
    const panel = theater.querySelector<HTMLElement>("[data-testid='theater-panel']")!;
    const before = panel.style.display;
    toggle.click();
    await flush();
    expect(panel.style.display).not.toBe(before);
  });

  it("has no panel or panel toggle without the slot", async () => {
    await mount(MediaTheater, { mediaIds: ["m1"], index: 0, authorName: "Sara" });
    expect(document.querySelector("[data-testid='theater-panel']")).toBeNull();
    expect(document.querySelector("[data-testid='theater-panel-toggle']")).toBeNull();
  });
});

describe("Manage Page rail", () => {
  it("shows only the tools a role may use", async () => {
    await mount(ManagePageRail, { page: page({ my_role: "owner" }) });
    const keys = () => [...document.querySelectorAll<HTMLElement>("[data-testid^='manage-page-']")].map((e) => e.dataset.testid);
    expect(keys()).toEqual(
      expect.arrayContaining(["manage-page-rail", "manage-page-studio", "manage-page-inbox", "manage-page-ads", "manage-page-settings", "manage-page-transparency"]),
    );
    expect(document.querySelector<HTMLAnchorElement>("[data-testid='manage-page-inbox']")?.getAttribute("href")).toBe("/pages/id/p1/inbox");
    app?.unmount();
    document.body.innerHTML = "";

    await mount(ManagePageRail, { page: page({ my_role: "moderator" }) });
    expect(keys()).toContain("manage-page-inbox");
    expect(keys()).not.toContain("manage-page-ads");
    expect(keys()).not.toContain("manage-page-settings");
  });

  it("is not there for visitors", async () => {
    await mount(ManagePageRail, { page: page({ my_role: null }) });
    expect(document.querySelector("[data-testid='manage-page-rail']")).toBeNull();
  });
});

describe("Page transparency", () => {
  it("shows the created date, the category and the past names", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue({
      data: {
        data: {
          page_id: "p1",
          name: "Nile Readers",
          category: "Books",
          created_at: "2025-01-02T00:00:00Z",
          name_changes: [{ old_name: "Nile Books", new_name: "Nile Readers", changed_at: "2026-03-04T00:00:00Z" }],
        },
      },
    });
    await mount(PageTransparencyDialog, { page: page() });
    expect(get).toHaveBeenCalledWith("/pages/id/p1/transparency/");
    const dialog = document.querySelector<HTMLElement>("[data-testid='page-transparency']")!;
    expect(dialog.textContent).toContain("2025");
    expect(dialog.querySelector("[data-testid='page-transparency-renames']")?.textContent).toContain("Nile Books");
  });

  it("says when the name never changed", async () => {
    vi.spyOn(api, "get").mockResolvedValue({
      data: { data: { page_id: "p1", name: "Nile Books", category: "", created_at: "2025-01-02T00:00:00Z", name_changes: [] } },
    });
    await mount(PageTransparencyDialog, { page: page() });
    expect(document.querySelector("[data-testid='page-transparency-no-renames']")).not.toBeNull();
  });
});
