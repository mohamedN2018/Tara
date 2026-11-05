import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, createApp, defineComponent, h } from "vue";
import { createMemoryHistory, createRouter, type Router, RouterView } from "vue-router";

import Toaster from "@/components/common/Toaster.vue";
import { reelsMuted } from "@/components/reels/pager";
import { i18n } from "@/i18n";
import { api } from "@/lib/api";
import type { Reel } from "@/services/reels";
import { useToastStore } from "@/stores/toasts";
import ReelsView from "@/views/ReelsView.vue";

// The reels "more" sheet: Save / Unsave and Report reuse the post's services;
// "Not interested" offers Undo on its toast, which puts the reel back.

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

// The shell (menus, rails, sockets) is not what these tests are about.
vi.mock("@/components/layout/AppShell.vue", () => ({
  default: defineComponent({ setup: (_p, { slots }) => () => h("div", slots.default?.()) }),
}));

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
    is_saved: false,
    created_at: "2026-11-05T10:00:00Z",
    reel: {
      media_id: `2000000${i}-0000-7000-8000-000000000000`,
      cover_media_id: null,
      duration_ms: 15000,
      width: 720,
      height: 1280,
      view_count: 3,
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
let router: Router;
let reels: Reel[];

async function flush() {
  for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0));
}

async function mountAt(path: string) {
  host = document.createElement("div");
  document.body.appendChild(host);
  const pinia = createPinia();
  setActivePinia(pinia);
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/reels", name: "reels", component: ReelsView },
      { path: "/reels/:id", name: "reel", component: ReelsView },
      { path: "/u/id/:id", name: "profile-by-id", component: { render: () => h("div") } },
      { path: "/pages/id/:id", name: "page-by-id", component: { render: () => h("div") } },
      { path: "/posts/:id", name: "post", component: { render: () => h("div") } },
      { path: "/:p(.*)*", component: { render: () => h("div") } },
    ],
  });
  await router.push(path);
  await router.isReady();
  app = createApp({ render: () => [h(RouterView), h(Toaster)] });
  app.use(pinia).use(router).use(i18n);
  app.mount(host);
  await flush();
}

const q = (sel: string) => document.body.querySelector<HTMLElement>(sel);
const slides = () => Array.from(document.body.querySelectorAll<HTMLElement>("[data-testid=reel-slide]")).map((s) => s.dataset.reelId);

beforeEach(() => {
  i18n.global.locale.value = "en";
  reelsMuted.value = true;
  reels = [reel(1), reel(2)];
  vi.spyOn(api, "get").mockImplementation(async (url: string) => {
    if (url === "/reels/") return { data: { data: reels, page: { next_cursor: null, prev_cursor: null, has_more: false } } };
    const one = reels.find((r) => url === `/reels/${r.id}/`);
    if (one) return { data: { data: one } };
    return playback;
  });
  vi.spyOn(api, "post").mockImplementation(async (url: string) => {
    if (url.endsWith("/view/")) return { data: { data: { view_count: 4, counted: true } } };
    return { data: { data: [] } };
  });
  vi.spyOn(api, "delete").mockResolvedValue({ data: {} });
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
  Element.prototype.scrollTo = function scrollTo() {} as typeof Element.prototype.scrollTo;
});

afterEach(() => {
  app?.unmount();
  host?.remove();
  app = null;
  host = null;
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

describe("reels more sheet", () => {
  it("saves and unsaves the reel through the post's saved items", async () => {
    const id = reels[0].id;
    await mountAt(`/reels/${id}?sheet=more`);
    const save = q("[data-testid=reel-save]")!;
    expect(save.textContent).toContain("Save reel");
    save.click();
    await flush();
    expect(api.post).toHaveBeenCalledWith(`/posts/${id}/save/`, undefined);
    expect(router.currentRoute.value.query.sheet).toBeUndefined();
    expect(useToastStore().items.map((t) => t.text)).toContain("Reel saved.");

    await router.push({ query: { sheet: "more" } });
    await flush();
    expect(q("[data-testid=reel-save]")!.textContent).toContain("Unsave reel");
    q("[data-testid=reel-save]")!.click();
    await flush();
    expect(api.delete).toHaveBeenCalledWith(`/posts/${id}/save/`);
  });

  it("reports the reel through the post's report flow", async () => {
    const id = reels[0].id;
    await mountAt(`/reels/${id}?sheet=more`);
    q("[data-testid=reel-report]")!.click();
    await flush();
    const submit = q("[data-testid=reel-report-submit]") as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    const reason = q("[data-testid=reel-report-reason]") as HTMLTextAreaElement;
    reason.value = "  spam  ";
    reason.dispatchEvent(new Event("input"));
    await flush();
    submit.click();
    await flush();
    expect(api.post).toHaveBeenCalledWith(`/posts/${id}/report/`, { reason: "spam" });
    expect(useToastStore().items.map((t) => t.text)).toContain("Report submitted. Thank you.");
  });

  it("hides Report and Not interested on the viewer's own reel", async () => {
    reels = [reel(1, { author_id: "me" }), reel(2)];
    await mountAt(`/reels/${reels[0].id}?sheet=more`);
    const { useAuthStore } = await import("@/stores/auth");
    useAuthStore().account = { id: "me" } as never;
    await flush();
    expect(q("[data-testid=reel-report]")).toBeNull();
    expect(q("[data-testid=reel-not-interested]")).toBeNull();
    expect(q("[data-testid=reel-save]")).not.toBeNull();
  });

  it("undoes 'Not interested' from the toast and puts the reel back", async () => {
    const [first, second] = reels;
    await mountAt(`/reels/${first.id}?sheet=more`);
    q("[data-testid=reel-not-interested]")!.click();
    await flush();
    expect(api.post).toHaveBeenCalledWith(`/reels/${first.id}/hide/`);
    expect(slides()).toEqual([second.id]);
    const undo = q("[data-testid=reel-undo-hide]")!;
    expect(undo.textContent).toContain("Undo");
    undo.click();
    await flush();
    expect(api.delete).toHaveBeenCalledWith(`/reels/${first.id}/hide/`);
    expect(slides()).toEqual([first.id, second.id]);
    expect(q("[data-testid=reel-undo-hide]")).toBeNull();
    expect(useToastStore().items.map((t) => t.text)).toContain("The reel is back in your reels.");
  });
});
